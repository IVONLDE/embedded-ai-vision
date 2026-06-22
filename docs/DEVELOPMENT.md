# 开发指南

面向开发者的环境搭建、开发流程、代码规范和调试技巧。

## 环境要求

### 通用

- Git ≥ 2.30
- CMake ≥ 3.13
- GCC ≥ 9.0 (支持 C++17)
- Python ≥ 3.10

### 边缘端 (C++)

- RK3399Pro 开发板（或 QEMU aarch64 模拟器）
- Buildroot 交叉编译工具链（Linaro ARM GCC 10.3）
- Rockchip NPU 驱动 + RKNN1 SDK

### PC 端 (Python)

- PySide6 ≥ 6.5
- PyTorch ≥ 2.0
- RKNN-Toolkit1 ≥ 1.7（模型导出，需 Python 3.6 环境）

## 环境搭建

### 1. 克隆仓库

```bash
git clone git@github.com:IVONLDE/embedded-ai-vision.git
cd embedded-ai-vision
```

### 2. PC 端开发环境

```bash
cd training
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 3. 边缘端开发环境

#### 本地编译（板子上直接编译）

```bash
cd edge
cmake -S . -B build
make -C build -j4
```

> **注意**：编译前需替换 3rdparty 占位头文件：
> ```bash
> cp /usr/include/rockchip/rknn_api.h edge/3rdparty/librknn_api/include/
> ```

#### 交叉编译（x86 主机上编译）

```bash
# 使用 Buildroot SDK
./scripts/build_all.sh sdk

# 或 x86 语法检查
./scripts/build_all.sh x86
```

#### Buildroot 完整镜像构建

```bash
# 下载 Buildroot
git clone https://github.com/buildroot/buildroot.git
cd buildroot

# 使用项目外部配置
make BR2_EXTERNAL=../embedded-ai-vision/buildroot-external rk3399pro_edge_ai_defconfig

# 编译
make -j$(nproc)
```

产物在 `output/images/`：
- `sdcard.img` — SD 卡镜像
- `rootfs.ext4` — 文件系统
- `Image` — 内核
- `rk3399pro-edge-ai-camera.dtb` — 设备树

### 4. 生成 gRPC 代码

```bash
./scripts/gen_proto.sh
```

生成：
- C++ stubs → `edge/src/comm/generated/`
- Python stubs → `training/backend/services/generated/`

## 项目结构

```
embedded-ai-vision/
├── buildroot-external/   # Layer 1: Buildroot 外部树
├── kernel/               # Layer 2: Linux 内核与驱动
├── gstreamer/            # Layer 3: GStreamer 自定义插件
├── edge/                 # Layer 4: C++ 边缘推理应用
├── training/             # Layer 5: PC 端管理平台
├── docs/                 # 项目文档
└── scripts/              # 构建/部署脚本
```

各层详细说明见 [ARCHITECTURE.md](ARCHITECTURE.md)。

## 开发流程

### 边缘端 (C++)

1. 修改 `edge/src/` 下的源码
2. 本地编译验证：
   ```bash
   cd edge && cmake -S . -B build && make -C build -j4
   ```
3. 部署到板子测试：
   ```bash
   scp build/edge-ai-camera root@192.168.1.50:/usr/bin/
   ssh root@192.168.1.50 "systemctl restart edge-ai-camera"
   ```
4. 查看日志：
   ```bash
   ssh root@192.168.1.50 "journalctl -u edge-ai-camera -f"
   ```

### PC 端 (Python)

1. 修改 `training/` 下的源码
2. 运行测试：
   ```bash
   cd training && python -m pytest tests/ -v
   ```
3. 启动应用验证：
   ```bash
   python main.py
   ```

### 内核驱动

1. 修改 `kernel/drivers/` 下的源码
2. 编译内核模块：
   ```bash
   cd kernel/drivers/camera && make    # IMX415
   cd kernel/drivers/peripheral && make  # UART/SPI/GPIO
   ```
3. 部署到板子：
   ```bash
   scp imx415.ko root@192.168.1.50:/lib/modules/4.19.111/extra/
   scp spi_sensor.ko root@192.168.1.50:/lib/modules/4.19.111/extra/
   ssh root@192.168.1.50 "insmod /lib/modules/4.19.111/extra/spi_sensor.ko"
   ```

### GStreamer 插件

1. 修改 `gstreamer/plugin/` 下的源码
2. 编译：
   ```bash
   cd gstreamer && cmake -S . -B build && make -C build -j4
   ```
3. 安装到板子：
   ```bash
   scp build/libgstrknninference.so root@192.168.1.50:/usr/lib/gstreamer-1.0/
   ```

## 代码规范

### 通用

- **提交信息**：中文描述 + 英文前缀
  ```
  feat: 添加 ByteTrack 跟踪算法支持
  fix: 修复 NPU 推理内存泄漏问题
  docs: 更新部署指南
  refactor: 重构 Pipeline 配置加载逻辑
  ```
- **代码格式化**：提交前格式化代码
- **注释语言**：中文领域逻辑注释，英文代码标识符

### C++ (边缘端)

- **标准**：C++17
- **命名**：
  - 类名：`PascalCase`（如 `Rknn1Engine`）
  - 函数/变量：`snake_case`（如 `hot_reload_model`）
  - 成员变量：`_` 前缀（如 `_ctx`, `_model_path`）
  - 常量/宏：`UPPER_SNAKE_CASE`（如 `RKNN_MAX_OUTPUTS`）
- **头文件保护**：使用 `#pragma once`
- **智能指针**：优先使用 `std::unique_ptr` / `std::shared_ptr`
- **错误处理**：致命错误抛 `std::runtime_error`，可恢复错误返回 -1

