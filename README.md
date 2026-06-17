# embedded-ai-vision

嵌入式 Linux 边缘 AI 通用推理平台 — 基于 RK3399Pro 的全栈方案。

[![GitHub stars](https://img.shields.io/github/stars/IVONLDE/embedded-ai-vision?style=flat-square)](https://github.com/IVONLDE/embedded-ai-vision)
[![License](https://img.shields.io/badge/license-MIT-blue?style=flat-square)](LICENSE)

## 项目概述

**一套"PC 管控 + 边缘推理"协同工作的通用 AI 平台。** PC 端负责数据管理、模型训练、场景切换、远程管控；RK3399Pro 板子端负责实时推理、结果上报。板子端硬件和驱动不变，**换模型即可切换场景**。

当前落地场景：YOLOv5 目标检测 + SORT 多目标跟踪（红外车辆监控）。平台支持扩展到故障诊断、时序预测、多模态融合等场景。

## 多场景边缘 AI 平台

```
┌──────────────────────────────────────────────────────────────────┐
│                    PC 端: ISG-mian 通用 AI 管控平台               │
│                                                                   │
│  数据集管理 │ 数据清洗 │ 样本增强 │ 模型训练 │ 评估 │ RKNN导出    │
│                                                                   │
│  场景 1: 智能摄像头    场景 2: 故障诊断    场景 3: 多模态融合      │
│  用: detection        用: fault_diagnosis  用: multimodal        │
│      cleaning(image)       timeseries            detection        │
│      generation(image)     cleaning(tabular)     timeseries       │
│      evaluation            generation(audio)     evaluation       │
│  导出: YOLOv5.rknn     导出: LSTM.rknn       导出: Fusion.rknn   │
│                                                                   │
│  场景 4: 声纳/音频      场景 5: 船舶/海岸线    ...更多场景         │
│  用: timeseries         用: detection                             │
│      cleaning(audio)         evaluation                           │
│      generation(audio)       simulation_evaluation                │
│  导出: AudioCNN.rknn    导出: Segment.rknn                        │
│                                                                   │
│              边缘设备管理 (gRPC 模型推送 / MQTT 结果回收)          │
└──────────────────────────┬───────────────────────────────────────┘
                           │  gRPC / MQTT
                           ▼
┌──────────────────────────────────────────────────────────────────┐
│                RK3399Pro 板子端: 通用边缘推理引擎                  │
│                                                                   │
│  硬件不变, 驱动不变, 只换 .rknn 模型文件                           │
│                                                                   │
│  摄像头 ──→ V4L2 DMA-BUF ──→ NPU 推理 ──→ 后处理 ──→ MQTT 上报   │
│  传感器 ──→ UART/SPI/I2C ──→ 数据融合 ──→ 推理 ──→ 结果输出      │
│                                                                   │
│  场景切换: PC 端 gRPC 下发新模型 → 板子热加载 → 无缝切换          │
└──────────────────────────────────────────────────────────────────┘
```

## 架构 (5 层)

```
┌──────────────────────────────────────────────────────────────────┐
│ Layer 5: 训练管理端 (x86 PC)                                      │
│   ISG-mian (PySide6 + QML) — 通用 AI 数据平台                     │
│   数据集管理 / 数据清洗 / 样本增强 / 模型训练 / 评估 / RKNN导出    │
│   边缘设备管理 (gRPC 模型推送 / MQTT 结果回收 / 场景切换)          │
│   支持: 图像 / 音频 / 时序 / 表格 / 多模态 数据                    │
├──────────────────────────────────────────────────────────────────┤
│ Layer 4: AI 推理应用 (RK3399Pro)                                  │
│   C++17 systemd Service — 通用推理引擎                             │
│   四线程流水线: 采集 → NPU推理 → 后处理/跟踪 → MQTT上报            │
│   gRPC Server: 模型热加载 / 场景切换 / 远程管控                    │
│   模型无关: 换 .rknn 即可切换检测/分类/分割/时序任务               │
├──────────────────────────────────────────────────────────────────┤
│ Layer 3: 多媒体中间件 (GStreamer)                                 │
│   自定义 NPU 推理插件 (rknninference)                              │
│   检测框绘制插件 (rknndraw)                                        │
│   V4L2 Source → H.264 硬件编码 (MFC) → RTSP 推流                  │
├──────────────────────────────────────────────────────────────────┤
│ Layer 2: Linux 内核与驱动 (Linux 4.19)                            │
│   设备树: CMA / NPU / I2C / MIPI CSI / UART / SPI / GPIO          │
│   自定义驱动: IMX415 V4L2 sub-device / UART传感器 / GPIO触发       │
│   预留: SPI/I2S 接口 (扩展音频/振动传感器)                         │
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
│       │   ├── rknn1_engine.cpp  # RKNN1 API 推理引擎 (模型无关)
│       │   ├── yolov5/           # YOLOv5 后处理 (decode + NMS)
│       │   └── deepsort/         # SORT 跟踪 (卡尔曼 + 匈牙利)
│       ├── io/                   # V4L2 DMA-BUF 采集 / 文件输入
│       └── comm/                 # MQTT 上报 / gRPC 服务
│
├── training/             # Layer 5: PC 端管理平台 (ISG-mian)
│   ├── backend/services/ #   模型导出 + 边缘设备管理
│   ├── plugins/
│   │   ├── detection/     #   YOLOv5 目标检测训练
│   │   ├── cleaning/      #   数据清洗 (图像/音频/表格/文本)
│   │   ├── generation/    #   数据增强 (图像/音频/文本)
│   │   ├── evaluation/    #   模型评估
│   │   ├── training/      #   训练插件 (检测/分类/分割/时序)
│   │   ├── timeseries/    #   时序分析 (船舶/振动/传感器)
│   │   ├── fault_diagnosis/ # 工业故障诊断
│   │   └── multimodal/    #   多模态融合
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
┌─ PC 端 ─────────────────────────────────────────────────────────┐
│                                                                   │
│  数据集导入 → 清洗 → 增强 → 训练 → 评估 → RKNN导出               │
│                                                       │          │
│                                              gRPC PushModel       │
└───────────────────────────────────────────────────────┼───────────┘
                                                        │
┌─ 板子端 ──────────────────────────────────────────────┼───────────┐
│                                                       ▼          │
│  摄像头 IMX415 ──MIPI CSI──→ ISP ──→ /dev/video0 (V4L2)         │
│  传感器 ──UART/SPI──→ /dev/uart_sensor (字符设备)                 │
│                                        │                          │
│                              V4l2Capture (DMA-BUF mmap)           │
│                                        │                          │
│                              Frame Queue (SPSC)                   │
│                                        │                          │
│                             NPU 推理 (rknn1_engine)               │
│                             ↑ 模型可热加载切换                    │
│                                        │                          │
│                             后处理 (decode/NMS/分类/回归)          │
│                                        │                          │
│                              SORT 跟踪 (可选, 按场景开关)          │
│                                        │                          │
│                              Track Queue (SPSC)                   │
│                                        │                          │
│                        ┌───────────────┼───────────────┐          │
│                        ↓               ↓               ↓          │
│                      MQTT            RTSP          Display        │
│                   (结果上报)      (视频推流)      (本地显示)       │
│                        │               │               │          │
└────────────────────────┼───────────────┼───────────────┼──────────┘
                         │               │               │
┌─ PC 端 ────────────────┼───────────────┼───────────────┼──────────┐
│                        ▼               ▼               ▼          │
│              MQTT 检测结果       RTSP 视频流      设备状态         │
│              → 实时展示         → 实时预览       → 监控面板       │
│              → 在线纠错         → 录像存储       → 告警通知       │
│              → 数据回收入库     → 截图标注       → 远程管控       │
└──────────────────────────────────────────────────────────────────┘
```

## 关键技术

| 技术 | 用途 | 位置 |
|------|------|------|
| **设备树** | CMA 512MB / NPU / I2C / MIPI CSI / UART / SPI / GPIO / pinctrl | `kernel/dts/` |
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
| **ISG-mian** | 通用 AI 数据平台 (图像/音频/时序/表格/多模态) | `training/` |

## 项目统计

```
文件总数:  300+
代码行数:  63,500+

C (内核驱动 + GStreamer):         2,950 行
C++ (推理应用):                   2,886 行
头文件 (.h):                        670 行
DTS (设备树):                       465 行
Proto (gRPC/Protobuf):             123 行
─────────────────────────────────────────
C/C++/DTS/Proto 总计:             7,094 行

Python (PC 端管理平台):         ~40,000 行
QML (GUI):                       ~3,000 行
Shell (构建/部署脚本):           ~600 行
配置 (Buildroot/systemd/YAML):  ~800 行
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