# 通信协议文档

PC 端与边缘设备之间通过 **gRPC** 和 **MQTT** 两种协议通信。gRPC 用于请求-响应式管控（模型推送、场景切换、状态查询等），MQTT 用于实时数据流（检测结果上报、心跳）和轻量指令下发。

## gRPC 服务定义

> 源文件: `edge/proto/edge_service.proto`

```protobuf
service EdgeService {
  // 推理管控
  rpc PushModel(ModelRequest) returns (ModelResponse);
  rpc SwitchScene(SceneRequest) returns (SceneResponse);
  rpc GetStatus(StatusRequest) returns (StatusResponse);
  rpc UpdateConfig(ConfigRequest) returns (ConfigResponse);
  rpc Restart(RestartRequest) returns (RestartResponse);

  // OTA 管理
  rpc GetVersionInfo(VersionInfoRequest) returns (VersionInfoResponse);
  rpc PushAppUpdate(AppUpdateRequest) returns (AppUpdateResponse);
  rpc Rollback(RollbackRequest) returns (RollbackResponse);
}
```

### 推理管控 RPC

#### PushModel — 推送新模型

推送模型二进制数据到边缘设备，SHA256 校验后热加载。

```protobuf
message ModelRequest {
  string device_id = 1;          // 设备ID
  bytes model_data = 2;          // 模型文件二进制数据
  string sha256_checksum = 3;    // SHA256 校验和
  string model_name = 4;         // 模型名称
  string model_version = 5;      // 模型版本号
  bool auto_rollback = 6;        // 失败时自动回滚
}

message ModelResponse {
  int32 status = 1;              // 0=成功, -1=失败
  string message = 2;
  string model_version = 3;      // 当前模型版本
  string previous_version = 4;   // 回滚前的版本 (用于回滚)
}
```

#### SwitchScene — 切换推理场景

切换到预定义场景，自动加载对应模型文件。

```protobuf
message SceneRequest {
  string device_id = 1;
  string scene_name = 2;         // face / body / vehicle / defect
}

message SceneResponse {
  int32 status = 1;
  string message = 2;
  string active_scene = 3;       // 切换后的场景
}
```

#### GetStatus — 查询设备状态

查询设备实时运行状态，包括 FPS、NPU 利用率、CPU 温度等。

```protobuf
message StatusRequest {
  string device_id = 1;
}

message StatusResponse {
  int32 status = 1;
  string device_id = 2;
  string scene = 3;              // 当前场景
  string model_version = 4;      // 当前模型版本
  float fps = 5;                // 实时帧率
  float npu_usage = 6;          // NPU 利用率 (%)
  float cpu_temp = 7;           // CPU 温度
  int64 memory_bytes = 8;       // 内存占用
  int64 uptime_sec = 9;         // 运行时长
  int32 frame_count = 10;       // 累计帧数
  float avg_inference_ms = 11;  // 平均推理耗时
  string app_version = 12;      // 应用版本号
}
```

#### UpdateConfig — 更新运行时配置

以键值对形式更新运行时参数。

```protobuf
message ConfigRequest {
  string device_id = 1;
  map<string, string> params = 2;  // 键值对参数
}

message ConfigResponse {
  int32 status = 1;
  string message = 2;
}
```

#### Restart — 重启推理服务

延迟 500ms 后发送 SIGTERM 优雅重启，给 gRPC 响应足够发回时间。

```protobuf
message RestartRequest {
  string device_id = 1;
}

message RestartResponse {
  int32 status = 1;
  string message = 2;
}
```

### OTA 管理 RPC

#### GetVersionInfo — 查询版本信息

查询设备当前应用版本、模型版本、是否可回滚。

```protobuf
message VersionInfoRequest {
  string device_id = 1;
}

message VersionInfoResponse {
  int32 status = 1;
  string device_id = 2;
  string app_version = 3;           // 应用版本
  string model_version = 4;         // 当前模型版本
  string previous_model_version = 5; // 上一模型版本 (可回滚)
  string scene = 6;                 // 当前场景
  int64 uptime_sec = 7;             // 运行时长
  bool rollback_available = 8;      // 是否可回滚
}
```

#### PushAppUpdate — 推送应用二进制更新

推送应用二进制到设备，SHA256 校验后替换并重启。

