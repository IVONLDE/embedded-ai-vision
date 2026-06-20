# RK3399Pro NPU 技术参考手册

## 1. NPU 硬件架构

### 1.1 概述

RK3399Pro 集成了一个专用神经网络处理单元（NPU），基于 Rockchip RK1808 NPU IP 核。该 NPU 与
CPU/GPU 分离，通过 AXI 总线与系统内存交互，支持 INT8/INT16/FP16 推理加速。

```
┌──────────────────────────────────────────────────────────────────┐
│                        RK3399Pro SoC                              │
│  ┌──────────────┐  ┌──────────────┐  ┌─────────────────────────┐ │
│  │  CPU Complex  │  │  Mali-T860   │  │  NPU (RK1808 IP Core)   │ │
│  │  2×A72 1.8G  │  │  GPU MP4     │  │                         │ │
│  │  4×A53 1.4G  │  │  600MHz      │  │  ┌───────────────────┐  │ │
│  │              │  │              │  │  │  Convolution       │  │ │
│  │  L1 32KB     │  │  L2 256KB    │  │  │  Accelerator      │  │ │
│  │  L2 1MB+512K │  │              │  │  │  1920 MACs/Cycle  │  │ │
│  └──────┬───────┘  └──────┬───────┘  │  │  (INT8)           │  │ │
│         │                  │          │  └───────────────────┘  │ │
│         └──────────────────┼──────────┤  ┌───────────────────┐  │ │
│                            │          │  │  Activation        │  │ │
│                   ┌────────┴────────┐ │  │  Engine (ReLU,     │  │ │
│                   │   Interconnect  │ │  │  LeakyReLU,        │  │ │
│                   │   (CCI-400)     │ │  │  Sigmoid, Tanh)    │  │ │
│                   └────────┬────────┘ │  └───────────────────┘  │ │
│                            │          │  ┌───────────────────┐  │ │
│                   ┌────────┴────────┐ │  │  Pooling           │  │ │
│                   │  DDR Controller │ │  │  Engine (MAX/AVG)  │  │ │
│                   │  (LPDDR4 2-4G)  │ │  └───────────────────┘  │ │
│                   └─────────────────┘ │                         │ │
│                                       │  Local SRAM: 256KB      │ │
│                                       │  Clock: 800MHz          │ │
│                                       └─────────────────────────┘ │
└──────────────────────────────────────────────────────────────────┘
```

### 1.2 技术规格

| 参数 | 规格 |
|------|------|
| **NPU 核心** | RK1808 IP Core |
| **INT8 峰值算力** | 3.0 TOPS |
| **INT16 峰值算力** | 1.5 TOPS |
| **FP16 峰值算力** | 0.75 TOPS |
| **MAC 单元数** | 1920 INT8 MACs/Cycle |
| **时钟频率** | 800MHz |
| **片上 SRAM** | 256KB (用于权重/特征图缓存) |
| **支持网络** | CNN, RNN, LSTM, GRU |
| **支持层类型** | Conv2D, DepthwiseConv, Deconv, FC, Pooling, Concat, Reshape, Slice, ElementWise, Softmax, BatchNorm, LRN, Pad, Upsample, Reorg |
| **支持量化** | INT8 对称/非对称量化, INT16 量化, FP16 |
| **驱动文件** | `/dev/rknpu` (misc 设备), `galcore.ko` 或 `rknpu.ko` (内核模块) |
| **用户空间运行时** | `librknn_api.so` (RKNN1 API, RK3399Pro 专用) |
| **功耗** | ~1.5W (满载), ~0.3W (空闲) |

### 1.3 与 RKNN2 API 的差异

| 特性 | RKNN1 (RK3399Pro) | RKNN2 (RK356x/RK3588) |
|------|-------------------|----------------------|
| **单核/多核** | 单核 NPU | 多核 NPU (rknn_set_core_mask) |
| **零拷贝** | 不支持 rknn_create_mem | 支持 (rknn_create_mem/rknn_set_io_mem) |
| **I/O 模式** | rknn_inputs_set/rknn_outputs_get (拷贝) | rknn_set_io_mem (零拷贝) |
| **模型格式** | RKNN v1 格式 | RKNN v2 格式 |
| **最大输入尺寸** | 8192×8192 | 取决于平台 |
| **INT8 算力** | 3.0 TOPS | 6.0 TOPS (RK3588 三核) |

---

## 2. RKNN API 函数参考 (RKNN-Toolkit1)

### 2.1 头文件

```c
#include "rknn_api.h"  /* 从 RKNN-Toolkit1 SDK 提取 */
```

### 2.2 数据结构

#### rknn_context
```c
typedef void* rknn_context;  /* NPU 推理上下文句柄 */
```

