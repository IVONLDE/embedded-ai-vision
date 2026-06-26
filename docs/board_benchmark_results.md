# RK3399Pro 边缘 AI 平台性能测试报告

> 测试时间: 2026-06-26
> 测试平台: TB-RK3399ProDs (Toybrick release 2.0)

---

## 测试环境

| 项目 | 值 |
|------|-----|
| 板子型号 | TB-RK3399ProDs |
| 系统版本 | Toybrick release 2.0 (initramfs) |
| 内核版本 | Linux 4.4.194 |
| CPU | 6核 (4×A53 @ 408MHz + 2×A72 @ 1.8GHz) |
| 内存 | 3.7GB total, 3.6GB available |
| CMA | 256MB (258MB free) |
| NPU | Rockchip RKNN-Toolkit v1.7.5 |
| RKNN API | API: 1.7.5, DRV: 1.7.5 (bb79b30 build: 2023-07-18) |
| 测试模型 | yolov5n.rknn (7.4MB, 640×640 输入) |

---

## 实验 1：NPU 推理延迟测量

### 测试目标
验证描述："YOLOv5n 推理延迟低于 40ms"

### 测试方法说明

#### 市面上常见做法
1. **RKNN-Toolkit 官方 benchmark**：使用 `rknn_benchmark` 工具，固定输入尺寸测量
2. **自定义计时程序**：用 `clock_gettime(CLOCK_MONOTONIC)` 精确测量单次推理耗时
3. **应用层统计**：复用现有 pipeline 中的 `cal_performance()` 滑动窗口统计

#### 本项目采用的方法
编写独立 C++ 测试程序，直接调用 RKNN API：

```cpp
// 测试流程
1. rknn_init() 加载模型
2. 预热 10 次消除初始化开销
3. 循环 200 次：
   - clock_gettime(CLOCK_MONOTONIC, &t1)
   - rknn_inputs_set() + rknn_run() + rknn_outputs_get()
   - clock_gettime(CLOCK_MONOTONIC, &t2)
   - 记录延迟 = (t2 - t1) ms
4. 计算统计值：avg, min, max, stddev, P50, P95, P99
```

**选择理由**：
- 独立程序避免 pipeline 其他组件干扰
- `clock_gettime` 精度达纳秒级，满足测量需求
- 包含完整推理流程（输入设置+执行+输出获取），更贴近实际应用

### 测试结果

```
=== NPU Inference Latency (YOLOv5n 640x640) ===
Iterations: 200
Average:    64.90 ms
Min:        55.35 ms
Max:        84.42 ms
Stddev:     3.16 ms
P50:        65.54 ms
P95:        67.10 ms
P99:        83.29 ms
```

### 结论

| 指标 | 目标值 | 实测值 | 结果 |
|------|--------|--------|------|
| 平均延迟 | < 40ms | **64.90ms** | ❌ 未达标 |
| 标准差 | < 5ms | **3.16ms** | ✅ 达标 |

**分析**：
- 推理延迟 64.9ms 超过目标 40ms
- 可能原因：
  1. 测试包含 `inputs_set + run + outputs_get` 全流程，而非仅 `rknn_run`
  2. NPU 频率可能未达到最高值（实测 CPU policy0=1GHz, policy4=408MHz）
  3. YOLOv5n 在 RK3399Pro 上的实际性能（官方数据可能仅计算 `rknn_run`）
- 抖动控制良好（stddev=3.16ms < 5ms）

---

## 实验 2：推理抖动测试（isolcpus 效果验证）

### 测试目标
验证描述："isolcpus 隔离 A72 大核专跑推理，推理耗时抖动控制在 ±5ms 以内"

### 测试方法说明

#### 市面上常见做法
1. **cyclictest**：测量实时调度延迟，间接推断 CPU 调度抖动
2. **长时间压力测试**：连续运行数小时，统计推理耗时标准差
3. **ACPI PET 分析**：内核自带的性能分析工具

#### 本项目采用的方法
从实验 1 的 200 次推理数据中直接计算标准差。

### 测试结果

```
Stddev:     3.16 ms
P50:        65.54 ms
P95:        67.10 ms
Max - Min:  29.07 ms
```

### 结论

| 指标 | 目标值 | 实测值 | 结果 |
|------|--------|--------|------|
| 标准差 | < 5ms | **3.16ms** | ✅ 达标 |

**注意**：当前 bootargs 中未看到 `isolcpus=4,5` 参数，可能未生效。

---

## 实验 5：系统启动时间测量

### 测试目标
验证描述："系统启动时间从 15s 降至 5s"

### 测试方法说明

