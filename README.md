# RK-NPU Cortex

嵌入式 Linux 边缘 AI 推理平台 — 基于 RK3399Pro 的全栈方案。

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
│   H.264/H.265 硬件编码 (mpph264enc/mpph265enc)                    │
│   RTSP 实时推流 (gst-rtsp-server)                                  │
├──────────────────────────────────────────────────────────────────┤
│ Layer 2: Linux 内核与驱动 (Linux 4.19)                            │
│   设备树: CMA / NPU / I2C / MIPI CSI / UART / SPI / GPIO          │
│   自定义驱动: IMX415 V4L2 sub-device / UART传感器 / GPIO触发 / SPI传感器 │
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
│       └── peripheral/   #   UART传感器 + GPIO触发 + SPI传感器 字符设备驱动
│
├── gstreamer/            # Layer 3: GStreamer 自定义插件 + 编码推流
│   └── plugin/
│       ├── gstrknninference.c   # NPU 推理元素 (GstVideoFilter)
│       └── gstrknndraw.c        # 检测框绘制元素
│
├── edge/                 # Layer 4: C++ 边缘 AI 推理应用
│   ├── config/           #   pipeline.yaml + systemd unit + avahi mDNS
│   ├── proto/            #   gRPC + Protobuf 协议定义 (8 RPC)
│   └── src/
│       ├── main.cpp              # 主入口 (YAML + CLI)
│       ├── pipeline/             # 四线程流水线调度器
│       ├── inference/
│       │   ├── rknn1_engine.cpp  # RKNN1 API 推理引擎 (模型无关, 支持热加载)
│       │   ├── yolov5/           # YOLOv5 后处理 (decode + NMS)
│       │   └── deepsort/         # SORT 跟踪 (卡尔曼 + 匈牙利)
│       ├── io/
│       │   ├── v4l2_capture.cpp  # V4L2 DMA-BUF 零拷贝采集
│       │   ├── video_encoder.cpp # GStreamer + MPP H.264/H.265 硬件编码
│       │   └── rtsp_server.cpp   # RTSP 实时推流服务
│       └── comm/                 # MQTT 上报 / gRPC 服务 (8 RPC) / OTA 管理
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
│   ├── DEVELOPMENT.md    #   开发指南
│   ├── EDGE_DEPLOY.md    #   部署指南
│   ├── PROTOCOL.md       #   通信协议
│   ├── API_REFERENCE.md  #   API 参考
│   ├── TESTING.md        #   测试指南
│   └── NPU_REFERENCE.md  #   NPU 技术参考
│
├── training/docs/        # PC 端文档
│   ├── BACKEND_ARCHITECTURE.md  # 后端架构
│   ├── ALGORITHM_PLUGIN_SPEC.md # 插件开发规范
│   └── datasets/         # 数据集文档
│
├── CONTRIBUTING.md       # 贡献指南
├── CHANGELOG.md          # 变更日志
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
│                      MQTT          视频编码          Display      │
│                   (结果上报)    (H.264/H.265)      (本地显示)     │
│                        │          ↓      ↓               │          │
│                        │      文件录制  RTSP推流          │          │
│                        │          │      │               │          │
└────────────────────────┼──────────┼──────┼───────────────┼──────────┘
                         │               │               │
┌─ PC 端 ────────────────┼───────────────┼───────────────┼──────────┐
│                        ▼               ▼               ▼          │
│              MQTT 检测结果       RTSP 视频流      设备状态         │
│              → 实时展示         → 实时预览       → 监控面板       │
│              → 在线纠错         → 录像存储       → 告警通知       │
│              → 数据回收入库     → 截图标注       → 远程管控       │
│              → MQTT远程启停录制/RTSP             → 一键控制       │
└──────────────────────────────────────────────────────────────────┘
```

## 关键技术

| 技术 | 用途 | 位置 |
|------|------|------|
| **设备树** | CMA 512MB / NPU / I2C / MIPI CSI / UART / SPI / GPIO / pinctrl | `kernel/dts/` |
| **V4L2 Sub-device** | IMX415 摄像头 I2C 驱动 (regmap / controls / media pad) | `kernel/drivers/camera/` |
| **UART 字符驱动** | 传感器数据采集 (serdev / 环形缓冲 / wait_queue / sysfs) | `kernel/drivers/peripheral/` |
| **SPI 字符驱动** | SPI 传感器通信 (spi_sync 全双工 / ioctl 配置 / sysfs 统计) | `kernel/drivers/peripheral/` |
| **GPIO 中断驱动** | 按键/报警触发 (gpio_to_irq / tasklet底半部 / 去抖) | `kernel/drivers/peripheral/` |
| **GStreamer 插件** | NPU 推理元素 (GstVideoFilter / transform_frame_ip) | `gstreamer/plugin/` |
| **GStreamer MPP** | H.264/H.265 硬件编码 (mpph264enc / mpph265enc) | `edge/src/io/` |
| **RTSP 服务** | 实时视频推流 (gst-rtsp-server / 独立线程 GLib main loop) | `edge/src/io/` |
| **RKNN1 API** | NPU 推理 (rknn_init/run/inputs_set/outputs_get) | `edge/src/inference/` |
| **SORT 跟踪** | 卡尔曼滤波 + 匈牙利匹配 (纯CPU, 单核NPU适配) | `edge/src/inference/deepsort/` |
| **V4L2 DMA-BUF** | 摄像头→NPU 零拷贝采集 (mmap / VIDIOC_EXPBUF) | `edge/src/io/` |
| **帧数据传递** | 推理→跟踪→输出线程所有权转移 (避免 V4L2 缓冲区提前释放) | `edge/src/pipeline/pipeline.cpp` |
| **线程看门狗** | 5线程原子心跳 + 5秒超时检测 + systemd watchdog 集成 | `edge/src/pipeline/pipeline.cpp` |
| **NPU 温度保护** | thermal_zone 读取, 80°C警告/90°C降频/105°C关机 + 推理500ms超时检测 | `edge/src/inference/rknn1_engine.cpp` |
| **传感器消费层** | UART/SPI 字符设备 O_NONBLOCK 读取 + MQTT 上报 | `edge/src/pipeline/pipeline.cpp` |
| **MQTT** | 检测结果 + 心跳上报 + 远程控制 + 自动重连(指数退避1s→300s) + 离线缓冲100条 | `edge/src/comm/` |
| **gRPC** | 模型推送 / 场景切换 / OTA升级 / 流式检测推送 (9 RPC, Proto3) | `edge/src/comm/` + `edge/proto/` |
| **GetStatus 硬件指标** | thermal_zone/meminfo/statvfs 填充温度/内存/磁盘/uptime | `edge/src/comm/grpc_server.cpp` |
| **systemd** | 服务托管 (Type=notify / cgroups / 看门狗 / 安全加固) | `edge/config/` |
| **Buildroot** | 交叉编译 / rootfs 裁剪 / SD 卡镜像 | `buildroot-external/` |
| **RKNN-Toolkit1** | PyTorch → ONNX → RKNN 导出 + INT8 量化 | `training/scripts/` |
| **ISG-mian** | 通用 AI 数据平台 (图像/音频/时序/表格/多模态) | `training/` |

## 项目统计

```
文件总数:  320+
代码行数:  67,500+

