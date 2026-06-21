# RK3399Pro NPU 版本匹配与部署指南

## 1. 问题背景

RK3399Pro 的 NPU 推理链路涉及 **3 个组件**，必须版本严格匹配：

| 组件 | 作用 | 版本来源 |
|---|---|---|
| `librknn_api.so` | RKNN C API 库（用户态） | Python rknn-toolkit 或系统包 `rknn-rk3399pro` |
| `npu_transfer_proxy` | USB 代理守护进程（连接 NPU 硬件） | 系统包 `rknn-rk3399pro` 或 Python rknn 包自带 |
| NPU 固件 (`boot.img`) | RK1808 NPU 芯片固件 | 系统包 `rknn-rk3399pro` 或 `RK3399Pro_npu/drivers/npu_firmware/` |

**不匹配症状**：`rknn_init` 使用 `RKNN_FLAG_COLLECT_PERF_MASK` 时返回 `-3`，报错 `ACK_PERF_TOO_MANY_CLIENT`。

### 1.1 版本不匹配的典型场景

```
E RKNNAPI: rknn_init,  msg_load_ack fail, ack = 6(ACK_PERF_TOO_MANY_CLIENT), expect 0(ACK_SUCC)!
E RKNNAPI: RKNN VERSION:
E RKNNAPI:   API: 1.7.5
E RKNNAPI:   DRV: 1.7.0    ← 不匹配！
```

- **API**：由 `librknn_api.so` 决定
- **DRV**：由 `npu_transfer_proxy` + NPU 固件共同决定

当 API ≠ DRV 时，`RKNN_FLAG_COLLECT_PERF_MASK` 不可用。用 `flag=0` 可临时绕过（但失去性能统计功能）。

---

## 2. 正确的版本匹配方案

### 2.1 推荐组合：API 1.7.5 + DRV 1.7.5

| 组件 | 版本 | 来源路径 |
|---|---|---|
| `librknn_api.so` | 1.7.5 | `~/.local/lib/python3.7/site-packages/rknn/api/lib/hardware/LION/linux-aarch64/librknn_api.so` |
| `npu_transfer_proxy` | Transfer v2.1.0 (配套 1.7.5) | `~/.local/lib/python3.7/site-packages/rknn/3rdparty/platform-tools/ntp/linux-aarch64/npu_transfer_proxy` |
| NPU 固件 | 配套 1.7.5 | `~/RK3399Pro_npu/drivers/npu_firmware/npu_fw/` |
| `rknn_api.h` 头文件 | API_VERSION "1.7.0" (兼容) | `/usr/include/rockchip/rknn_api.h` |

> **注意**：头文件 `API_VERSION` 宏是 "1.7.0"，但 `librknn_api.so` 运行时报告 API 1.7.5。这是正常的——头文件版本宏和库二进制版本可以不同步，只要结构体布局一致即可。

### 2.2 替代组合：API 1.6.0 + DRV 1.6.0

使用 `rknnlite` 包（更旧但稳定）：

| 组件 | 版本 | 来源路径 |
|---|---|---|
| `librknn_api.so` | 1.6.0 | `~/.local/lib/python3.7/site-packages/rknnlite/api/lib/hardware/LION/linux-aarch64/librknn_api.so` |
| `npu_transfer_proxy` | Transfer v2.0.0 | `~/.local/lib/python3.7/site-packages/rknnlite/3rdparty/platform-tools/ntp/linux-aarch64/npu_transfer_proxy` |

---

## 3. 从零部署：NPU 版本匹配操作步骤

### 3.1 前置条件

- TB-RK3399ProD 开发板，Debian 10 (aarch64)
- 已安装 Python 3.7 + rknn-toolkit 1.7.5：
  ```bash
  pip3 install rknn-toolkit==1.7.5
  ```
- 已安装系统包 `rknn-rk3399pro`（提供 `npu_powerctrl`、`npu_upgrade` 等工具）

### 3.2 步骤 1：替换 `npu_transfer_proxy`

系统包 `rknn-rk3399pro 1.7.1-1` 自带的 proxy 版本较旧，需替换为 rknn-toolkit 1.7.5 配套版本：

