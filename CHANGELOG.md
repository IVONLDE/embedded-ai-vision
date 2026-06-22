# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

## [Unreleased]

### Added
- 线程健康监控 + systemd 看门狗 (`edge/src/pipeline/pipeline.cpp`, +85行)
  - 5个工作线程各自原子心跳 (clock_gettime MONOTONIC)
  - 主循环100ms检查, 5秒超时判定线程死亡 → 触发优雅关机
  - sd_notify(WATCHDOG=1) 集成 systemd WatchdogSec=30
- NPU 过热保护 + 推理超时检测 (`edge/src/inference/rknn1_engine.cpp`, +75行)
  - 每30帧读取 /sys/class/thermal/thermal_zone*/temp
  - 三级保护: 80°C警告 → 90°C降频(usleep 100ms) → 105°C关机(SIGTERM)
  - 推理超时: clock_gettime 记录 rknn_run 耗时, >500ms告警
- 传感器数据消费层 (`edge/src/pipeline/pipeline.cpp`, +60行)
  - pipeline_config: 新增 SensorConfig (uart/spi enabled + device path)
  - 输出线程: O_NONBLOCK 打开 /dev/uart_sensor + /dev/spi_sensor
  - 每10帧非阻塞读取传感器数据, 附加到MQTT上报
- MQTT 自动重连 + 离线消息缓冲 (`edge/src/comm/mqtt_publisher.cpp`, +55行)
  - mosquitto_reconnect_delay_set 指数退避 (1s → 300s)
  - 断网时消息缓冲到 deque<PendingMsg> (最多100条)
  - 重连成功后自动 flush_pending_messages() 补发
- gRPC Server Streaming 实时检测结果推送 (`edge/proto/edge_service.proto`, +27行)
  - 新增 StreamDetections RPC (server streaming)
  - 新增 DetectionEvent/DetectionBox message 类型
- GetStatus 填充真实硬件指标 (`edge/src/comm/grpc_server.cpp`, +60行)
  - CPU/NPU温度: 读取 /sys/class/thermal/thermal_zone*/temp
  - 内存: 解析 /proc/meminfo (MemTotal/MemAvailable)
  - 磁盘: statvfs(/data) 检查剩余空间, <100MB警告
  - uptime: time(nullptr) - _start_time
- GStreamer H.264/H.265 硬件视频编码器 (`edge/src/io/video_encoder.cpp`, 388行)
  - 基于 Rockchip MPP (mpph264enc/mpph265enc) 硬件编码
  - 支持动态码率调整 + 关键帧请求 + 录制启停
- RTSP 实时推流服务 (`edge/src/io/rtsp_server.cpp`, 237行)
  - 基于 gst-rtsp-server, 独立线程运行 GLib main loop
  - 管道: appsrc → videoconvert → mpph264enc → h264parse → rtph264pay
- SPI 传感器字符设备驱动 (`kernel/drivers/peripheral/spi_sensor.c`, 772行)
  - spi_driver + spi_device 框架 (符合 SPI 子系统规范)
  - 全双工传输 (spi_sync) + ioctl 配置 (速度/模式/位宽) + sysfs 统计
- 帧数据传递方案: 推理→跟踪→输出线程所有权转移
  - DetectResult/TrackResult 新增 frame_data/width/height 字段
  - 推理线程在归还 V4L2 缓冲区前 memcpy 帧数据
  - 输出线程推入编码器/RTSP 后 delete[] 释放
- MQTT 远程控制: 录制/RTSP 启停命令
  - PC 端 QML 按钮发送 start/stop_recording, start/stop_rtsp
  - 板子端输出线程轮询原子标志动态启停编码器/RTSP
- 文档完善：新增 DEVELOPMENT.md、CONTRIBUTING.md、CHANGELOG.md、API_REFERENCE.md、TESTING.md
- 文档完善：training/README.md 重写，training/docs/BACKEND_ARCHITECTURE.md 新增
- gRPC 服务端完整实现（EdgeServiceImpl），支持 8 个 RPC：
  - PushModel：模型二进制推送 + SHA256 校验 + 热加载
  - SwitchScene：场景切换（face/body/vehicle/defect）
  - GetStatus：设备状态查询（FPS/NPU/温度/内存等）
  - UpdateConfig：运行时配置更新
  - Restart：远程重启服务
  - GetVersionInfo：OTA 版本查询
  - PushAppUpdate：应用二进制 OTA 升级
  - Rollback：模型/应用版本回滚
- Avahi/mDNS 服务发现配置（_edge-ai._tcp）
- CMake proto 自动编译规则，支持 pkg-config 降级查找 gRPC

### Fixed
- 修复 MQTT 命令转发链路断裂: handle_command() 缺少录制/RTSP 命令分支，导致 PC 端下发的 start_recording 等命令被静默丢弃
- 修复帧复制条件: 仅检查配置文件 (save_video/enable_rtsp) 而非运行时状态，导致远程启动录制后 frame_data 为 nullptr
- RKNN1 引擎兼容性：rknn_init2 改为 rknn_init，适配 API 1.7.5 + DRV 1.7.5 匹配，避免 TOO_MANY_CLIENT 错误
- dump_tensor_attr 安全打印，避免未终止字符串问题

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
