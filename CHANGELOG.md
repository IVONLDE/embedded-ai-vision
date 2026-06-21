# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

## [Unreleased]

### Added
- 文档完善：新增 DEVELOPMENT.md、CONTRIBUTING.md、CHANGELOG.md、API_REFERENCE.md、TESTING.md
- 文档完善：training/README.md 重写，training/docs/BACKEND_ARCHITECTURE.md 新增

## [1.2.0] - 2026-06-XX

### Added
- OTA 应用远程升级支持 (OtaManager)
- SHA256 校验和验证
- 自动回滚机制
- MQTT OTA 状态上报
- gRPC Rollback 接口

### Changed
- 重构 Pipeline 配置加载，支持多场景配置
- 优化 NPU 推理引擎热加载流程

### Fixed
- 修复 MQTT 重连时的内存泄漏
- 修复 V4L2 采集在高帧率下的丢帧问题

## [1.1.0] - 2025-12-XX

### Added
- 多模态数据集支持（图像 + 4D 雷达 + AIS）
- 故障诊断训练插件 (hyfd_fault_diagnosis)
- 多 Agent 仿真评估算法
- ISG-mian 插件系统 (PARAMETERS 反射)

### Changed
- 重构后端架构为分层设计 (Services → Repositories → ORM)
- 统一 QML → BackendService → BackendBridge 通信模式
- 清洗/增强/评估任务全部迁移到插件架构

### Fixed
- 修复 RKNN 导出时的 INT8 量化精度损失问题
- 修复数据集导入时的大文件内存溢出
- 修复边缘设备心跳超时误报

## [1.0.0] - 2025-06-XX

### Added
- 初始发布
- 五层架构：Buildroot + 内核驱动 + GStreamer + C++ 推理 + Python 管控
- 边缘端：
  - 四线程流水线：V4L2 采集 → NPU 推理 → SORT 跟踪 → MQTT 上报
  - YOLOv5 目标检测
  - SORT 多目标跟踪
  - gRPC 远程服务
  - MQTT 结果上报
  - 模型热加载
- PC 端：
  - PySide6 + QML 桌面应用
  - 数据集管理（导入/导出/预览）
  - 数据清洗（模糊/重复/异常检测）
  - 样本增强（几何变换/颜色抖动/音频增强）
  - 模型训练（YOLOv5）
  - 模型评估（mAP/Precision/Recall）
  - RKNN 导出（INT8 量化）
  - 边缘设备管理（MQTT + gRPC）
- 内核驱动：
  - IMX415 V4L2 sub-device 驱动
  - UART 传感器字符设备驱动
  - GPIO 中断触发驱动
- GStreamer 插件：
  - rknninference（NPU 推理）
  - rknndraw（检测框绘制）
- Buildroot 外部树：
  - 自定义内核配置片段
  - 自定义软件包（edge-ai-app、rknn-driver）
  - SD 卡镜像生成

### Known Issues
- RTSP 输出在高分辨率下可能丢帧
- gRPC Unix Socket 权限需手动设置
