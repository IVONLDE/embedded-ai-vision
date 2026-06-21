/* SPDX-License-Identifier: MIT */
/*
 * gRPC Server — Header
 *
 * 服务定义 (proto/edge_service.proto):
 *   service EdgeService {
 *     rpc PushModel(ModelRequest) returns (ModelResponse);
 *     rpc SwitchScene(SceneRequest) returns (SceneResponse);
 *     rpc GetStatus(StatusRequest) returns (StatusResponse);
 *     rpc UpdateConfig(ConfigRequest) returns (ConfigResponse);
 *     rpc Restart(RestartRequest) returns (RestartResponse);
 *     rpc GetVersionInfo(VersionInfoRequest) returns (VersionInfoResponse);
 *     rpc PushAppUpdate(AppUpdateRequest) returns (AppUpdateResponse);
 *     rpc Rollback(RollbackRequest) returns (RollbackResponse);
 *   }
 */

#ifndef GRPC_SERVER_H
#define GRPC_SERVER_H

#include <string>
#include <functional>
#include <atomic>
#include <memory>
#include "../inference/rknn1_engine.h"
#include "../pipeline/pipeline_config.h"

/* 条件编译: gRPC 仅在找到 protobuf/gRPC 时启用 */
#ifdef PROTO_GENERATED
#include "generated/edge_service.grpc.pb.h"
#endif

/* 前向声明 */
class OtaManager;

/* OTA 回调类型 */
using OtaCallback = std::function<void(const std::string &cmd,
                                       const std::string &payload)>;

class GrpcServer {
public:
    GrpcServer();
    ~GrpcServer();

    bool start(const std::string &listen_address,
               const std::string &unix_socket,
               Rknn1Engine *engine,
               const PipelineConfig *config);

    void stop();
    void wait();

    bool is_running() const { return _running; }

    /* 设置 OTA 指令回调 (由 pipeline 注册, 连接到实际业务逻辑) */
    void set_ota_callback(OtaCallback cb) { _ota_callback = cb; }

    /* 供 MQTT 命令处理调用: 将 MQTT 指令转发到 gRPC 同一套业务逻辑 */
    void handle_command(const std::string &cmd, const std::string &payload);

private:
    std::atomic<bool> _running;
    std::string _listen_address;
    std::string _unix_socket;

    Rknn1Engine *_engine;
    const PipelineConfig *_config;

    /* OTA 指令回调 */
    OtaCallback _ota_callback;

#ifdef PROTO_GENERATED
    /* gRPC 服务器实例 */
    std::unique_ptr<grpc::Server> _server;

    /* ── gRPC Service 实现 ──────────────────────────────── */
    class EdgeServiceImpl final : public edge_ai::EdgeService::Service {
    public:
        EdgeServiceImpl(GrpcServer *owner) : _owner(owner) {}

        /* 8 个 RPC handler */
        grpc::Status PushModel(grpc::ServerContext *context,
                               const edge_ai::ModelRequest *request,
                               edge_ai::ModelResponse *response) override;

        grpc::Status SwitchScene(grpc::ServerContext *context,
                                 const edge_ai::SceneRequest *request,
                                 edge_ai::SceneResponse *response) override;

        grpc::Status GetStatus(grpc::ServerContext *context,
                               const edge_ai::StatusRequest *request,
                               edge_ai::StatusResponse *response) override;

        grpc::Status UpdateConfig(grpc::ServerContext *context,
                                  const edge_ai::ConfigRequest *request,
                                  edge_ai::ConfigResponse *response) override;

        grpc::Status Restart(grpc::ServerContext *context,
                             const edge_ai::RestartRequest *request,
                             edge_ai::RestartResponse *response) override;

        grpc::Status GetVersionInfo(grpc::ServerContext *context,
                                    const edge_ai::VersionInfoRequest *request,
                                    edge_ai::VersionInfoResponse *response) override;

        grpc::Status PushAppUpdate(grpc::ServerContext *context,
                                   const edge_ai::AppUpdateRequest *request,
                                   edge_ai::AppUpdateResponse *response) override;

        grpc::Status Rollback(grpc::ServerContext *context,
                              const edge_ai::RollbackRequest *request,
                              edge_ai::RollbackResponse *response) override;

    private:
        GrpcServer *_owner;
    };

    /* Service 实例 */
    std::unique_ptr<EdgeServiceImpl> _service_impl;
#endif

    /* ── 内部 OTA 业务逻辑 ──────────────────────────────── */

    /* 模型文件接收 + SHA256 校验 + 原子替换 + 热加载 */
    int receive_model(const std::string &model_bytes,
                      const std::string &expected_sha256,
                      const std::string &model_name,
                      const std::string &model_version,
                      bool auto_rollback,
                      std::string &previous_version);

    /* 场景切换 */
    int do_switch_scene(const std::string &scene_name);

    /* 获取设备状态 JSON */
    std::string get_device_status_json() const;

    /* 版本信息查询 */
    std::string get_version_info_json() const;

    /* 应用更新 */
    int receive_app_update(const std::string &app_data,
                           const std::string &expected_sha256,
                           const std::string &app_version,
                           bool auto_rollback);

    /* 回滚 */
    int do_rollback(const std::string &target_type,
                    std::string &rolled_back_version,
                    bool &needs_restart);

    /* SHA256 计算 (使用 OpenSSL 或简易实现) */
    static std::string compute_sha256(const std::string &data);
    static std::string compute_file_sha256(const std::string &path);

    /* 备份当前模型 */
    static bool backup_file(const std::string &src, const std::string &dst);
};

/* 全局 OTA Manager 设置 (由 main.cpp 调用) */
void grpc_set_ota_manager(OtaManager *manager);

#endif /* GRPC_SERVER_H */