### Python (PC 端)

- **标准**：Python 3.10+
- **命名**：
  - 类名：`PascalCase`（如 `DatasetService`）
  - 函数/变量：`snake_case`（如 `create_dataset`）
  - 常量：`UPPER_SNAKE_CASE`（如 `DEFAULT_ALGORITHMS`）
- **类型注解**：所有公开方法使用类型注解
- **数据库会话**：
  - 主线程：依赖注入的 `session_factory`
  - 后台线程：`SessionLocal()` 线程局部会话
- **QML 通信**：通过 `BackendService` 信号/槽，不直接操作 UI
- **返回值**：`{"status": "ok/error", "data/message": ...}`

### 设备树 (DTS)

- **节点命名**：`<外设名>-<功能>`（如 `rknpu: npu@ffbc0000`）
- **属性**：使用 Rockchip BSP 约定
- **注释**：关键配置添加注释说明

## 调试技巧

### 串口调试

```bash
# 连接串口 (1500000 8N1)
minicom -D /dev/ttyUSB0 -b 1500000

# 或使用 screen
screen /dev/ttyUSB0 1500000
```

### 日志查看

```bash
# 边缘端服务日志
journalctl -u edge-ai-camera -f

# 内核日志
dmesg | grep -i rknpu
dmesg | grep -i imx415

# PC 端应用日志
# 日志输出到 stderr 和 data/logs/ 目录
```

### NPU 调试

```bash
# 检查 NPU 驱动
dmesg | grep -i rknpu
ls -la /dev/rknpu

# 检查 CMA 内存
cat /proc/meminfo | grep Cma

# 检查模型信息
rknpu_tool --info /opt/edge-ai/models/current.rknn

# NPU 性能统计
# 在 pipeline.yaml 中启用 RKNN_FLAG_COLLECT_PERF_MASK
```

### V4L2 调试

```bash
# 列出 V4L2 设备
v4l2-ctl --list-devices

# 查看设备能力
v4l2-ctl -d /dev/video0 --list-formats-ext

# 查看当前配置
v4l2-ctl -d /dev/video0 --get-fmt-video

# 检查 MIPI CSI 状态
dmesg | grep -i mipi

# 查看 ISP 管道
media-ctl -p
```

### MQTT 调试

```bash
# 订阅所有边缘设备消息
mosquitto_sub -h 192.168.1.50 -t 'edge/#' -v

# 订阅检测结果
mosquitto_sub -h 192.168.1.50 -t 'edge/rk3399pro-edge-001/detections' -v

# 发送场景切换指令
mosquitto_pub -h 192.168.1.50 -t 'edge/rk3399pro-edge-001/command' \
    -m '{"command":"switch_scene","scene_name":"vehicle"}'

# 远程启动视频录制
mosquitto_pub -h 192.168.1.50 -t 'edge/rk3399pro-edge-001/command' \
    -m '{"command":"start_recording"}'

# 远程停止视频录制
mosquitto_pub -h 192.168.1.50 -t 'edge/rk3399pro-edge-001/command' \
    -m '{"command":"stop_recording"}'

# 远程启动 RTSP 推流
mosquitto_pub -h 192.168.1.50 -t 'edge/rk3399pro-edge-001/command' \
    -m '{"command":"start_rtsp"}'

# 远程停止 RTSP 推流
mosquitto_pub -h 192.168.1.50 -t 'edge/rk3399pro-edge-001/command' \
    -m '{"command":"stop_rtsp"}'
```

