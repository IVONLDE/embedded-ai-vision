# API 参考文档

关键模块的 API 使用示例和接口说明。

## 1. RKNN1 API — NPU 推理

### 典型推理流程

```cpp
#include "rknn_api.h"

// 1. 加载模型
rknn_context ctx;
int ret = rknn_init(&ctx, model_data, model_size, 0, nullptr);
if (ret < 0) {
    fprintf(stderr, "rknn_init 失败: %d\n", ret);
    return -1;
}

// 2. 查询输入/输出属性
rknn_input_output_num io_num;
rknn_query(ctx, RKNN_QUERY_IN_OUT_NUM, &io_num, sizeof(io_num));

rknn_tensor_attr input_attrs[1];
rknn_query(ctx, RKNN_QUERY_INPUT_ATTR, input_attrs, sizeof(input_attrs));

rknn_tensor_attr output_attrs[8];
rknn_query(ctx, RKNN_QUERY_OUTPUT_ATTR, output_attrs,
           sizeof(rknn_tensor_attr) * io_num.n_output);

// 3. 推理循环
while (running) {
    // 3.1 设置输入
    rknn_input input;
    memset(&input, 0, sizeof(input));
    input.index = 0;
    input.buf = frame_data;           // uint8 图像数据
    input.size = width * height * 3;  // NHWC 格式
    input.pass_through = 0;
    input.type = RKNN_TENSOR_UINT8;
    input.fmt = RKNN_TENSOR_NHWC;
    rknn_inputs_set(ctx, 1, &input);

    // 3.2 执行推理
    rknn_run(ctx, nullptr);

    // 3.3 获取输出
    rknn_output outputs[8];
    memset(outputs, 0, sizeof(outputs));
    for (uint32_t i = 0; i < io_num.n_output; i++) {
        outputs[i].want_float = 1;     // 要求 float32 输出
        outputs[i].is_prealloc = 0;    // RKNN 内部分配
    }
    rknn_outputs_get(ctx, io_num.n_output, outputs, nullptr);

    // 3.4 处理输出
    for (uint32_t i = 0; i < io_num.n_output; i++) {
        float *data = (float *)outputs[i].buf;
        // YOLOv5: 3 个输出层，分别对应 80×80, 40×40, 20×20 网格
        // ... 后处理 (decode + NMS) ...
    }

    // 3.5 释放输出（必须！）
    rknn_outputs_release(ctx, io_num.n_output, outputs);
}

// 4. 销毁上下文
rknn_destroy(ctx);
```

### 错误处理

```cpp
int ret = rknn_init(&ctx, model_data, model_size, 0, nullptr);
if (ret < 0) {
    switch (ret) {
    case -1:  fprintf(stderr, "模型数据无效\n"); break;
    case -2:  fprintf(stderr, "NPU 驱动未加载\n"); break;
    case -3:  fprintf(stderr, "CMA 内存不足\n"); break;
    default:  fprintf(stderr, "未知错误: %d\n", ret); break;
    }
    return -1;
}
```

### 性能统计

```cpp
// 启用性能统计
rknn_init(&ctx, model_data, model_size,
          RKNN_FLAG_COLLECT_PERF_MASK, nullptr);

// 推理后查询耗时
rknn_perf_run perf;
rknn_query(ctx, RKNN_QUERY_PERF_RUN, &perf, sizeof(perf));
printf("推理耗时: %llu ns\n", perf.run_end - perf.run_start);
```

---

## 2. gRPC 服务 — 远程管控

### Python 客户端示例

```python
import grpc
from edge_service_pb2 import (
    ModelRequest, SceneRequest, StatusRequest,
    ConfigRequest, RestartRequest
)
from edge_service_pb2_grpc import EdgeServiceStub

# 连接
channel = grpc.insecure_channel('192.168.1.50:50051')
stub = EdgeServiceStub(channel)

# 推送模型
with open('yolov5_vehicle.rknn', 'rb') as f:
    model_data = f.read()

import hashlib
sha256 = hashlib.sha256(model_data).hexdigest()

response = stub.PushModel(ModelRequest(
    device_id='rk3399pro-edge-001',
    model_data=model_data,
    sha256_checksum=sha256,
    model_name='yolov5_vehicle',
))
print(f"推送结果: status={response.status}, message={response.message}")

# 切换场景
response = stub.SwitchScene(SceneRequest(
    device_id='rk3399pro-edge-001',
    scene_name='vehicle',
))
print(f"场景切换: {response.active_scene}")

# 查询状态
response = stub.GetStatus(StatusRequest(
    device_id='rk3399pro-edge-001',
))
print(f"FPS: {response.fps}, NPU: {response.npu_usage}%, "
      f"温度: {response.cpu_temp}°C, 推理: {response.avg_inference_ms}ms")

# 更新配置
response = stub.UpdateConfig(ConfigRequest(
    device_id='rk3399pro-edge-001',
    params={'conf_threshold': '0.5', 'nms_threshold': '0.45'},
))

# 重启服务
response = stub.Restart(RestartRequest(
    device_id='rk3399pro-edge-001',
))
```