#### rknn_tensor_attr
```c
typedef struct {
    uint32_t index;              /* Tensor 序号 (0-based) */
    uint32_t n_dims;             /* 维度数 (通常 4: NCHW/NHWC) */
    uint32_t dims[4];            /* 具体维度值 [N, H, W, C] 或 [N, C, H, W] */
    uint32_t n_elems;            /* 元素总数 = dims[0]*dims[1]*dims[2]*dims[3] */
    uint32_t size;               /* 字节数 = n_elems * sizeof(type) */
    char     name[64];           /* Tensor 名称 (来自模型) */
    rknn_tensor_format fmt;       /* NCHW=0, NHWC=1, NC1HWC2=2 */
    rknn_tensor_type type;        /* FLOAT32=0, FLOAT16=1, INT8=2, UINT8=3, INT16=4, INT32=5, INT64=6 */
    rknn_tensor_qnt_type qnt_type; /* NONE=0, DFP=1, AFFINE_ASYMMETRIC=2 */
    int32_t  fl;                 /* 量化小数位 (INT8 量化) */
    int32_t  zp;                 /* 零点 (INT8 量化) */
    float    scale;              /* 缩放因子 (INT8 量化) */
    float    w_scale;            /* 权重量化缩放 */
} rknn_tensor_attr;
```

#### rknn_input
```c
typedef struct {
    uint32_t          index;        /* 输入序号 (通常 0) */
    void*             buf;          /* 输入数据缓冲区指针 */
    uint32_t          size;         /* 输入数据字节数 */
    uint32_t          pass_through; /* 直通模式 (跳过预处理, 通常置 0) */
    rknn_tensor_type  type;         /* 数据类型: UINT8/INT8/FLOAT32 */
    rknn_tensor_format fmt;         /* 内存布局: NHWC/NCHW */
} rknn_input;
```

#### rknn_output
```c
typedef struct {
    uint8_t  want_float;   /* 1=要求 float32 输出, 0=原始量化输出 */
    uint8_t  is_prealloc;  /* 1=使用预分配缓冲区, 0=RKNN 内部分配 */
    uint32_t index;        /* 输出序号 (0-based) */
    void*    buf;          /* 输出缓冲区指针 (is_prealloc=1 时有效) */
    uint32_t size;         /* 缓冲区大小 (is_prealloc=1 时有效) */
} rknn_output;
```

### 2.3 API 函数详解

#### rknn_init — 初始化 NPU 上下文
```c
int rknn_init(rknn_context* ctx, void* model, uint32_t size, uint32_t flag, void* opt);
```
- **ctx**: [out] 返回的推理上下文句柄
- **model**: [in] 模型文件数据 (完整 RKNN 模型二进制)
- **size**: [in] 模型数据字节数
- **flag**: [in] 初始化标志位:
  - `RKNN_FLAG_COLLECT_PERF_MASK (1<<0)` — 启用推理性能统计
  - `RKNN_FLAG_MEM_ALLOC_OUTSIDE (1<<1)` — 外部管理 NPU 内存 (高级用法)
- **opt**: [in] 扩展参数, 传 NULL
- **返回值**: 0 成功, <0 失败 (错误码)
- **注意**: RK3399Pro 上, 该函数会打开 `/dev/rknpu` 设备, 与内核 NPU 驱动交互

#### rknn_query — 查询上下文信息
```c
int rknn_query(rknn_context ctx, rknn_query_cmd cmd, void* info, uint32_t size);
```
- **cmd**: 查询命令:
  - `RKNN_QUERY_IN_OUT_NUM` — 查询输入/输出数量, info 为 `rknn_input_output_num*`
  - `RKNN_QUERY_INPUT_ATTR` — 查询输入属性, info 为 `rknn_tensor_attr*`
  - `RKNN_QUERY_OUTPUT_ATTR` — 查询输出属性, info 为 `rknn_tensor_attr*`
  - `RKNN_QUERY_SDK_VERSION` — 查询 SDK 版本, info 为 `rknn_sdk_version*`
  - `RKNN_QUERY_PERF_RUN` — 查询最近一次推理耗时, info 为 `rknn_perf_run*`

#### rknn_inputs_set — 设置输入数据
```c
int rknn_inputs_set(rknn_context ctx, uint32_t n_inputs, rknn_input inputs[]);
```
- 将输入数据拷贝到 NPU 内部缓冲区 (拷贝模式, RK3399Pro 不支持零拷贝)
- 调用后数据可以立即释放
- **注意**: YOLOv5 输入通常为 `[1, 640, 640, 3] NHWC UINT8`

#### rknn_run — 触发 NPU 推理
```c
int rknn_run(rknn_context ctx, void* extend);
```
- 阻塞执行, 直到 NPU 推理完成
- **extend**: 扩展参数, 传 NULL
- **返回值**: 0 成功, <0 失败

#### rknn_outputs_get — 获取推理输出
```c
int rknn_outputs_get(rknn_context ctx, uint32_t n_outputs, rknn_output outputs[], void* extend);
```
- 获取 NPU 推理结果的指针
- **want_float=1** 时, 即使模型是 INT8 量化, 输出也会转为 float32
- **调用后必须在数据处理完毕后调用 rknn_outputs_release 释放**

#### rknn_outputs_release — 释放输出缓冲区
```c
int rknn_outputs_release(rknn_context ctx, uint32_t n_outputs, rknn_output outputs[]);
```
- **必须在 rknn_outputs_get 之后调用**, 否则会内存泄漏
- outputs[].buf 中的指针变为悬空指针, 不应再访问