```bash
# 备份原版
sudo mv /usr/bin/npu_transfer_proxy /usr/bin/npu_transfer_proxy.system_orig

# 复制 rknn-toolkit 1.7.5 配套版本
sudo cp ~/.local/lib/python3.7/site-packages/rknn/3rdparty/platform-tools/ntp/linux-aarch64/npu_transfer_proxy /usr/bin/npu_transfer_proxy
sudo chmod +x /usr/bin/npu_transfer_proxy
```

**验证**：

```bash
strings /usr/bin/npu_transfer_proxy | grep "Transfer version"
# 期望输出: Transfer version 2.1.0 (b5861e7@2020-11-23T11:50:51)
```

### 3.3 步骤 2：替换 NPU 固件

系统包自带的固件版本较旧，需替换为 `RK3399Pro_npu` 配套版本：

```bash
# 备份原版
sudo cp -r /usr/lib/firmware/npu_fw /usr/lib/firmware/npu_fw.system_orig

# 复制配套固件
sudo cp ~/RK3399Pro_npu/drivers/npu_firmware/npu_fw/* /usr/lib/firmware/npu_fw/
```

**验证**：

```bash
md5sum /usr/lib/firmware/npu_fw/boot.img
# 对比: md5sum ~/RK3399Pro_npu/drivers/npu_firmware/npu_fw/boot.img
# 两者应一致
```

### 3.4 步骤 3：替换 `librknn_api.so`（如需要）

如果系统库版本不是 1.7.5，需要替换：

```bash
# 检查当前版本
strings /usr/lib/aarch64-linux-gnu/librknn_api.so | grep -E "^[0-9]+\.[0-9]+\.[0-9]+"

# 备份原版
sudo mv /usr/lib/aarch64-linux-gnu/librknn_api.so /usr/lib/aarch64-linux-gnu/librknn_api.so.system_orig

# 复制 1.7.5 版本
sudo cp ~/.local/lib/python3.7/site-packages/rknn/api/lib/hardware/LION/linux-aarch64/librknn_api.so /usr/lib/aarch64-linux-gnu/
```

> **注意**：替换系统库可能导致 `dpkg` 校验失败（`dpkg --verify rknn-rk3399pro`），但不影响运行。

### 3.5 步骤 4：重启 NPU 服务

```bash
sudo systemctl restart rknn-npu.service
sleep 3
systemctl status rknn-npu.service
# 期望: Active: active (running)
```

NPU 服务启动流程：

```
npu_powerctrl -i     → NPU 上电
npu_powerctrl -o     → NPU 复位
npu_upgrade TB-RK3399ProD  → 刷新 NPU 固件
npu_transfer_proxy   → USB 代理守护进程（常驻）
```

### 3.6 步骤 5：验证版本匹配

```bash
# 运行最小测试
cat > /tmp/test_rknn_version.cpp << 'EOF'
#include <cstdio>
#include <cstring>
#include "rknn_api.h"
int main() {
    rknn_context ctx = 0;
    FILE *fp = fopen("/opt/edge-ai/models/yolov5n.rknn", "rb");
    fseek(fp, 0, SEEK_END); long sz = ftell(fp); fseek(fp, 0, SEEK_SET);
    void *data = malloc(sz); fread(data, 1, sz, fp); fclose(fp);
    int ret = rknn_init(&ctx, data, sz, RKNN_FLAG_COLLECT_PERF_MASK, NULL);
    free(data);
    if (ret < 0) { printf("FAIL: rknn_init ret=%d\n", ret); return 1; }
    rknn_sdk_version ver;
    rknn_query(ctx, RKNN_QUERY_SDK_VERSION, &ver, sizeof(ver));
    printf("API: %s\nDRV: %s\n", ver.api_version, ver.drv_version);
    rknn_destroy(ctx);
    return 0;
}
EOF

g++ -std=c++17 -o /tmp/test_rknn_version /tmp/test_rknn_version.cpp \
    -I/usr/include/rockchip -lrknn_api -lpthread

/tmp/test_rknn_version
# 期望输出:
# API: 1.7.5 (bb79b30 build: 2023-07-18 16:49:12)
# DRV: 1.7.5 (bb79b30 build: 2023-07-18 10:49:14)
```