### 命令行调用 (grpcurl)

```bash
# 查询状态
grpcurl -plaintext 192.168.1.50:50051 EdgeService/GetStatus \
    -d '{"device_id": "rk3399pro-edge-001"}'

# 切换场景
grpcurl -plaintext 192.168.1.50:50051 EdgeService/SwitchScene \
    -d '{"device_id": "rk3399pro-edge-001", "scene_name": "vehicle"}'

# 通过 Unix Socket
grpcurl -plaintext -unix /tmp/edge-ai-grpc.sock EdgeService/GetStatus \
    -d '{"device_id": "rk3399pro-edge-001"}'
```

---

## 3. MQTT 协议 — 实时数据

### 订阅检测结果

```bash
mosquitto_sub -h 192.168.1.50 -t 'edge/rk3399pro-edge-001/detections' -v
```

输出示例：
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

### 订阅心跳

```bash
mosquitto_sub -h 192.168.1.50 -t 'edge/rk3399pro-edge-001/health' -v
```

输出示例：
```json
{
  "device_id": "rk3399pro-edge-001",
  "status": "online",
  "frame_index": 1200,
  "timestamp": 1700000000
}
```

### 发送远程指令

```bash
# 切换场景
mosquitto_pub -h 192.168.1.50 -t 'edge/rk3399pro-edge-001/command' \
    -m '{"cmd":"switch_scene","scene_name":"vehicle"}'

# 重新加载模型
mosquitto_pub -h 192.168.1.50 -t 'edge/rk3399pro-edge-001/command' \
    -m '{"cmd":"reload_model","model_path":"/opt/edge-ai/models/new_model.rknn"}'

# 重启服务
mosquitto_pub -h 192.168.1.50 -t 'edge/rk3399pro-edge-001/command' \
    -m '{"cmd":"restart"}'
```

### Python MQTT 客户端

```python
import paho.mqtt.client as mqtt
import json

def on_connect(client, userdata, flags, rc):
    print(f"连接成功, rc={rc}")
    client.subscribe("edge/rk3399pro-edge-001/detections")
    client.subscribe("edge/rk3399pro-edge-001/health")

def on_message(client, userdata, msg):
    data = json.loads(msg.payload.decode())
    if msg.topic.endswith("/detections"):
        print(f"检测到 {len(data['detections'])} 个目标")
    elif msg.topic.endswith("/health"):
        print(f"设备在线, 帧号: {data['frame_index']}")

client = mqtt.Client(client_id="pc-monitor")
client.on_connect = on_connect
client.on_message = on_message
client.connect("192.168.1.50", 1883, 60)
client.loop_forever()
```

---

## 4. Edge 端 C++ 模块接口

### Pipeline 配置

```cpp
#include "pipeline_config.h"

// 从 YAML 加载配置
PipelineConfig cfg = PipelineConfig::load_from_yaml("/opt/edge-ai/config/pipeline.yaml");

// 访问配置
printf("输入设备: %s\n", cfg.input.v4l2_device.c_str());
printf("模型路径: %s\n", cfg.inference.model_path.c_str());
printf("置信度阈值: %.2f\n", cfg.inference.conf_threshold);
printf("跟踪启用: %s\n", cfg.tracking.enabled ? "是" : "否");
printf("MQTT Broker: %s:%d\n", cfg.mqtt.broker_host.c_str(), cfg.mqtt.broker_port);
```

### 启动流水线

```cpp
#include "pipeline.h"

// 加载配置
PipelineConfig cfg = PipelineConfig::load_from_yaml(config_path);

// 命令行覆盖
cfg.active_scene = "vehicle";
cfg.inference.model_path = "/opt/edge-ai/models/yolov5_vehicle.rknn";

// 启动（阻塞直到收到 SIGTERM）
int ret = pipeline_run(cfg);
```

### RKNN 推理引擎

```cpp
#include "rknn1_engine.h"

// 创建引擎
Rknn1Engine engine("/opt/edge-ai/models/yolov5.rknn", 4);  // CPU4 (A72)

// 执行推理
int cost_us = engine.inference(frame_data);
if (cost_us < 0) {
    fprintf(stderr, "推理失败\n");
}

// 读取输出
for (int i = 0; i < engine._n_output; i++) {
    float *data = engine._output_copies[i].data();
    // ... 后处理 ...
}

// 热加载新模型
int ret = engine.hot_reload_model("/opt/edge-ai/models/new_model.rknn");
if (ret == 0) {
    printf("模型热加载成功\n");
} else {
    printf("热加载失败，继续使用旧模型\n");
}
```