```protobuf
message AppUpdateRequest {
  string device_id = 1;
  bytes app_data = 2;               // 应用二进制数据
  string sha256_checksum = 3;       // SHA256 校验和
  string app_version = 4;           // 新版本号
  bool auto_rollback = 5;           // 失败时自动回滚
}

message AppUpdateResponse {
  int32 status = 1;                 // 0=成功, -1=失败, 2=需重启
  string message = 2;
  string app_version = 3;           // 更新后的版本
  bool needs_restart = 4;           // 是否需要重启服务
}
```

#### Rollback — 版本回滚

回滚模型或应用到上一版本。若回滚后需要重启，会延迟 500ms 发送 SIGTERM。

```protobuf
message RollbackRequest {
  string device_id = 1;
  string target_type = 2;           // "model" 或 "app"
}

message RollbackResponse {
  int32 status = 1;
  string message = 2;
  string rolled_back_version = 3;   // 回滚到的版本
  bool needs_restart = 4;           // 是否需要重启
}
```

### 条件编译

gRPC 服务端通过 CMake `PROTO_GENERATED` 宏条件编译：
- **有 gRPC 环境**：编译 proto stub + EdgeServiceImpl，启动真正的 gRPC 服务器
- **无 gRPC 环境**：自动降级为 framework mode，仅通过 MQTT 处理指令

## MQTT 协议

### Topic 设计

| Topic | QoS | 方向 | 说明 |
|-------|------|------|------|
| `edge/{device_id}/detections` | 1 | 设备→PC | 检测结果 (JSON) |
| `edge/{device_id}/health` | 0 | 设备→PC | 心跳/设备状态 |
| `edge/{device_id}/command` | 1 | PC→设备 | 远程指令 |
| `edge/{device_id}/ota_status` | 1 | 设备→PC | OTA 状态更新 |

PC 端订阅通配符 `edge/#` 接收所有设备数据。

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
      "track_id": 3,
      "class_name": "vehicle"
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
  "timestamp": 1700000000,
  "fps": 12.5,
  "npu_usage": 85.2,
  "cpu_temp": 52.3,
  "memory_bytes": 134217728,
  "model_version": "yolov5n-v1.2",
  "scene": "vehicle"
}
```

设备上线时发送 `status: "online"`，离线时通过 MQTT 遗嘱消息自动发送 `status: "offline"`。

### 指令格式

PC 端通过 MQTT `command` topic 下发指令，板子端 `mqtt_publisher` 订阅并转发到 `GrpcServer::handle_command()`。

```json
{"cmd": "switch_scene", "scene": "vehicle"}
```

```json
{"cmd": "reload_model", "model_path": "/opt/edge-ai/models/new.rknn", "version": "v2", "sha256": "abc123..."}
```

```json
{"cmd": "app_update", "app_path": "/tmp/edge-ai-camera", "version": "1.1.0", "sha256": "def456..."}
```

```json
{"cmd": "rollback", "target": "model"}
```

```json
{"cmd": "restart"}
```

## mDNS 服务发现

边缘设备通过 Avahi 广播自身信息，PC 端通过 zeroconf 扫描发现设备。

| 属性 | 值 |
|------|-----|
| 服务类型 | `_edge-ai._tcp` |
| 端口 | 50051 |
| TXT: device_id | `rk3399pro-edge-001` |
| TXT: scene | 当前场景 |
| TXT: mqtt_port | `1883` |

> 配置文件: `edge/config/avahi/edge-ai.service`

## 通信方式选择

| 场景 | 推荐方式 | 原因 |
|------|---------|------|
| 实时检测数据 | MQTT | 高频推送，发布-订阅模式 |
| 心跳/状态上报 | MQTT | 低频周期性，QoS 0 即可 |
| 模型推送 (大文件) | gRPC | 请求-响应，二进制流，带校验 |
| 场景切换 | gRPC / MQTT | 均可，gRPC 有明确响应 |
| 状态查询 | gRPC | 需要即时响应 |
| OTA 升级 | gRPC | 带版本管理和自动回滚 |
| 设备发现 | mDNS | 局域网自动发现 |

## 端口分配

| 服务 | 端口 | 协议 |
|------|------|------|
| gRPC | 50051 | TCP |
| gRPC Unix Socket | /tmp/edge-ai-grpc.sock | UDS |
| MQTT | 1883 | TCP |
| RTSP (可选) | 8554 | TCP |
| Prometheus (可选) | 9090 | TCP |
