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
 *
 * 注: gRPC stub 需要生成, 当前实现通过 MQTT 命令转发 + OtaManager 处理。
 */

#include "grpc_server.h"
#include "ota_manager.h"

#include <cstdio>
#include <fstream>
#include <sstream>
#include <thread>
#include <sys/stat.h>
#include <unistd.h>
#include <signal.h>

/* ── 内部 OTA Manager 引用 ─────────────────────────────── */
static OtaManager *g_ota_manager = nullptr;

void GrpcServer::set_ota_callback(OtaCallback cb)
{
    _ota_callback = cb;
}

/* ── 从 MQTT 命令转发调用 ──────────────────────────────── */
/*
 * handle_command — 处理 MQTT/JSON-RPC 指令, 转发到 OtaManager
 *
 * 指令格式 (JSON):
 *   {"cmd":"switch_scene", "scene":"vehicle"}
 *   {"cmd":"reload_model", "model_path":"/tmp/new.rknn", "version":"v2"}
 *   {"cmd":"app_update", "app_path":"/tmp/edge-ai-camera", "version":"1.1"}
 *   {"cmd":"rollback", "target":"model"}
 *   {"cmd":"restart"}
 */
void GrpcServer::handle_command(const std::string &cmd,
                                const std::string &payload)
{
    printf("[gRPC/OTA] Command: %s\n", cmd.c_str());

    /* 解析 JSON 参数 (简化, 生产环境用 cJSON/yaml-cpp) */
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
                /* 通知 systemd 重启 */
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

/* ── 场景切换 ──────────────────────────────────────────── */
int GrpcServer::do_switch_scene(const std::string &scene_name)
{
    printf("[gRPC] Switching to scene: %s\n", scene_name.c_str());

    if (!_config) {
        fprintf(stderr, "[gRPC] No config available\n");
        return -1;
    }

    /* 查找场景配置 */
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

    /* 热加载场景对应的模型 */
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

/* ── 版本信息 ──────────────────────────────────────────── */
std::string GrpcServer::get_version_info_json() const
{
    if (g_ota_manager) {
        return g_ota_manager->get_version_info();
    }

    /* fallback: 从 config 路径推断版本 */
    std::ostringstream json;
    json << "{";
    json << "\"device_id\":\"" << (_config ? _config->device_id : "") << "\",";
    json << "\"app_version\":\"1.0.0\",";
    json << "\"model_version\":\"" << (_config ? _config->inference.model_path : "") << "\",";
    json << "\"rollback_available\":false";
    json << "}";
    return json.str();
}

/* ── gRPC 服务器框架 ────────────────────────────────────── */

GrpcServer::GrpcServer()
    : _running(false), _engine(nullptr), _config(nullptr)
{
}

GrpcServer::~GrpcServer()
{
    stop();
}

/*
 * start — 启动 gRPC 服务器
 *
 * 注: 当前为框架实现, 实际 gRPC stub 需要生成。
 * 通过 MQTT 命令转发 + OtaManager 处理 OTA。
 */
bool GrpcServer::start(const std::string &listen_address,
                       const std::string &unix_socket,
                       Rknn1Engine *engine,
                       const PipelineConfig *config)
{
    _listen_address = listen_address;
    _unix_socket = unix_socket;
    _engine = engine;
    _config = config;

    printf("[gRPC] Server framework ready on %s (unix: %s)\n",
           listen_address.c_str(), unix_socket.c_str());

    /*
     * TODO: 完整 gRPC 实现
     *
     * 1. protoc --grpc_out=. --plugin=protoc-gen-grpc=grpc_cpp_plugin edge_service.proto
     * 2. 继承 EdgeService::Service, 实现各 RPC handler
     * 3. grpc::ServerBuilder builder;
     *    builder.AddListeningPort(listen_address, ...);
     *    builder.RegisterService(&service_impl);
     *    _server = builder.BuildAndStart();
     */

    _running = true;
    printf("[gRPC] Server started (framework mode)\n");
    return true;
}

void GrpcServer::stop()
{
    if (!_running) return;
    _running = false;
    printf("[gRPC] Server stopped\n");
}

void GrpcServer::wait()
{
    while (_running) {
        sleep(1);
    }
}

/* ── 设置全局 OTA Manager ─────────────────────────────── */
void grpc_set_ota_manager(OtaManager *manager)
{
    g_ota_manager = manager;
}