### gRPC 调试

```bash
# 安装 grpcurl
# 列出服务
grpcurl -plaintext 192.168.1.50:50051 list

# 查询设备状态
grpcurl -plaintext 192.168.1.50:50051 EdgeService/GetStatus \
    -d '{"device_id": "rk3399pro-edge-001"}'

# 通过 Unix Socket
grpcurl -plaintext -unix /tmp/edge-ai-grpc.sock list
```

### SPI 传感器调试

```bash
# 检查 SPI 设备节点
ls -la /dev/spi_sensor

# 读取传感器数据
cat /dev/spi_sensor

# 查看统计信息 (sysfs)
cat /sys/class/spi_sensor/spi_sensor/tx_bytes_total
cat /sys/class/spi_sensor/spi_sensor/rx_bytes_total
cat /sys/class/spi_sensor/spi_sensor/errors

# 配置 SPI 参数
# 需要编写 C 程序使用 ioctl:
#   SPI_IOC_WR_SPEED_HZ    - 设置时钟频率
#   SPI_IOC_WR_MODE        - 设置 SPI 模式 (0-3)
#   SPI_IOC_WR_BITS_PER_WORD - 设置位宽
#   SPI_IOC_TRANSFER       - 全双工传输
```

### 性能分析

```bash
# CPU 使用率
htop

# NPU 推理耗时（日志中查看）
journalctl -u edge-ai-camera | grep "inference"

# 内存使用
cat /proc/$(pidof edge-ai-camera)/status | grep Vm

# 帧率统计
# MQTT 心跳消息中包含 frame_index，可计算 FPS
```

## 构建脚本

### build_all.sh

```bash
./scripts/build_all.sh           # 本地 aarch64 编译
./scripts/build_all.sh x86       # x86 语法检查
./scripts/build_all.sh sdk       # Buildroot SDK 交叉编译
```

### gen_proto.sh

```bash
./scripts/gen_proto.sh           # 生成 gRPC C++ 和 Python 代码
```

### export_to_rknn1.py

```bash
python training/scripts/export_to_rknn1.py \
    --model_path model.pt \
    --model_type yolov5 \
    --output_path model.rknn \
    --do_quantization \
    --dataset calibration_images/
```

### deploy_to_edge.sh

```bash
./training/scripts/deploy_to_edge.sh 192.168.1.50 model.rknn vehicle
```

## 测试

### PC 端测试

```bash
cd training

# 运行全部测试
python -m pytest tests/ -v

# 运行单个测试文件
python -m pytest tests/test_backend_dataset_service.py -v

# 运行特定测试
python -m pytest tests/test_backend_chain.py::test_full_cleaning_workflow -v

# 查看覆盖率
python -m pytest tests/ --cov=backend --cov-report=html
```

### 边缘端测试

边缘端目前无自动化测试框架，建议手动测试：

1. **无摄像头模式**：修改 `pipeline.yaml` 中 `type: "video_file"` 进行离线测试
2. **MQTT 验证**：使用 `mosquitto_sub` 验证检测结果输出
3. **gRPC 验证**：使用 `grpcurl` 验证服务接口

详见 [TESTING.md](TESTING.md)。

## 常见问题

### 编译错误 "rknn_tensor_attr 大小不匹配"

3rdparty 占位头文件与真实 SDK 头文件结构体大小不同：
```bash
cp /usr/include/rockchip/rknn_api.h edge/3rdparty/librknn_api/include/
```

### Python 导入错误

确保虚拟环境已激活：
```bash
source training/.venv/bin/activate
```

### NPU 推理返回 -1

1. 检查 NPU 驱动：`dmesg | grep rknpu`
2. 检查 CMA 内存：`cat /proc/meminfo | grep Cma`
3. 检查模型文件完整性：`sha256sum /opt/edge-ai/models/current.rknn`

### MQTT 连接失败

1. 检查 Broker 是否运行：`systemctl status mosquitto`
2. 检查网络连通性：`ping 192.168.1.100`
3. 检查防火墙：`iptables -L -n | grep 1883`
