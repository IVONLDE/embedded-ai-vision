# 边缘部署指南

## 环境要求

| 组件 | 版本/型号 | 说明 |
|------|-----------|------|
| 硬件 | RK3399Pro | 2×A72 + 4×A53 + NPU |
| 内存 | ≥4GB LPDDR4 | NPU CMA 需 ≥256MB |
| 存储 | ≥16GB eMMC/SD | 系统+模型+日志 |
| 内核 | Linux 4.19 (Rockchip BSP) | 需 NPU/V4L2/MIPI 驱动 |
| 摄像头 | IMX415 | MIPI CSI-2 4-lane |

## 构建 Buildroot 镜像

```bash
# 1. 下载 Buildroot
git clone https://github.com/buildroot/buildroot.git
cd buildroot

# 2. 添加外部配置
make BR2_EXTERNAL=../embedded-ai-vision/buildroot-external rk3399pro_edge_ai_defconfig

# 3. 编译
make -j$(nproc)

# 4. 产物在 output/images/
#   - sdcard.img  (SD卡镜像)
#   - rootfs.ext4 (文件系统)
#   - Image       (内核)
#   - rk3399pro-edge-ai-camera.dtb (设备树)
```

## 本地编译 (板子上直接编译)

如果板子上已有系统（Debian 10），可以直接编译 edge 推理引擎：

```bash
cd edge
cmake -S . -B build          # 需要 cmake ≥ 3.13
make -C build -j4

# 编译产物
./build/edge-ai-camera --help
```

### 替换 3rdparty rknn_api.h

项目 `3rdparty/librknn_api/include/rknn_api.h` 是占位头文件，
编译前建议替换为系统安装的真实 Rockchip API 头文件：

```bash
cp /usr/include/rockchip/rknn_api.h edge/3rdparty/librknn_api/include/
```

真实头文件 (360 字节 `rknn_tensor_attr`) 与占位符 (124 字节) 的结构体
布局不同，使用占位符会导致 `rknn_query` 返回 size 不匹配错误。

### 无摄像头测试模式

配置 `type: "video_file"` 可从本地图片/视频文件读取帧：

```yaml
input:
  type: "video_file"                     # v4l2_camera / video_file / rtsp_stream
  file_path: "/opt/edge-ai/models/dog_640.jpg"
```

支持单张图片 (OpenCV VideoCapture 读取为 1 帧) 和 mp4 视频文件。

## 烧写 SD 卡

```bash
# Linux
sudo dd if=output/images/sdcard.img of=/dev/sdX bs=4M status=progress

# Windows (用 Rufus 或 Win32DiskImager)
```

## 上电启动

1. 插入 SD 卡
2. 连接串口 (1500000 8N1)
3. 连接以太网
4. 上电

```
U-Boot 2020.07 → Linux 4.19 → systemd → edge-ai-camera.service
```

## PC 端推送模型

```bash
# 方式 1: 通过部署脚本
cd training/scripts
./deploy_to_edge.sh 192.168.1.50 models/yolov5n.rknn vehicle

# 方式 2: 手动 scp + gRPC
scp model.rknn root@192.168.1.50:/opt/edge-ai/models/current.rknn
ssh root@192.168.1.50 "systemctl reload edge-ai-camera"
```

## 开始推理

```bash
# 检查服务状态
ssh root@192.168.1.50 "systemctl status edge-ai-camera"

# 查看日志
ssh root@192.168.1.50 "journalctl -u edge-ai-camera -f"

# 查看检测结果 (MQTT)
mosquitto_sub -h 192.168.1.50 -t 'edge/rk3399pro-edge-001/detections' -v
```

## 常见问题

### 摄像头无画面

```bash
# 检查 V4L2 设备
v4l2-ctl --list-devices
# 检查 MIPI CSI 状态
dmesg | grep -i mipi
# 检查 ISP 管道
media-ctl -p
```

### NPU 推理失败

```bash
# 检查 NPU 驱动
dmesg | grep -i rknpu
# 检查 CMA 内存
cat /proc/meminfo | grep Cma
# 检查模型文件
rknpu_tool --info /opt/edge-ai/models/current.rknn
```