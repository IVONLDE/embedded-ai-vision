/* SPDX-License-Identifier: MIT */
/*
 * gRPC Server — Header
 */

#ifndef GRPC_SERVER_H
#define GRPC_SERVER_H

#include <string>
#include "../inference/rknn1_engine.h"
#include "../pipeline/pipeline_config.h"

/*
 * GrpcServer — gRPC 模型更新与远程管控服务
 *
 * 服务定义 (proto/edge_service.proto):
 *   service EdgeService {
 *     rpc PushModel(ModelRequest) returns (ModelResponse);
 *     rpc SwitchScene(SceneRequest) returns (SceneResponse);
 *     rpc GetStatus(StatusRequest) returns (StatusResponse);
 *     rpc UpdateConfig(ConfigRequest) returns (ConfigResponse);
 *     rpc Restart(RestartRequest) returns (RestartResponse);
 *   }
 */
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

private:
    bool _running;
    std::string _listen_address;
    std::string _unix_socket;

    Rknn1Engine *_engine;
    const PipelineConfig *_config;

    /* gRPC server handle (完整实现时使用) */
    /* std::unique_ptr<grpc::Server> _server; */
};

#endif /* GRPC_SERVER_H */
