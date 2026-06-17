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
 *
 * 监听:
 *   - TCP: 0.0.0.0:50051 (网络访问)
 *   - UNIX Socket: /tmp/edge-ai-grpc.sock (本地进程通信)
 *
 * 安全:
 *   - 生产环境应启用 mTLS 双向认证
 *   - 模型文件 SHA256 校验
 *
 * 依赖:
 *   - gRPC C++ (libgrpc++ + libprotobuf)
 *   - proto/edge_service.proto
 */

#include "grpc_server.h"

#include <cstdio>
#include <fstream>
#include <sstream>
#include <thread>
#include <sys/stat.h>
#include <unistd.h>

/* ── gRPC 服务实现 (简化, 完整实现需 proto 生成代码) ────── */

/*
 * 注: 完整的 gRPC 实现需要:
 *   1. 定义 edge_service.proto
 *   2. protoc 生成 C++ stub (edge_service.grpc.pb.h)
 *   3. 继承生成的 Service 基类, 实现各 RPC 方法
 *
 * 这里提供框架代码, 展示 gRPC 服务的结构和流程。
 * 实际编译时替换为 proto 生成的代码。
 */

/* ── 模型文件接收 ──────────────────────────────────────── */
/*
 * receive_model — 接收 PC 端推送的模型文件
 *
 * 流程:
 *   1. 接收模型字节流 + SHA256 校验和
 *   2. 写入临时文件
 *   3. 校验 SHA256
 *   4. 原子替换 (rename) 到模型目录
 *   5. 通知推理引擎热加载
 */
static int receive_model(const std::string &model_bytes,
                         const std::string &expected_sha256,
                         const std::string &model_dir,
                         Rknn1Engine *engine)
{
    /* 写入临时文件 */
    std::string tmp_path = model_dir + "/.tmp_model.rknn";
    std::ofstream tmp_file(tmp_path, std::ios::binary);
    if (!tmp_file) {
        fprintf(stderr, "[gRPC] Failed to write temp model file\n");
        return -1;
    }
    tmp_file.write(model_bytes.data(), model_bytes.size());
    tmp_file.close();

    /* SHA256 校验 (简化, 生产环境用 OpenSSL/libgcrypt) */
    /* TODO: 实现 SHA256 校验 */

    /* 原子替换 */
    std::string final_path = model_dir + "/current.rknn";
    if (rename(tmp_path.c_str(), final_path.c_str()) != 0) {
        fprintf(stderr, "[gRPC] Failed to rename model file\n");
        return -1;
    }

    printf("[gRPC] Model saved to %s\n", final_path.c_str());

    /* 热加载 */
    if (engine) {
        int ret = engine->hot_reload_model(final_path.c_str());
        if (ret != 0) {
            fprintf(stderr, "[gRPC] Hot-reload failed\n");
            return -1;
        }
    }

    return 0;
}

/* ── 场景切换 ──────────────────────────────────────────── */
/*
 * switch_scene — 切换推理场景
 *
 * 场景配置预定义在 pipeline.yaml 的 scenes 列表中。
 * 切换时加载对应场景的模型和参数。
 */
static int switch_scene(const std::string &scene_name,
                        const PipelineConfig &cfg,
                        Rknn1Engine *engine)
{
    printf("[gRPC] Switching to scene: %s\n", scene_name.c_str());

    /* 查找场景配置 */
    const SceneConfig *target = nullptr;
    for (const auto &scene : cfg.scenes) {
        if (scene.name == scene_name) {
            target = &scene;
            break;
        }
    }

    if (!target) {
        fprintf(stderr, "[gRPC] Scene '%s' not found\n",
                scene_name.c_str());
        return -1;
    }

    /* 热加载场景对应的模型 */
    if (engine) {
        int ret = engine->hot_reload_model(target->model_path.c_str());
        if (ret != 0) {
            fprintf(stderr, "[gRPC] Failed to load scene model\n");
            return -1;
        }
    }

    printf("[gRPC] Scene switched to '%s'\n", scene_name.c_str());
    return 0;
}

/* ── 设备状态查询 ──────────────────────────────────────── */
/*
 * get_device_status — 查询设备运行状态
 *
 * 返回:
 *   - device_id, scene, model_version
 *   - fps, npu_usage, cpu_temp, memory
 *   - uptime, frame_count
 *   - mqtt_connected, grpc_connected
 */
static std::string get_device_status(const PipelineConfig &cfg,
                                     int frame_count,
                                     float avg_inference_ms)
{
    std::ostringstream status;
    status << "{";
    status << "\"device_id\":\"" << cfg.device_id << "\",";
    status << "\"scene\":\"" << cfg.active_scene << "\",";
    status << "\"model\":\"" << cfg.inference.model_path << "\",";
    status << "\"status\":\"running\",";
    status << "\"frame_count\":" << frame_count << ",";
    status << "\"avg_inference_ms\":" << avg_inference_ms;
    status << "}";
    return status.str();
}

/* ── gRPC 服务器 ────────────────────────────────────────── */

GrpcServer::GrpcServer()
{
    _running = false;
    _engine = nullptr;
    _config = nullptr;
}

GrpcServer::~GrpcServer()
{
    stop();
}

/*
 * start — 启动 gRPC 服务器
 *
 * 注: 完整实现使用 grpc::ServerBuilder:
 *
 *   grpc::ServerBuilder builder;
 *   builder.AddListeningPort(address, grpc::InsecureServerCredentials());
 *   builder.RegisterService(&service);
 *   _server = builder.BuildAndStart();
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

    printf("[gRPC] Starting server on %s (unix: %s)\n",
           listen_address.c_str(), unix_socket.c_str());

    /*
     * TODO: 完整 gRPC 实现
     *
     * EdgeServiceImpl service(engine, config);
     *
     * grpc::ServerBuilder builder;
     * builder.AddListeningPort(listen_address,
     *                          grpc::InsecureServerCredentials());
     * builder.AddListeningPort("unix:" + unix_socket,
     *                          grpc::InsecureServerCredentials());
     * builder.RegisterService(&service);
     *
     * _server = builder.BuildAndStart();
     */

    _running = true;
    printf("[gRPC] Server started\n");
    return true;
}

void GrpcServer::stop()
{
    if (!_running)
        return;

    /*
     * TODO: 完整 gRPC 实现
     *
     * _server->Shutdown();
     * _server->Wait();
     */

    _running = false;
    printf("[gRPC] Server stopped\n");
}

/*
 * wait — 阻塞等待服务器停止
 */
void GrpcServer::wait()
{
    while (_running) {
        sleep(1);
    }
}
