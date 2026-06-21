# embedded-ai-vision 系统架构

## 项目概述

嵌入式 Linux 边缘 AI 智能摄像头系统，基于 **RK3399Pro** 平台，实现从内核驱动到 AI 推理应用的全栈覆盖。

## 五层架构

```
┌─────────────────────────────────────────────────────────┐
│ Layer 5: 通信层 (训练端/PC管控)                           │
│   gRPC: 模型推送/场景切换/状态查询/OTA升级/版本回滚 (8 RPC)   │
│   MQTT: 检测结果上报/心跳/远程指令/OTA状态                     │
│   Proto: Protobuf 序列化 + JSON fallback                  │
├─────────────────────────────────────────────────────────┤
│ Layer 4: 应用层 (C++ 边缘推理)                            │
│   Pipeline: 4线程流水线 (采集→推理→跟踪→输出)               │
│   Inference: RKNN1 API 封裝 (YOLOv5)                     │
│   Tracking: SORT 多目标跟踪 (卡尔曼+匈牙利)                │
│   I/O: V4L2 DMA-BUF 零拷贝采集                            │
├─────────────────────────────────────────────────────────┤
│ Layer 3: 中间件层 (GStreamer NPU 插件)                    │
│   rknninference: NPU 推理视频滤镜                          │
│   rknndraw: 检测框绘制视频滤镜                             │
├─────────────────────────────────────────────────────────┤
│ Layer 2: 内核层 (Linux 4.19 + Rockchip BSP)              │
│   Camera: IMX415 V4L2 Sub-device 驱动                     │
│   Peripheral: UART传感器字符设备 + GPIO触发驱动            │
│   DTS: 设备树 (CMA/NPU/I2C/MIPI/UART/GPIO)               │
├─────────────────────────────────────────────────────────┤
│ Layer 1: 硬件层 + 系统构建 (Buildroot)                     │
│   Buildroot: 交叉编译工具链 + rootfs + 内核 + U-Boot       │
│   Training: ONNX导出 + RKNN1 转换 + 部署脚本               │
└─────────────────────────────────────────────────────────┘
```

## 数据流

```
摄像头 IMX415 ──MIPI CSI──→ ISP ──→ /dev/video0 (V4L2)
                                        │
                              V4l2Capture (DMA-BUF mmap)
                                        │
                              Frame Queue (SPSC)
                                        │
                             NPU 推理 (rknn1_engine)
                                        │
                             YOLOv5 后处理 (decode + NMS)
                                        │
                              Detect Queue (SPSC)
                                        │
                             SORT 跟踪 (卡尔曼 + 匈牙利)
                                        │
                              Track Queue (SPSC)
                                        │
                        ┌───────────────┼───────────────┐
                        ↓               ↓               ↓
                      MQTT            RTSP          Display
```

## 线程模型 (RK3399Pro 6核分配)

| 核心 | CPU | 用途 | 说明 |
|------|-----|------|------|
| CPU4 | A72 | NPU 推理 | YOLOv5 前向推理, 最高频率 |
| CPU5 | A72 | SORT 跟踪 | 卡尔曼预测 + 匈牙利匹配 |
| CPU0 | A53 | 结果输出 | MQTT上报 + 视频编码 |
| CPU1 | A53 | 视频采集 | V4L2 DMA-BUF 零拷贝 |

## 关键技术

### 零拷贝路径
```
V4L2 MMAP → DMA-BUF fd → NPU rknn_inputs_set (直接传指针)
                                          ↓
                             无需 CPU memcpy (节省 ~15ms/帧)
```

### 背压策略
- **采集→推理**: 队列满时阻塞 (不丢帧)
- **推理→跟踪**: 队列满时丢弃非关键帧, 卡尔曼预测兜底
- **跟踪→输出**: 队列满时本地缓存 (MQTT QoS 1 保证)

### 多场景热切换
```
vehicle → face → body → defect
   └───────── gRPC SwitchScene ──────────┘
          ├─ 新模型通过 gRPC 推送
          ├─ SHA256 校验 → 原子 rename
          └─ rknn_init 新 context → 原子替换 _ctx
```

## 目录结构

```
embedded-ai-vision/
├── edge/              # Layer 4: C++推理应用
│   ├── config/        # pipeline.yaml + systemd service
│   └── src/
│       ├── main.cpp
│       ├── pipeline/
│       ├── inference/
│       ├── io/
│       └── comm/
├── kernel/            # Layer 2: 内核驱动 + 设备树
│   ├── config/        # 内核配置片段
│   ├── drivers/
│   │   ├── camera/    # IMX415 V4L2 驱动
│   │   └── peripheral/# UART/GPIO 字符设备驱动
│   └── dts/           # 设备树
├── gstreamer/         # Layer 3: GStreamer 插件
├── training/          # Layer 5: 训练端工具
│   └── scripts/       # 模型导出 + 部署脚本
├── buildroot-external/# Layer 1: Buildroot 构建
└── docs/              # 文档
```

## 依赖

| 库 | 版本 | 用途 |
|----|------|------|
| libmosquitto | ≥2.0 | MQTT 客户端 |
| librknn_api | RKNN-Toolkit1 | NPU 推理 |
| OpenCV | ≥3.4 | 图像预处理 |
| yaml-cpp | ≥0.6 | YAML 配置解析 |
| libsystemd | ≥237 | systemd notify/watchdog |
| gRPC/Protobuf | ≥1.16 | 远程管控 (8 RPC: 推理管控 + OTA) |
