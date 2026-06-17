# 通信协议文档

## gRPC 服务定义

```protobuf
// proto/edge_service.proto
service EdgeService {
  rpc PushModel(ModelRequest) returns (ModelResponse);
  rpc SwitchScene(SceneRequest) returns (SceneResponse);
  rpc GetStatus(StatusRequest) returns (StatusResponse);
  rpc UpdateConfig(ConfigRequest) returns (ConfigResponse);
  rpc Restart(RestartRequest) returns (RestartResponse);
}

// 请求: 推送新模型
message ModelRequest {
  string device_id = 1;
  bytes model_data = 2;
  string sha256_checksum = 3;
  string model_name = 4;
}

message ModelResponse {
  int32 status = 1;          // 0=成功, -1=失败
  string message = 2;
  string model_version = 3;
}

// 请求: 切换推理场景
message SceneRequest {
  string device_id = 1;
  string scene_name = 2;     // face / body / vehicle / defect
}

message SceneResponse {
  int32 status = 1;
  string message = 2;
  string active_scene = 3;
}

// 请求: 查询设备状态
message StatusRequest {
  string device_id = 1;
}

message StatusResponse {
  int32 status = 1;
  string device_id = 2;
  string scene = 3;
  string model_version = 4;
  float fps = 5;
  float npu_usage = 6;
  float cpu_temp = 7;
  int64 memory_bytes = 8;
  int64 uptime_sec = 9;
  int32 frame_count = 10;
  float avg_inference_ms = 11;
}

// 请求: 更新运行时配置
message ConfigRequest {
  string device_id = 1;
  map<string, string> params = 2;
}

message ConfigResponse {
  int32 status = 1;
  string message = 2;
}

// 请求: 重启服务
message RestartRequest {
  string device_id = 1;
}

message RestartResponse {
  int32 status = 1;
  string message = 2;
}
```

## MQTT 协议

### Topic 设计

| Topic | QoS | 方向 | 说明 |
|-------|------|------|------|
| `edge/{device_id}/detections` | 1 | 设备→PC | 检测结果 (JSON) |
| `edge/{device_id}/health` | 0 | 设备→PC | 心跳/设备状态 |
| `edge/{device_id}/command` | 1 | PC→设备 | 远程指令 |

### 检测结果格式

```json
{
  "device_id": "rk3399pro-edge-001",
  "frame_index": 1234,
  "timestamp_us": 1700000000123456,
  "detections": [
    {
      "x1": 100, "y1": 80, "x2": 300, "y2": 250,
      "conf": 0.92,
      "class_id": 2,
      "track_id": 3
    }
  ]
}
```

### 心跳格式

```json
{
  "device_id": "rk3399pro-edge-001",
  "status": "online",
  "frame_index": 1200,
  "timestamp": 1700000000
}
```

### 指令格式

```json
{
  "cmd": "switch_scene",
  "scene_name": "vehicle"
}
```

```json
{
  "cmd": "reload_model",
  "model_path": "/opt/edge-ai/models/new_model.rknn"
}
```

```json
{
  "cmd": "restart"
}
```

## 端口分配

| 服务 | 端口 | 协议 |
|------|------|------|
| gRPC | 50051 | TCP |
| gRPC Unix Socket | /tmp/edge-ai-grpc.sock | UDS |
| MQTT | 1883 | TCP |
| RTSP (可选) | 8554 | TCP |
| Prometheus (可选) | 9090 | TCP |