板子端 (手写):
  C++ 推理应用 (.cpp):              5,251 行
  C++ 头文件 (手写 .h):             1,060 行
  C 内核驱动 (.c):                  3,080 行  (IMX415/UART/SPI/GPIO/NPU)
  C 驱动头文件 (.h):                  286 行
  GStreamer 插件 (.c):              1,522 行  (rknninference/rknndraw)
  设备树 (DTS):                       474 行
  Proto (gRPC/Protobuf):              207 行
  ─────────────────────────────────────────
  板子端总计:                     ~11,880 行

PC 端:
  Python (管理平台):              ~45,000 行
  QML (GUI):                      ~12,288 行

其他:
  Shell (构建/部署脚本):             ~600 行
  配置 (Buildroot/systemd/YAML):    ~820 行
  文档:                             ~400 行
```

### 板子端模块代码量分布

| 模块 | 行数 | 关键文件 |
|------|------|---------|
| Pipeline 调度器 | 899 | pipeline.cpp (4线程流水线+看门狗+帧传递) |
| gRPC 服务 | 660 | grpc_server.cpp (9 RPC + 真实指标) |
| NPU 推理引擎 | 580 | rknn1_engine.cpp (热加载+温度保护+超时) |
| OTA 管理 | 532 | ota_manager.cpp (SHA256+原子替换+回滚) |
| GStreamer 编码 | 387 | video_encoder.cpp (MPP H.264/H.265) |
| SORT 跟踪 | 348 | tracker.cpp (卡尔曼+匈牙利) |
| V4L2 采集 | 332 | v4l2_capture.cpp (DMA-BUF 零拷贝) |
| MQTT 通信 | 309 | mqtt_publisher.cpp (自动重连+消息缓冲) |
| RTSP 推流 | 237 | rtsp_server.cpp (gst-rtsp-server) |
| SPI 驱动 | 772 | spi_sensor.c (spi_sync 全双工) |
| IMX415 驱动 | 714 | imx415_v4l2.c (V4L2 sub-device) |
| UART 驱动 | 649 | uart_sensor.c (serdev+环形缓冲) |
| GPIO 驱动 | 546 | gpio_trigger.c (中断+tasklet) |
| NPU 驱动 | 399 | rknpu_drv.c (misc+wait_queue) |

## 快速开始

### PC 端 (训练管理)

```bash
cd training
pip install -r requirements.txt
python main.py
```

### 边缘端 (推理部署)

```bash
cd edge
cmake -S . -B build          # 需要 cmake ≥ 3.13
make -C build -j4
```

#### 运行模式

**有摄像头 (V4L2):**
```bash
./build/edge-ai-camera -c /opt/edge-ai/config/pipeline.yaml
```

**无摄像头 (文件输入测试):**
```bash
# 修改配置文件 type 为 video_file
sed -i 's/v4l2_camera/video_file/' /opt/edge-ai/config/pipeline.yaml
./build/edge-ai-camera -c /opt/edge-ai/config/pipeline.yaml
```

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
| GStreamer | ≥1.18 | 多媒体管道 + 硬件编码 + RTSP 推流 |
| gst-rtsp-server | ≥1.18 | RTSP 实时推流服务 |
| PySide6 | ≥6.5 | PC 端 GUI |
| PyTorch | ≥2.0 | 模型训练 |
| RKNN-Toolkit1 | ≥1.7 | 模型导出 |