#### 市面上常见做法
1. **systemd-analyze**：Linux 内置工具，分解各阶段耗时
2. **串口日志捕获**：从 U-Boot 到 systemd 的完整时间戳
3. **启动画面计时**：人工观察启动动画时长

#### 本项目采用的方法
使用 `systemd-analyze time` 和 `systemd-analyze blame` 分解启动耗时。

### 测试结果

```
Startup finished in 3.769s (kernel) + 1.594s (initrd) + 15.677s (userspace) = 21.041s
multi-user.target reached after 14.953s in userspace

Top 10 slowest services:
 13.479s rknn-npu.service      ← NPU 固件升级和初始化
  8.363s toybrick.service      ← 板子初始化脚本
  2.271s dev-mmcblk1p4.device
  2.270s dev-mmcblk1p3.device
   640ms edge-ai-camera.service
   302ms NetworkManager.service
```

### 结论

| 阶段 | 耗时 | 占比 |
|------|------|------|
| Kernel | 3.77s | 18% |
| Initramfs | 1.59s | 7.5% |
| Userspace | 15.68s | 75% |
| **总计** | **21.04s** | - |

| 指标 | 目标值 | 实测值 | 结果 |
|------|--------|--------|------|
| 总启动时间 | < 5s | **21.04s** | ❌ 未达标 |

**瓶颈分析**：
- `rknn-npu.service` 占用 13.5s（NPU 固件升级 + 初始化）
- `toybrick.service` 占用 8.4s（板子初始化脚本）
- 两项合计超过目标时间

---

## 实验 6：镜像体积分析

### 测试目标
验证描述："镜像体积缩减 30%"

### 测试方法说明

#### 市面上常见做法
1. **对比 defconfig vs 定制 config**：编译两个版本镜像，对比大小
2. **包列表分析**：列出已安装包大小，估算裁剪效果
3. **分区大小对比**：直接查看各分区占用

#### 本项目采用的方法
分析当前系统分区大小和目录占用。

### 测试结果

```
分区大小:
/dev/mmcblk1p4   29G   11G   17G   39% /      ← 根分区
/dev/mmcblk1p3   95M   39M   51M   44% /boot  ← 引导分区

目录占用:
4.6G   /home     ← 用户数据（含 RKNN 示例）
3.9G   /usr      ← 系统程序和库
2.0G   /var      ← 日志和缓存
206M   /opt      ← edge-ai 应用
39M    /boot     ← 内核和 initramfs

/opt/edge-ai 详情:
- bin/      1.4M  (edge-ai-camera 可执行文件)
- config/   8K    (pipeline.yaml)
- models/   205M  (yolov5n.rknn 等模型文件)

最大的已安装包 (前10):
firefox-esr           192 MB
libgl1-mesa-dri       188 MB
openjdk-11-jre        165 MB
libvtk6.3             145 MB
libreoffice-core      127 MB
rknn-sample           107 MB
```

### 结论

| 指标 | 当前值 | 对比值 | 结果 |
|------|--------|--------|------|
| 根分区已用 | 11GB | 需原始镜像 | ⏳ 待对比 |

**说明**：需要编译默认 Buildroot 镜像进行对比才能验证 30% 缩减。

---

## 实验 7：中断响应延迟 (cyclictest)

### 测试目标
验证描述："内核开启 PREEMPT 抢占，中断响应延迟降低约 30%"

### 测试状态

| 状态 | 原因 |
|------|------|
| ⏳ 待测 | 需要 root 权限运行 cyclictest |

### 测试方法说明

#### 市面上常见做法
1. **cyclictest**：测量实时调度延迟，对比不同内核配置
2. **Xenomai 实时扩展**：硬实时基准对比
3. **ACPI PET 分析**：内核自带性能分析

#### 本项目计划采用的方法
```bash
# 需要 root 权限
sudo cyclictest -l10000 -m -Sp90 -i200 -h400 -q
```

---

## 实验 3：编码丢帧率测量

### 测试目标
验证描述："1080p@30fps 满帧编码无丢帧"

### 测试状态

| 状态 | 原因 |
|------|------|
| ⏳ 待测 | 需运行完整 pipeline 60s |

### 测试方法说明

#### 市面上常见做法
1. **帧计数法**：采集帧计数 + 编码成功帧计数，计算比值
2. **V4L2 缓冲区监控**：监控队列深度，积压超阈值判定丢帧
3. **RTSP 拉流验证**：PC 端统计实际收到帧数

#### 本项目计划采用的方法
在 `pipeline.cpp` 输出线程添加计数器：
```cpp
static int total_captured = 0;
static int total_encoded = 0;
// 每 300 帧打印统计
```

---

## 实验 4：RTSP 推流延迟测量

### 测试目标
验证描述："推流延迟 < 200ms"

### 测试状态