### V4L2 采集

```cpp
#include "v4l2_capture.h"

V4l2Capture cap;
if (!cap.open("/dev/video0", 1920, 1080, 30)) {
    fprintf(stderr, "摄像头打开失败\n");
    return -1;
}

cap.start_stream();

while (running) {
    unsigned char *data;
    int width, height;
    int64_t timestamp_us;

    if (cap.read_frame(&data, &width, &height, &timestamp_us)) {
        // 处理帧数据...
        cap.release_frame();  // 必须归还缓冲区
    }
}

cap.stop_stream();
cap.close();
```

### MQTT 上报

```cpp
#include "mqtt_publisher.h"

MqttPublisher mqtt;
mqtt.connect("192.168.1.100", 1883, "rk3399pro-edge-001", 60);

// 上报检测结果
std::vector<DetectBox> boxes = {...};
mqtt.publish_detections("edge/rk3399pro-001/detections", boxes, frame_idx, timestamp_us);

// 上报心跳
mqtt.publish_health("edge/rk3399pro-001/health", frame_idx);

// 设置指令回调
mqtt.set_command_callback([](const char *topic, const char *payload, int len) {
    printf("收到指令: %s\n", payload);
    // 解析 JSON 指令并执行...
});
```

### YOLOv5 后处理

```cpp
#include "detect.h"

// NPU 输出的 3 个特征层
float *output0 = engine._output_copies[0].data();
float *output1 = engine._output_copies[1].data();
float *output2 = engine._output_copies[2].data();

// 后处理：decode + NMS
std::vector<DetectBox> detections;
int ret = post_process_fp(output0, output1, output2,
                          0.3,   // conf_threshold
                          0.45,  // nms_threshold
                          &detections);
```

### SORT 跟踪

```cpp
#include "tracker.h"

// 创建跟踪器
Tracker tracker(0.7f,  // max_iou_distance
                30,    // max_age
                2);    // n_init

// 每帧调用
tracker.predict();
tracker.update(detections);
std::vector<DetectBox> active_tracks = tracker.get_active_tracks();

// 轨迹信息
for (auto &track : tracker.tracks()) {
    if (track.is_confirmed()) {
        printf("Track %d: class=%d, conf=%.2f, age=%d\n",
               track.track_id, track.cls, track.conf, track.age);
    }
}
```

---

## 5. PC 端 Python 接口

### BackendService (QML 桥接)

```python
# main.py 中的 BackendService 是 QML 的唯一入口
# 所有方法通过 @Slot() 装饰器暴露给 QML

class BackendService(QObject):
    # 信号定义
    datasetsUpdated = Signal()
    cleaningTasksUpdated = Signal()

    @Slot(result=list)
    def get_datasets(self):
        return self._bridge.list_datasets()

    @Slot(int, str, result=dict)
    def create_cleaning_task(self, dataset_id, algorithm_key):
        return self._bridge.create_cleaning_task(dataset_id, algorithm_key)
```

### 插件开发

```python
# plugins/user/my_plugin.py
PARAMETERS = [
    {"name": "threshold", "type": "float", "label": "阈值",
     "default": 0.5, "min": 0.0, "max": 1.0},
]

def run(payload, context):
    params = payload.get("parameters", {})
    threshold = float(params.get("threshold", 0.5))

    # 进度上报
    context.set_progress(50, "处理中...")

    # 取消检查
    if context.is_cancel_requested():
        return {"ok": False, "error_code": "CANCELLED", "message": "已取消"}

    # 日志
    context.log("info", f"使用阈值: {threshold}")

    # ... 执行算法 ...

    return {"ok": True, "outputs": [...]}
```

详见 [ALGORITHM_PLUGIN_SPEC.md](../training/docs/ALGORITHM_PLUGIN_SPEC.md)。

### 模型导出

```bash
# 命令行导出
python training/scripts/export_to_rknn1.py \
    --model_path model.pt \
    --model_type yolov5 \
    --output_path model.rknn \
    --do_quantization \
    --dataset calibration_images/

# 查看模型信息
python training/scripts/export_to_rknn1.py \
    --model_path model.rknn \
    --info
```

### 边缘设备部署

```bash
# 使用部署脚本
./training/scripts/deploy_to_edge.sh 192.168.1.50 model.rknn vehicle

# 手动部署
scp model.rknn root@192.168.1.50:/opt/edge-ai/models/current.rknn
ssh root@192.168.1.50 "systemctl reload edge-ai-camera"
```