#### rknn_destroy — 销毁上下文
```c
int rknn_destroy(rknn_context ctx);
```
- 释放 NPU 资源, 关闭 `/dev/rknpu`

### 2.4 典型推理流程

```
┌──────────────┐
│ rknn_init()  │  加载模型, 初始化 NPU
├──────────────┤
│ rknn_query() │  查询 I/O 属性 (尺寸、类型、格式)
├──────────────┤
│  循环开始     │
│  ┌─────────────────────────┐
│  │ 预处理: 图像缩放+格式转换  │
│  │ rknn_inputs_set()       │  设置输入数据 (拷贝)
│  │ rknn_run()              │  触发 NPU 推理 (阻塞)
│  │ rknn_outputs_get()      │  获取输出指针
│  │ 后处理: 解码+NMS         │  在 CPU 上执行
│  │ rknn_outputs_release()  │  释放输出
│  └─────────────────────────┘
│  循环结束     │
├──────────────┤
│ rknn_destroy()│ 释放 NPU 资源
└──────────────┘
```

---

## 3. NPU 内核驱动

### 3.1 设备节点

RK3399Pro NPU 通过 misc 设备暴露给用户空间:

```bash
/dev/rknpu          # NPU 设备节点
/dev/galcore        # GPU/NPU 通用设备 (GAL 驱动, 某些内核版本)
```

### 3.2 驱动架构

```
┌─────────────────────────────────────────────────────┐
│  用户空间                                            │
│  ┌──────────────┐  ┌───────────────────────────────┐ │
│  │ librknn_api  │  │ 应用程序                       │ │
│  │ (RKNN1 C API)│  │ (edge-ai-camera)              │ │
│  └──────┬───────┘  └───────────────┬───────────────┘ │
│         │ ioctl()                  │                  │
├─────────┼──────────────────────────┼──────────────────┤
│  内核空间│                          │                  │
│  ┌──────┴──────────────────────────┴───────────────┐ │
│  │  rknpu.ko / galcore.ko                          │ │
│  │  (Rockchip NPU 内核驱动)                         │ │
│  │  ┌──────────────────────────────────────────┐   │ │
│  │  │  NPU 电源管理 (clk/gate/pd)               │   │ │
│  │  │  NPU 内存管理 (DMA/iommu)                 │   │ │
│  │  │  命令队列 (cmdqueue)                      │   │ │
│  │  │  中断处理 (推理完成中断)                   │   │ │
│  │  └──────────────────────────────────────────┘   │ │
│  └──────────────────┬──────────────────────────────┘ │
│                     │                                │
│  ┌──────────────────┴──────────────────────────────┐ │
│  │  RK3399Pro 硬件                                 │ │
│  │  ┌────────────────────────────────────────┐     │ │
│  │  │  NPU Core (RK1808 IP)                  │     │ │
│  │  │  - 1920 MAC Units                      │     │ │
│  │  │  - 256KB SRAM                          │     │ │
│  │  │  - Convolution Accelerator             │     │ │
│  │  │  - Activation Engine                   │     │ │
│  │  │  - Pooling Engine                      │     │ │
│  │  └────────────────────────────────────────┘     │ │
│  └─────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────┘
```

### 3.3 设备树配置

NPU 在 RK3399Pro 设备树中的典型配置:

```dts
rknpu: npu@ffbc0000 {
    compatible = "rockchip,rk3399pro-npu";
    reg = <0x0 0xffbc0000 0x0 0x10000>;
    interrupts = <GIC_SPI 43 IRQ_TYPE_LEVEL_HIGH>;
    clocks = <&cru ACLK_NPU>, <&cru HCLK_NPU>, <&cru SCLK_NPU>;
    clock-names = "aclk_npu", "hclk_npu", "sclk_npu";
    assigned-clocks = <&cru SCLK_NPU>;
    assigned-clock-rates = <800000000>;  /* 800MHz */
    power-domains = <&power RK3399Pro_PD_NPU>;
    memory-region = <&npu_reserved>;      /* CMA 512MB */
    status = "okay";
};

/* NPU CMA 内存保留 (512MB, 用于推理缓冲区) */
npu_reserved: npu-mem@40000000 {
    reg = <0x0 0x40000000 0x0 0x20000000>;   /* 512MB @ 0x40000000 */
    no-map;
};
```

### 3.4 NPU 电源管理

RK3399Pro NPU 通过 Power Domain 控制开关:

| Power Domain | 寄存器基址 | 控制组件 |
|-------------|-----------|---------|
| `RK3399Pro_PD_NPU` | `0xff310000` | NPU Core + SRAM |
| SCLK_NPU | CRU | NPU 工作时钟 (200-800MHz) |

空闲时 NPU 可以完全断电 (Power Gate)，推理前由 `rknn_init()` 自动唤醒。

### 3.5 中断

NPU 完成一次推理后会触发中断，RKNN API 的 `rknn_run()` 内部等待该中断。中断号:

| 中断 | GIC SPI | 说明 |
|------|---------|------|
| `npu_irq` | SPI 43 | 推理完成中断 (level-high 触发) |