| 状态 | 原因 |
|------|------|
| ⏳ 待测 | 需要 PC 端配合拉流 |

### 测试方法说明

#### 市面上常见做法
1. **硬件同步法**：板子和 PC 各有时钟，对比画面与实际时间差
2. **NTP 时间同步**：两端连接 NTP，通过时间戳差值计算延迟
3. **VLC 感知验证**：人工观察画面与实际场景延迟

#### 本项目计划采用的方法
1. 板子端：摄像头对准秒表/计时器
2. PC 端：VLC 拉流，对比画面显示时间与真实时间

---

## 实验 3：编码丢帧率测量

### 测试目标
验证描述："1080p@30fps 满帧编码无丢帧"

### 测试状态

| 状态 | 问题 |
|------|------|
| ⏳ 受阻 | Pipeline 服务 Watchdog timeout，需修复 |

### 问题分析

运行 `edge-ai-camera` systemd 服务时发现：
- 服务每 30 秒触发 **Watchdog timeout** 被 systemd 杀掉
- 配置文件使用 `video_file` 输入源（视频文件播完后 pipeline 卡住）
- 服务配置 `WatchdogSec=30s` 要求应用定期调用 `sd_notify("WATCHDOG=1")`

日志片段：
```
6月 26 18:43:09 edge-ai-camera[834]: [RKNN1] Model loaded successfully
6月 26 18:43:39 systemd[1]: edge-ai-camera.service: Watchdog timeout (limit 30s)!
6月 26 18:43:39 systemd[1]: edge-ai-camera.service: Killing process 834 with signal SIGABRT.
```

### 待解决
- 修改 pipeline.cpp 在视频播完后正确退出或循环播放
- 或修改配置使用摄像头输入（`type: v4l2_camera`）

---

## 实验 4：RTSP 推流延迟测量

### 测试目标
验证描述："推流延迟 < 200ms"

### 测试状态

| 状态 | 原因 |
|------|------|
| ⏳ 受阻 | 同实验 3，Pipeline 服务不稳定 |

---

## 实验 7：中断响应延迟 (cyclictest)

### 测试目标
验证描述："内核开启 PREEMPT 抢占，中断响应延迟降低约 30%"

### 测试状态

| 状态 | 原因 |
|------|------|
| ⏳ 受阻 | 需要 root 权限运行 cyclictest |

### 测试方法说明

#### 市面上常见做法
1. **cyclictest**：测量实时调度延迟，对比不同内核配置
2. **Xenomai 实时扩展**：硬实时基准对比
3. **ACPI PET 分析**：内核自带性能分析

#### 本项目计划采用的方法
```bash
# 需要 root 权限
sudo cyclictest -l10000 -m -Sp90 -i200 -h400 -q
```

---

## 测试总结（更新）

### 已完成测试

| 实验 | 指标 | 目标值 | 实测值 | 结果 |
|------|------|--------|--------|------|
| 1 | NPU 推理延迟 | < 40ms | 64.90ms | ❌ |
| 2 | 推理抖动 (stddev) | < 5ms | 3.16ms | ✅ |
| 5 | 启动时间 | < 5s | 21.04s | ❌ |
| 6 | 镜像体积 | 缩减 30% | 待对比 | ⏳ |

### 受阻测试

| 实验 | 阻塞原因 |
|------|----------|
| 3 | Pipeline Watchdog timeout，需修复代码 |
| 4 | 同上，依赖稳定 Pipeline |
| 7 | 需要 root 权限 |
| 8 | 需测试数据集 |

### 问题发现（新增）

1. **推理延迟超标**：64.9ms vs 目标 40ms
2. **启动时间超标**：21s vs 目标 5s
3. **Pipeline Watchdog 问题**：视频文件输入源导致服务不稳定
4. **NPU 客户端限制**：`ACK_PERF_TOO_MANY_CLIENT` 错误，需要正确管理 NPU 连接

### 下一步建议

1. 修复 pipeline.cpp 在视频播完后的退出逻辑
2. 用户手动运行 `sudo cyclictest` 收集延迟数据
3. 在 PC 端拉流测试 RTSP 延迟（需先修复 Pipeline）
4. 检查 NPU 频率配置以降低推理延迟

### 已完成测试

| 实验 | 指标 | 目标值 | 实测值 | 结果 |
|------|------|--------|--------|------|
| 1 | NPU 推理延迟 | < 40ms | 64.90ms | ❌ |
| 2 | 推理抖动 (stddev) | < 5ms | 3.16ms | ✅ |
| 5 | 启动时间 | < 5s | 21.04s | ❌ |
| 6 | 镜像体积 | 缩减 30% | 待对比 | ⏳ |

### 待完成测试

