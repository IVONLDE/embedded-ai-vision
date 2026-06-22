/* SPDX-License-Identifier: MIT */
/*
 * gRPC Server — 模型更新与远程管控
 *
 * 功能: 接收 PC 管控端的 gRPC 请求
 *   - PushModel:    推送新模型 → 热加载
 *   - SwitchScene:  切换推理场景
 *   - GetStatus:    查询设备状态
 *   - UpdateConfig: 更新运行时参数
 *   - Restart:      优雅重启推理服务
 *   - GetVersionInfo: 查询版本信息 (OTA)
 *   - PushAppUpdate: 应用二进制更新 (OTA)
 *   - Rollback:     版本回滚 (OTA)
 */

#include "grpc_server.h"
#include "ota_manager.h"

#ifdef PROTO_GENERATED
#include <grpcpp/grpcpp.h>
#include "generated/edge_service.pb.h"
#include "generated/edge_service.grpc.pb.h"
#endif

#include <cstdio>
#include <fstream>
#include <sstream>
#include <thread>
#include <sys/stat.h>
#include <sys/statvfs.h>
#include <unistd.h>
#include <signal.h>
#include <openssl/sha.h>

/* ── 内部 OTA Manager 引用 ─────────────────────────────── */
static OtaManager *g_ota_manager = nullptr;

/* ── SHA256 工具函数 ───────────────────────────────────── */
std::string GrpcServer::compute_sha256(const std::string &data)
{
    unsigned char hash[SHA256_DIGEST_LENGTH];
    SHA256_CTX sha256;
    SHA256_Init(&sha256);
    SHA256_Update(&sha256, data.c_str(), data.size());
    SHA256_Final(hash, &sha256);

    std::string hex;
    hex.reserve(SHA256_DIGEST_LENGTH * 2);
    static const char *hex_chars = "0123456789abcdef";
    for (int i = 0; i < SHA256_DIGEST_LENGTH; i++) {
        hex.push_back(hex_chars[(hash[i] >> 4) & 0x0F]);
        hex.push_back(hex_chars[hash[i] & 0x0F]);
    }
    return hex;
}

std::string GrpcServer::compute_file_sha256(const std::string &path)
{
    std::ifstream ifs(path, std::ios::binary);
    if (!ifs.is_open()) return "";

    SHA256_CTX sha256;
    SHA256_Init(&sha256);

    char buf[8192];
    while (ifs.read(buf, sizeof(buf))) {
        SHA256_Update(&sha256, buf, ifs.gcount());
    }
    if (ifs.gcount() > 0) {
        SHA256_Update(&sha256, buf, ifs.gcount());
    }

    unsigned char hash[SHA256_DIGEST_LENGTH];
    SHA256_Final(hash, &sha256);

    std::string hex;
    hex.reserve(SHA256_DIGEST_LENGTH * 2);
    static const char *hex_chars = "0123456789abcdef";
    for (int i = 0; i < SHA256_DIGEST_LENGTH; i++) {
        hex.push_back(hex_chars[(hash[i] >> 4) & 0x0F]);
        hex.push_back(hex_chars[hash[i] & 0x0F]);
    }
    return hex;
}

bool GrpcServer::backup_file(const std::string &src, const std::string &dst)
{
    std::ifstream in(src, std::ios::binary);
    if (!in.is_open()) return false;
    std::ofstream out(dst, std::ios::binary);
    if (!out.is_open()) return false;
    out << in.rdbuf();
    return true;
}