---

## 4. C++ 代码中使用 RKNN API 的注意事项

### 4.1 `rknn_init` vs `rknn_init2`

RKNN1 API 头文件同时定义了 `rknn_init` 和 `rknn_init2`：

```c
// rknn_init: 4 参数 + 第 5 参数 (void* opt)
int rknn_init(rknn_context* context, void* model, uint32_t size, uint32_t flag, void* opt);

// rknn_init2: 使用 rknn_init_extend 结构体
int rknn_init2(rknn_context* context, void* model, uint32_t size, uint32_t flag, rknn_init_extend* extend);
```

**推荐使用 `rknn_init`**：在 API 1.7.5 + DRV 1.7.5 组合下，`rknn_init` 更稳定。`rknn_init2` 在版本不匹配时更容易触发 `TOO_MANY_CLIENT` 错误。

```cpp
// ✅ 推荐
ret = rknn_init(&ctx, model_data, model_len, RKNN_FLAG_COLLECT_PERF_MASK, NULL);

// ❌ 不推荐（版本不匹配时更严格）
ret = rknn_init2(&ctx, model_data, model_len, RKNN_FLAG_COLLECT_PERF_MASK, NULL);
```

### 4.2 `RKNN_FLAG_COLLECT_PERF_MASK` 使用条件

| 条件 | `RKNN_FLAG_COLLECT_PERF_MASK` | `flag=0` |
|---|---|---|
| API = DRV | ✅ 正常 | ✅ 正常（无性能统计） |
| API ≠ DRV | ❌ `TOO_MANY_CLIENT` | ✅ 可用（无性能统计） |

**必须确保 API = DRV 才能使用性能统计。**

### 4.3 `rknn_tensor_attr` 结构体大小

当前头文件定义的结构体大小为 **360 字节**（`RKNN_MAX_DIMS=16`, `RKNN_MAX_NAME_LEN=256`）：

```c
sizeof(rknn_tensor_attr) = 360  // 4+4+64+256+4+4+4+4+4+1+3+4+4
```

调用 `rknn_query` 时必须传 `sizeof(rknn_tensor_attr)`，不能硬编码其他值。

### 4.4 stdout 缓冲问题

在 systemd 服务或重定向输出时，`printf` 不会自动 flush。**关键日志后必须加 `fflush(stdout)`**：

```cpp
printf("[RKNN1] Model loaded successfully\n");
fflush(stdout);  // ← 必须加！否则日志可能不显示
```

### 4.5 NPU 客户端互斥

RK3399Pro 的 NPU **同一时刻只允许一个客户端**。如果已有进程占用 NPU，后续 `rknn_init` 会报 `TOO_MANY_CLIENT`。

```bash
# 检查是否有进程占用 NPU
ps aux | grep edge-ai-camera | grep -v grep

# 杀掉占用进程
killall edge-ai-camera
```

---

## 5. 完整的 NPU 调用流程

### 5.1 启动链路

```
开机
  │
  ├─ rknn-npu.service (systemd)
  │    ├─ npu_powerctrl -i          (NPU 上电)
  │    ├─ npu_powerctrl -o          (NPU 复位)
  │    ├─ npu_upgrade TB-RK3399ProD (刷固件)
  │    └─ npu_transfer_proxy        (USB 代理守护进程)
  │         │
  │         │  USB (2207:180a)
  │         ↓
  │    RK1808 NPU (3 TOPS INT8)
  │
  └─ edge-ai-camera.service (systemd)
       │
       └─ edge-ai-camera --config pipeline.yaml
            │
            ├─ rknn_init()           → 通过 librknn_api.so → USB → proxy → NPU
            ├─ rknn_query()          → 查询输入/输出属性
            ├─ rknn_inputs_set()     → 设置输入数据
            ├─ rknn_run()            → 触发 NPU 推理
            ├─ rknn_outputs_get()    → 获取推理结果
            ├─ rknn_query(PERF_RUN)  → 获取推理耗时
            └─ rknn_outputs_release() → 释放输出
```