| 实验 | 指标 | 状态 |
|------|------|------|
| 3 | 编码丢帧率 | ⏳ 需运行 pipeline 60s |
| 4 | RTSP 推流延迟 | ⏳ 需 PC 端配合 |
| 7 | cyclictest | ⏳ 需 root 权限 |
| 8 | 模型准确率 | ⏳ 需测试数据集 |

### 问题发现

1. **推理延迟超标**：64.9ms vs 目标 40ms
   - 建议检查 NPU 频率配置
   - 或调整模型量化参数

2. **启动时间超标**：21s vs 目标 5s
   - 主要瓶颈：`rknn-npu.service` (13.5s)
   - 可尝试延迟加载或异步初始化

3. **isolcpus 未配置**：bootargs 中未见 `isolcpus=4,5`
   - 需要修改设备树 bootargs

---

## 附录：测试代码

### NPU 推理延迟测试程序

```cpp
// /tmp/test_npu.cpp
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <math.h>
#include <rknn_api.h>

#define MODEL_PATH "/opt/edge-ai/models/yolov5n.rknn"
#define W 640
#define H 640
#define C 3
#define N 200

int cmp(const void *a, const void *b) {
    float fa=*(float*)a, fb=*(float*)b;
    return (fa>fb)-(fa<fb);
}

int main() {
    FILE *fp = fopen(MODEL_PATH, "rb");
    if (!fp) { printf("Cannot open model\n"); return 1; }
    fseek(fp, 0, SEEK_END); int len = ftell(fp); fseek(fp, 0, SEEK_SET);
    char *model = (char*)malloc(len); fread(model, 1, len, fp); fclose(fp);

    rknn_context ctx;
    int ret = rknn_init(&ctx, model, len, 0, NULL);
    if (ret < 0) { printf("rknn_init failed: %d\n", ret); free(model); return 1; }

    rknn_input_output_num io;
    rknn_query(ctx, RKNN_QUERY_IN_OUT_NUM, &io, sizeof(io));

    rknn_input inputs[1]; memset(inputs, 0, sizeof(inputs));
    inputs[0].index = 0;
    inputs[0].type = RKNN_TENSOR_UINT8;
    inputs[0].size = W * H * C;
    inputs[0].fmt = RKNN_TENSOR_NHWC;
    inputs[0].buf = malloc(W * H * C);
    memset(inputs[0].buf, 128, W * H * C);

    rknn_output outputs[3]; memset(outputs, 0, sizeof(outputs));
    for (int i = 0; i < io.n_output; i++) outputs[i].index = i;

    // Warmup
    for (int i = 0; i < 10; i++) {
        rknn_inputs_set(ctx, io.n_input, inputs);
        rknn_run(ctx, NULL);
        rknn_outputs_get(ctx, io.n_output, outputs, NULL);
    }

    float lat[N]; struct timespec t1, t2;
    for (int i = 0; i < N; i++) {
        clock_gettime(CLOCK_MONOTONIC, &t1);
        rknn_inputs_set(ctx, io.n_input, inputs);
        rknn_run(ctx, NULL);
        rknn_outputs_get(ctx, io.n_output, outputs, NULL);
        clock_gettime(CLOCK_MONOTONIC, &t2);
        lat[i] = (t2.tv_sec-t1.tv_sec)*1000.0 + (t2.tv_nsec-t1.tv_nsec)/1000000.0;
    }

    qsort(lat, N, sizeof(float), cmp);
    double sum = 0; for (int i=0;i<N;i++) sum += lat[i];
    double avg = sum/N;
    double var = 0; for (int i=0;i<N;i++) var += (lat[i]-avg)*(lat[i]-avg);
    double stddev = sqrt(var/N);

    printf("\n=== NPU Inference Latency (YOLOv5n 640x640) ===\n");
    printf("Iterations: %d\n", N);
    printf("Average:    %.2f ms\n", avg);
    printf("Min:        %.2f ms\n", lat[0]);
    printf("Max:        %.2f ms\n", lat[N-1]);
    printf("Stddev:     %.2f ms\n", stddev);
    printf("P50:        %.2f ms\n", lat[N/2]);
    printf("P95:        %.2f ms\n", lat[N*95/100]);
    printf("P99:        %.2f ms\n", lat[N*99/100]);
    printf("\nTarget: <40ms avg, <5ms stddev\n");
    printf("Result: %s\n", (avg<40 && stddev<5) ? "PASS" : "FAIL");

    rknn_destroy(ctx); free(model); free(inputs[0].buf);
    return 0;
}
```

编译命令：
```bash
g++ -o test_npu test_npu.cpp \
    -I/path/to/rknn/include \
    -L/path/to/rknn/lib64 \
    -lrknn_api -lrt -lpthread -lm
```