/* ── 模型接收 + 校验 + 热加载 ──────────────────────────── */
int GrpcServer::receive_model(const std::string &model_bytes,
                              const std::string &expected_sha256,
                              const std::string &model_name,
                              const std::string &model_version,
                              bool auto_rollback,
                              std::string &previous_version)
{
    if (g_ota_manager) {
        OtaResult res = g_ota_manager->install_model_from_data(
            model_bytes, model_name, model_version,
            expected_sha256, auto_rollback);
        previous_version = res.previous_version;
        return res.status;
    }

    /* fallback: 直接写文件 + 热加载 */
    std::string model_dir = "/opt/edge-ai/models/";
    std::string model_path = model_dir + "current.rknn";
    std::string backup_path = model_dir + ".backup/current.rknn.bak";

    if (!expected_sha256.empty()) {
        std::string actual = compute_sha256(model_bytes);
        if (actual != expected_sha256) {
            fprintf(stderr, "[OTA] SHA256 mismatch\n");
            return -1;
        }
    }

    backup_file(model_path, backup_path);

    std::ofstream out(model_path, std::ios::binary);
    if (!out.is_open()) return -1;
    out.write(model_bytes.data(), model_bytes.size());
    out.close();

    if (_engine) {
        int ret = _engine->hot_reload_model(model_path.c_str());
        if (ret != 0 && auto_rollback) {
            backup_file(backup_path, model_path);
            _engine->hot_reload_model(model_path.c_str());
            return -1;
        }
        return ret;
    }

    return 0;
}

/* ── 场景切换 ──────────────────────────────────────────── */
int GrpcServer::do_switch_scene(const std::string &scene_name)
{
    printf("[gRPC] Switching to scene: %s\n", scene_name.c_str());

    if (!_config) {
        fprintf(stderr, "[gRPC] No config available\n");
        return -1;
    }

    const SceneConfig *target = nullptr;
    for (const auto &scene : _config->scenes) {
        if (scene.name == scene_name) {
            target = &scene;
            break;
        }
    }

    if (!target) {
        fprintf(stderr, "[gRPC] Scene '%s' not found\n", scene_name.c_str());
        return -1;
    }

    if (_engine) {
        int ret = _engine->hot_reload_model(target->model_path.c_str());
        if (ret != 0) {
            fprintf(stderr, "[gRPC] Failed to load scene model\n");
            return -1;
        }
    }

    printf("[gRPC] Scene switched to '%s'\n", scene_name.c_str());
    return 0;
}

/* ── 设备状态查询 ──────────────────────────────────────── */
std::string GrpcServer::get_device_status_json() const
{
    std::ostringstream json;
    json << "{";
    json << "\"device_id\":\"" << (_config ? _config->device_id : "") << "\",";
    json << "\"scene\":\"" << (_config ? _config->active_scene : "") << "\",";
    json << "\"model_version\":\"" << (_config ? _config->inference.model_path : "") << "\"";
    json << "}";
    return json.str();
}

/* ── 版本信息 ──────────────────────────────────────────── */
std::string GrpcServer::get_version_info_json() const
{
    if (g_ota_manager) {
        return g_ota_manager->get_version_info();
    }

    std::ostringstream json;
    json << "{";
    json << "\"device_id\":\"" << (_config ? _config->device_id : "") << "\",";
    json << "\"app_version\":\"1.0.0\",";
    json << "\"model_version\":\"" << (_config ? _config->inference.model_path : "") << "\",";
    json << "\"rollback_available\":false";
    json << "}";
    return json.str();
}

/* ── 应用更新 ──────────────────────────────────────────── */
int GrpcServer::receive_app_update(const std::string &app_data,
                                   const std::string &expected_sha256,
                                   const std::string &app_version,
                                   bool auto_rollback)
{
    if (g_ota_manager) {
        std::string tmp_path = "/tmp/edge-ai-camera.update";
        std::ofstream out(tmp_path, std::ios::binary);
        if (!out.is_open()) return -1;
        out.write(app_data.data(), app_data.size());
        out.close();

        OtaResult res = g_ota_manager->install_app(tmp_path, app_version,
                                                     expected_sha256, auto_rollback);
        return res.status;
    }
    return -1;
}

/* ── 回滚 ──────────────────────────────────────────────── */
int GrpcServer::do_rollback(const std::string &target_type,
                            std::string &rolled_back_version,
                            bool &needs_restart)
{
    if (g_ota_manager) {
        OtaResult res = g_ota_manager->rollback(target_type);
        rolled_back_version = res.version;
        needs_restart = res.needs_restart;
        return res.status;
    }
    return -1;
}

