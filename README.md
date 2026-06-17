# embedded-ai-vision

嵌入式 Linux 边缘 AI 智能摄像头系统 — 基于 RK3399Pro 的全栈方案。

## 项目概述

将 **YOLOv5 目标检测 + SORT 多目标跟踪** 部署到 RK3399Pro 嵌入式平台，通过**自定义 Linux 内核驱动、设备树、GStreamer 多媒体管道、systemd 服务化**实现从摄像头采集到 AI 推理到结果上报的完整链路。

PC 端通过 **ISG-mian** 进行数据集管理、模型训练、RKNN 模型导出和边缘设备运维。

## 架构 (5 层)

| Layer | 层级 | 技术栈 |
|-------|------|--------|
| 5 | 训练管理端 (x86 PC) | PySide6 + QML, RKNN-Toolkit1, gRPC Client |
| 4 | AI 推理应用 (RK3399Pro) | C++17, RKNN1 API, SORT, systemd |
| 3 | 多媒体中间件 | GStreamer, V4L2, H.264 硬件编码 |
| 2 | Linux 内核与驱动 | Linux 4.19, Device Tree, V4L2 sub-device, UART char driver |
| 1 | 系统构建 | Buildroot external tree, cross-compile |

## 目录结构

```
embedded-ai-vision/
├── buildroot-external/   # Layer 1: Buildroot 外部树 (rootfs构建)
├── kernel/               # Layer 2: 内核 defconfig + 设备树 + 自定义驱动
├── gstreamer/            # Layer 3: 自定义 GStreamer NPU 推理插件
├── edge/                 # Layer 4: C++ 边缘 AI 推理应用
├── training/             # Layer 5: Python 训练端 (ISG-mian 扩展)
├── docs/                 # 开发文档
└── scripts/              # 构建/烧写/调试脚本
```

## 快速开始

详见 `docs/` 目录下的开发文档。
