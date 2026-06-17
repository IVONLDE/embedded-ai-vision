# embedded-ai-vision

嵌入式 Linux 边缘 AI 智能摄像头系统 — 基于 RK3399Pro 的全栈方案。

[![GitHub stars](https://img.shields.io/github/stars/IVONLDE/embedded-ai-vision?style=flat-square)](https://github.com/IVONLDE/embedded-ai-vision)
[![License](https://img.shields.io/badge/license-MIT-blue?style=flat-square)](LICENSE)

## 项目概述

将 **YOLOv5 目标检测 + SORT 多目标跟踪** 部署到 RK3399Pro 嵌入式平台，通过**自定义 Linux 内核驱动、设备树、GStreamer 多媒体管道、systemd 服务化**实现从摄像头采集到 AI 推理到结果上报的完整链路。

PC 端通过 **ISG-mian** 进行数据集管理、模型训练、RKNN 模型导出和边缘设备运维。

## 架构 (5 层)

```
┌──────────────────────────────────────────────────────────────────┐
│ Layer 5: 训练管理端 (x86 PC)                                      │
│   ISG-mian (PySide6 + QML)                                       │
│   数据集管理 / 数据清洗 / 样本增强 / 模型训练 / 评估 / RKNN导出    │
│   边缘设备管理 (gRPC 模型推送 / MQTT 结果回收 / 场景切换)          │
├──────────────────────────────────────────────────────────────────┤
│ Layer 4: AI 推理应用 (RK3399Pro)                                  │
│   C++17 systemd Service                                           │
│   四线程流水线: V4L2采集 → NPU推理 → SORT跟踪 → MQTT上报          │
│   gRPC Server: 模型热加载 / 场景切换 / 远程管控                    │
├──────────────────────────────────────────────────────────────────┤
│ Layer 3: 多媒体中间件 (GStreamer)                                 │
│   自定义 NPU 推理插件 (rknninference)                              │
│   检测框绘制插件 (rknndraw)                                        │
│   V4L2 Source → H.264 硬件编码 (MFC) → RTSP 推流                  │
├──────────────────────────────────────────────────────────────────┤
│ Layer 2: Linux 内核与驱动 (Linux 4.19)                            │
│   设备树: CMA / NPU / I2C / MIPI CSI / UART / GPIO                │
│   自定义驱动: IMX415 V4L2 sub-device / UART传感器 / GPIO触发       │
├──────────────────────────────────────────────────────────────────┤
│ Layer 1: 系统构建 (Buildroot)                                     │
│   交叉编译工具链 / rootfs定制 / 内核裁剪 / SD卡镜像                │
│   systemd 开机自启 / cgroups 资源隔离 / 看门狗                     │
└──────────────────────────────────────────────────────────────────┘
```

## 目录结构

```
embedded-ai-vision/
├── buildroot-external/   # Layer 1: Buildroot 外部树
│   ├── configs/          #   defconfig (RK3399Pro)
│   ├── board/            #   板级支持包 (boot.cmd/genimage/overlay)
│   └── package/          #   自定义软件包 (edge-ai-app/rknn-driver)
│
├── kernel/               # Layer 2: Linux 内核与驱动
│   ├── config/           #   内核配置片段 (NPU/V4L2/MFC/PREEMPT)
│   ├── dts/rk3399pro/    #   设备树 (主设备树 + IMX415子节点)
│   └── drivers/
│       ├── camera/       #   IMX415 V4L2 sub-device 驱动 (I2C)
│       └── peripheral/   #   UART传感器 + GPIO触发 字符设备驱动
│
├── gstreamer/            # Layer 3: GStreamer 自定义插件
│   └── plugin/
│       ├── gstrknninference.c   # NPU 推理元素 (GstVideoFilter)
│       └── gstrknndraw.c        # 检测框绘制元素
│
├── edge/                 # Layer 4: C++ 边缘 AI 推理应用
│   ├── config/           #   pipeline.yaml + systemd unit
│   ├── proto/            #   gRPC + Protobuf 协议定义
│   └── src/
│       ├── main.cpp              # 主入口 (YAML + CLI)
│       ├── pipeline/             # 四线程流水线调度器
│       ├── inference/
│       │   ├── rknn1_engine.cpp  # RKNN1 API 推理引擎
│       │   ├── yolov5/           # YOLOv5 后处理 (decode + NMS)
│       │   └── deepsort/         # SORT 跟踪 (卡尔曼 + 匈牙利)
│       ├── io/                   # V4L2 DMA-BUF 采集 / 文件输入
│       └── comm/                 # MQTT 上报 / gRPC 服务
│
├── training/             # Layer 5: PC 端管理平台 (ISG-mian)
│   ├── backend/services/ #   模型导出 + 边缘设备管理
│   ├── plugins/          #   算法插件 (检测/清洗/增强/评估/时序/故障诊断)
│   ├── ui/               #   QML 界面
│   └── scripts/          #   模型导出 + 部署脚本
│
├── docs/                 # 文档
│   ├── ARCHITECTURE.md   #   系统架构
│   ├── EDGE_DEPLOY.md    #   部署指南
│   └── PROTOCOL.md       #   通信协议
│
└── scripts/              # 运维脚本
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

## 关键技术

| 技术 | 用途 | 位置 |
|------|------|------|
| **设备树** | CMA 512MB / NPU / I2C / MIPI CSI / UART / GPIO / pinctrl | `kernel/dts/` |
| **V4L2 Sub-device** | IMX415 摄像头 I2C 驱动 (regmap / controls / media pad) | `kernel/drivers/camera/` |
| **UART 字符驱动** | 传感器数据采集 (serdev / 环形缓冲 / wait_queue / sysfs) | `kernel/drivers/peripheral/` |
| **GPIO 中断驱动** | 按键/报警触发 (gpio_to_irq / tasklet底半部 / 去抖) | `kernel/drivers/peripheral/` |
| **GStreamer 插件** | NPU 推理元素 (GstVideoFilter / transform_frame_ip) | `gstreamer/plugin/` |
| **RKNN1 API** | NPU 推理 (rknn_init/run/inputs_set/outputs_get) | `edge/src/inference/` |
| **SORT 跟踪** | 卡尔曼滤波 + 匈牙利匹配 (纯CPU, 单核NPU适配) | `edge/src/inference/deepsort/` |
| **V4L2 DMA-BUF** | 摄像头→NPU 零拷贝采集 (mmap / VIDIOC_EXPBUF) | `edge/src/io/` |
| **MQTT** | 检测结果 + 心跳上报 (libmosquitto / QoS 0/1) | `edge/src/comm/` |
| **gRPC** | 模型推送 / 场景切换 / 远程管控 (Proto3) | `edge/src/comm/` + `edge/proto/` |
| **systemd** | 服务托管 (Type=notify / cgroups / 看门狗 / 安全加固) | `edge/config/` |
| **Buildroot** | 交叉编译 / rootfs 裁剪 / SD 卡镜像 | `buildroot-external/` |
| **RKNN-Toolkit1** | PyTorch → ONNX → RKNN 导出 + INT8 量化 | `training/scripts/` |
| **ISG-mian** | 数据集管理 / 清洗 / 增强 / 训练 / 评估 GUI | `training/` |

## 项目统计

```
文件总数:  300+
代码行数:  63,500+

C/C++ (内核驱动 + 推理应用):    ~8,500 行
DTS (设备树):                    ~450 行
GStreamer (C):                   ~1,100 行
Python (PC 端管理平台):         ~40,000 行
QML (GUI):                       ~3,000 行
Shell (构建/部署脚本):           ~600 行
配置 (Buildroot/systemd/YAML):  ~800 行
Proto (gRPC/Protobuf):          ~200 行
文档:                            ~300 行
```

## 快速开始

### PC 端 (训练管理)

```bash
cd training
pip install -r requirements.txt
python main.py
```

### 边缘端 (推理部署)

详见 `docs/EDGE_DEPLOY.md`

## 依赖

| 库 | 版本 | 用途 |
|----|------|------|
| librknn_api | RKNN-Toolkit1 | NPU 推理 (RK3399Pro) |
| libmosquitto | ≥2.0 | MQTT 客户端 |
| OpenCV | ≥3.4 | 图像预处理 |
| yaml-cpp | ≥0.6 | YAML 配置解析 |
| Eigen | ≥3.3 | 线性代数 (卡尔曼/匈牙利) |
| libsystemd | ≥237 | systemd notify/watchdog |
| gRPC/Protobuf | ≥1.30 | 远程管控 |
| GStreamer | ≥1.18 | 多媒体管道 |
| PySide6 | ≥6.5 | PC 端 GUI |
| PyTorch | ≥2.0 | 模型训练 |
| RKNN-Toolkit1 | ≥1.7 | 模型导出 |