/* ── MQTT 命令转发 ─────────────────────────────────────── */
void GrpcServer::handle_command(const std::string &cmd,
                                const std::string &payload)
{
    printf("[gRPC/OTA] Command: %s\n", cmd.c_str());

    auto extract_param = [&payload](const std::string &key) -> std::string {
        std::string search = "\"" + key + "\"";
        size_t pos = payload.find(search);
        if (pos == std::string::npos) return "";
        pos = payload.find(':', pos);
        if (pos == std::string::npos) return "";
        pos = payload.find_first_not_of(" \t\"", pos + 1);
        if (pos == std::string::npos) return "";
        size_t end = payload.find_first_of(",\"}", pos);
        return payload.substr(pos, end - pos);
    };

    if (cmd == "switch_scene") {
        std::string scene = extract_param("scene");
        if (!scene.empty()) {
            do_switch_scene(scene);
        }
    }
    else if (cmd == "reload_model") {
        if (g_ota_manager) {
            std::string path = extract_param("model_path");
            std::string version = extract_param("version");
            std::string sha256 = extract_param("sha256");
            OtaResult res = g_ota_manager->install_model(path, version, sha256);
            printf("[OTA] Model install: %d - %s\n", res.status, res.message.c_str());
        }
    }
    else if (cmd == "app_update") {
        if (g_ota_manager) {
            std::string path = extract_param("app_path");
            std::string version = extract_param("version");
            std::string sha256 = extract_param("sha256");
            OtaResult res = g_ota_manager->install_app(path, version, sha256);
            printf("[OTA] App install: %d - %s\n", res.status, res.message.c_str());

            if (res.needs_restart) {
                kill(getpid(), SIGTERM);
            }
        }
    }
    else if (cmd == "rollback") {
        if (g_ota_manager) {
            std::string target = extract_param("target");
            if (target.empty()) target = "model";
            OtaResult res = g_ota_manager->rollback(target);
            printf("[OTA] Rollback: %d - %s\n", res.status, res.message.c_str());

            if (res.needs_restart) {
                kill(getpid(), SIGTERM);
            }
        }
    }
}

/* ══════════════════════════════════════════════════════════
 * gRPC Service 实现 (仅在有 proto stub 时编译)
 * ══════════════════════════════════════════════════════════ */
#ifdef PROTO_GENERATED

using grpc::ServerContext;
using grpc::Status;

/* ── PushModel ─────────────────────────────────────────── */
Status GrpcServer::EdgeServiceImpl::PushModel(
    ServerContext *context,
    const edge_ai::ModelRequest *request,
    edge_ai::ModelResponse *response)
{
    printf("[gRPC] PushModel: name=%s, version=%s, size=%zu bytes\n",
           request->model_name().c_str(),
           request->model_version().c_str(),
           request->model_data().size());

    std::string previous_version;
    int ret = _owner->receive_model(
        request->model_data(),
        request->sha256_checksum(),
        request->model_name(),
        request->model_version(),
        request->auto_rollback(),
        previous_version);

    response->set_status(ret);
    response->set_message(ret == 0 ? "Model installed successfully" : "Model install failed");
    response->set_model_version(request->model_version());
    response->set_previous_version(previous_version);

    return Status::OK;
}

/* ── SwitchScene ───────────────────────────────────────── */
Status GrpcServer::EdgeServiceImpl::SwitchScene(
    ServerContext *context,
    const edge_ai::SceneRequest *request,
    edge_ai::SceneResponse *response)
{
    printf("[gRPC] SwitchScene: scene=%s\n", request->scene_name().c_str());

    int ret = _owner->do_switch_scene(request->scene_name());

    response->set_status(ret);
    response->set_message(ret == 0 ? "Scene switched" : "Scene switch failed");
    response->set_active_scene(request->scene_name());

    return Status::OK;
}