### 5.2 四线程流水线

```
CPU1 (A53)          CPU4 (A72)          CPU5 (A72)          CPU0 (A53)
采集线程             推理线程             跟踪线程             输出线程
  │                   │                   │                   │
  │ V4L2/文件读帧     │ NPU推理YOLOv5     │ SORT跟踪          │ MQTT上报
  │                   │ (rknn_run)        │ 卡尔曼+匈牙利     │ +视频编码
  ↓                   ↓                   ↓                   ↓
frame_queue ──→  detect_queue ──→   track_queue ──→    网络/本地
```

### 5.3 版本验证清单

部署新板子时，按此清单逐项验证：

```bash
# 1. USB NPU 设备可见
lsusb | grep 2207
# → ID 2207:180a Fuzhou Rockchip Electronics Company

# 2. npu_transfer_proxy 运行
systemctl status rknn-npu.service
# → Active: active (running)

# 3. API = DRV 版本匹配
/tmp/test_rknn_version
# → API: 1.7.5, DRV: 1.7.5

# 4. PERF flag 可用
# (test_rknn_version 已使用 RKNN_FLAG_COLLECT_PERF_MASK)

# 5. 推理正常
# 启动 edge-ai-camera 服务，检查日志有 "Model loaded successfully"
```

---

## 6. 故障排除

### 6.1 `NPUTransfer: Transfer interface open failed!`

**原因**：`npu_transfer_proxy` 未运行或 USB 设备不可访问。

```bash
sudo systemctl restart rknn-npu.service
lsusb | grep 2207  # 确认 USB 设备存在
```

### 6.2 `ACK_PERF_TOO_MANY_CLIENT`

**原因**：API/DRV 版本不匹配，或已有其他进程占用 NPU。

```bash
# 检查版本
strings /usr/lib/aarch64-linux-gnu/librknn_api.so | grep -E "^[0-9]+\.[0-9]+\.[0-9]+"
# → 应为 1.7.5

# 检查占用进程
ps aux | grep -E "edge-ai|rknn" | grep -v grep
killall edge-ai-camera  # 释放 NPU

# 如果版本不匹配，按第 3 节步骤替换组件
```

### 6.3 `rknn_init fail! ret=-3` (非 TOO_MANY_CLIENT)

**原因**：模型文件不存在或损坏。

```bash
ls -la /opt/edge-ai/models/yolov5n.rknn
# → 文件应存在，大小约 7.4MB
```

### 6.4 程序卡住无输出

**原因**：stdout 缓冲未 flush，或 MQTT broker 不可达导致阻塞。

```bash
# 1. 确认 MQTT broker 可达
mosquitto_sub -h 127.0.0.1 -t "edge/#" -V mqttv311

# 2. 检查 DNS 解析
ping debian10.local  # 如果不可达，改为 IP 地址
```

### 6.5 恢复原版系统组件

如果需要回退到系统包原版：

```bash
# 恢复 transfer proxy
sudo mv /usr/bin/npu_transfer_proxy.system_orig /usr/bin/npu_transfer_proxy

# 恢复固件
sudo rm -rf /usr/lib/firmware/npu_fw
sudo mv /usr/lib/firmware/npu_fw.system_orig /usr/lib/firmware/npu_fw

# 恢复库
sudo mv /usr/lib/aarch64-linux-gnu/librknn_api.so.system_orig /usr/lib/aarch64-linux-gnu/librknn_api.so

# 重启 NPU 服务
sudo systemctl restart rknn-npu.service
```

---

## 7. 参考链接

- [NPU_REFERENCE.md](NPU_REFERENCE.md) — NPU 硬件架构和 API 详细参考
- [EDGE_DEPLOY.md](EDGE_DEPLOY.md) — 边缘端部署指南
- [ARCHITECTURE.md](ARCHITECTURE.md) — 五层架构设计
- Rockchip RKNN-Toolkit: `https://github.com/rockchip-linux/rknn-toolkit`