/* ── GetStatus ─────────────────────────────────────────── */
Status GrpcServer::EdgeServiceImpl::GetStatus(
    ServerContext *context,
    const edge_ai::StatusRequest *request,
    edge_ai::StatusResponse *response)
{
    const PipelineConfig *cfg = _owner->_config;

    response->set_status(0);
    response->set_device_id(cfg ? cfg->device_id : "");
    response->set_scene(cfg ? cfg->active_scene : "");
    response->set_model_version(cfg ? cfg->inference.model_path : "");

    /* ── 读取真实硬件指标 ── */

    /* NPU/CPU 温度: 遍历所有 thermal zone 取最大值 */
    float max_temp = -1.0f;
    for (int zone = 0; zone < 5; zone++) {
        char path[64];
        snprintf(path, sizeof(path),
                 "/sys/class/thermal/thermal_zone%d/temp", zone);
        FILE *f = fopen(path, "r");
        if (!f) continue;
        int millideg;
        if (fscanf(f, "%d", &millideg) == 1) {
            float t = millideg / 1000.0f;
            if (t > max_temp) max_temp = t;
        }
        fclose(f);
    }
    response->set_cpu_temp(max_temp > 0 ? max_temp : 0.0f);

    /* 内存使用: /proc/meminfo */
    long mem_total = 0, mem_available = 0;
    {
        FILE *f = fopen("/proc/meminfo", "r");
        if (f) {
            char line[128];
            while (fgets(line, sizeof(line), f)) {
                if (strncmp(line, "MemTotal:", 9) == 0)
                    sscanf(line + 9, "%ld", &mem_total);
                else if (strncmp(line, "MemAvailable:", 13) == 0)
                    sscanf(line + 13, "%ld", &mem_available);
            }
            fclose(f);
        }
    }
    if (mem_total > 0) {
        response->set_memory_bytes(
            (mem_total - mem_available) * 1024L);
    }

    /* 磁盘空间: statvfs */
    {
        struct statvfs vfs;
        if (statvfs("/data", &vfs) == 0 || statvfs("/", &vfs) == 0) {
            /* 记录到日志, 可后续扩展到 response 字段 */
            long long free_mb = (long long)vfs.f_bfree * vfs.f_frsize / (1024 * 1024);
            if (free_mb < 100) {
                fprintf(stderr, "[gRPC] WARNING: disk free only %lldMB\n", free_mb);
            }
        }
    }

    /* 运行时长 */
    response->set_uptime_sec(
        (long)(time(nullptr) - _owner->_start_time));

    /* 应用版本 */
    response->set_app_version("1.3.0");

    return Status::OK;
}

/* ── UpdateConfig ──────────────────────────────────────── */
Status GrpcServer::EdgeServiceImpl::UpdateConfig(
    ServerContext *context,
    const edge_ai::ConfigRequest *request,
    edge_ai::ConfigResponse *response)
{
    printf("[gRPC] UpdateConfig: device=%s, params=%d\n",
           request->device_id().c_str(),
           request->params_size());

    if (_owner->_ota_callback) {
        std::string payload = "{\"cmd\":\"update_config\"";
        for (const auto &kv : request->params()) {
            payload += ",\"" + kv.first + "\":\"" + kv.second + "\"";
        }
        payload += "}";
        _owner->_ota_callback("update_config", payload);
    }

    response->set_status(0);
    response->set_message("Config update accepted");

    return Status::OK;
}

/* ── Restart ───────────────────────────────────────────── */
Status GrpcServer::EdgeServiceImpl::Restart(
    ServerContext *context,
    const edge_ai::RestartRequest *request,
    edge_ai::RestartResponse *response)
{
    printf("[gRPC] Restart requested for device: %s\n",
           request->device_id().c_str());

    response->set_status(0);
    response->set_message("Restarting service");

    /* 延迟发送 SIGTERM, 给 gRPC 响应时间发回 */
    std::thread([](){
        usleep(500000);  /* 500ms 延迟 */
        kill(getpid(), SIGTERM);
    }).detach();

    return Status::OK;
}

/* ── GetVersionInfo ────────────────────────────────────── */
Status GrpcServer::EdgeServiceImpl::GetVersionInfo(
    ServerContext *context,
    const edge_ai::VersionInfoRequest *request,
    edge_ai::VersionInfoResponse *response)
{
    printf("[gRPC] GetVersionInfo: device=%s\n",
           request->device_id().c_str());

    if (g_ota_manager) {
        response->set_status(0);
        response->set_device_id(_owner->_config ? _owner->_config->device_id : "");
        response->set_rollback_available(true);
    } else {
        const PipelineConfig *cfg = _owner->_config;
        response->set_status(0);
        response->set_device_id(cfg ? cfg->device_id : "");
        response->set_app_version("1.0.0");
        response->set_model_version(cfg ? cfg->inference.model_path : "");
        response->set_scene(cfg ? cfg->active_scene : "");
        response->set_rollback_available(false);
    }

    return Status::OK;
}

/* ── PushAppUpdate ─────────────────────────────────────── */
Status GrpcServer::EdgeServiceImpl::PushAppUpdate(
    ServerContext *context,
    const edge_ai::AppUpdateRequest *request,
    edge_ai::AppUpdateResponse *response)
{
    printf("[gRPC] PushAppUpdate: version=%s, size=%zu bytes\n",
           request->app_version().c_str(),
           request->app_data().size());

    int ret = _owner->receive_app_update(
        request->app_data(),
        request->sha256_checksum(),
        request->app_version(),
        request->auto_rollback());

    response->set_status(ret);
    if (ret == 0) {
        response->set_message("App update installed, restart required");
        response->set_needs_restart(true);
    } else {
        response->set_message("App update failed");
        response->set_needs_restart(false);
    }
    response->set_app_version(request->app_version());

    return Status::OK;
}

/* ── Rollback ──────────────────────────────────────────── */
Status GrpcServer::EdgeServiceImpl::Rollback(
    ServerContext *context,
    const edge_ai::RollbackRequest *request,
    edge_ai::RollbackResponse *response)
{
    printf("[gRPC] Rollback: target=%s\n", request->target_type().c_str());

    std::string rolled_back_version;
    bool needs_restart = false;
    int ret = _owner->do_rollback(request->target_type(),
                                   rolled_back_version,
                                   needs_restart);

    response->set_status(ret);
    response->set_message(ret == 0 ? "Rollback successful" : "Rollback failed");
    response->set_rolled_back_version(rolled_back_version);
    response->set_needs_restart(needs_restart);

    if (needs_restart) {
        std::thread([](){
            usleep(500000);
            kill(getpid(), SIGTERM);
        }).detach();
    }

    return Status::OK;
}

#endif /* PROTO_GENERATED */

/* ══════════════════════════════════════════════════════════
 * GrpcServer 构造 / 启动 / 停止
 * ══════════════════════════════════════════════════════════ */

GrpcServer::GrpcServer()
    : _running(false), _engine(nullptr), _config(nullptr), _start_time(time(nullptr))
{
}

GrpcServer::~GrpcServer()
{
    stop();
}

bool GrpcServer::start(const std::string &listen_address,
                       const std::string &unix_socket,
                       Rknn1Engine *engine,
                       const PipelineConfig *config)
{
    _listen_address = listen_address;
    _unix_socket = unix_socket;
    _engine = engine;
    _config = config;

#ifdef PROTO_GENERATED
    /* 创建 Service 实现 */
    _service_impl = std::make_unique<EdgeServiceImpl>(this);

    /* 构建 gRPC 服务器 */
    grpc::ServerBuilder builder;

    /* TCP 监听 */
    builder.AddListeningPort(listen_address,
                              grpc::InsecureServerCredentials());

    /* 注册服务 */
    builder.RegisterService(_service_impl.get());

    /* 构建并启动 */
    _server = builder.BuildAndStart();
    if (!_server) {
        fprintf(stderr, "[gRPC] Failed to start server on %s\n",
                listen_address.c_str());
        return false;
    }

    _running = true;
    printf("[gRPC] Server started on %s\n", listen_address.c_str());

    /* 在独立线程中等待服务器 */
    std::thread([this](){
        _server->Wait();
    }).detach();
#else
    /* 无 gRPC stub, 框架模式 */
    _running = true;
    printf("[gRPC] Server started (framework mode, no proto stubs)\n");
#endif

    return true;
}

void GrpcServer::stop()
{
    if (!_running) return;
    _running = false;

#ifdef PROTO_GENERATED
    if (_server) {
        _server->Shutdown();
        _server.reset();
    }
#endif

    printf("[gRPC] Server stopped\n");
}

void GrpcServer::wait()
{
#ifdef PROTO_GENERATED
    if (_server) {
        _server->Wait();
    } else {
        while (_running) {
            sleep(1);
        }
    }
#else
    while (_running) {
        sleep(1);
    }
#endif
}

/* ── 设置全局 OTA Manager ─────────────────────────────── */
void grpc_set_ota_manager(OtaManager *manager)
{
    g_ota_manager = manager;
}
