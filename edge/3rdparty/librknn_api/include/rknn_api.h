/* SPDX-License-Identifier: MIT */
/*
 * RKNN API Header — Rockchip NPU Runtime Library
 *
 * 从 Rockchip RKNN-Toolkit1 SDK 中提取: librknn_api/include/rknn_api.h
 * 项目路径: edge/3rdparty/librknn_api/aarch64/librknn_api.so
 *
 * 这是占位头文件，用于在 x86 PC 上做语法检查和静态分析。
 * 真实编译时替换为 Rockchip SDK 中的完整头文件。
 */

#ifndef RKNN_API_H
#define RKNN_API_H

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/* ── RKNN 上下文 ───────────────────────────────────────── */
typedef void* rknn_context;

/* ── Flags ──────────────────────────────────────────────── */
#define RKNN_FLAG_COLLECT_PERF_MASK   (1 << 0)
#define RKNN_FLAG_MEM_ALLOC_OUTSIDE   (1 << 1)

/* ── Tensor 格式 ───────────────────────────────────────── */
typedef enum {
    RKNN_TENSOR_NCHW = 0,
    RKNN_TENSOR_NHWC = 1,
    RKNN_TENSOR_NC1HWC2 = 2,
    RKNN_TENSOR_UNDEFINED = 3,
} rknn_tensor_format;

/* ── Tensor 数据类型 ────────────────────────────────────── */
typedef enum {
    RKNN_TENSOR_FLOAT32 = 0,
    RKNN_TENSOR_FLOAT16 = 1,
    RKNN_TENSOR_INT8 = 2,
    RKNN_TENSOR_UINT8 = 3,
    RKNN_TENSOR_INT16 = 4,
    RKNN_TENSOR_INT32 = 5,
    RKNN_TENSOR_INT64 = 6,
} rknn_tensor_type;

/* ── 量化类型 ───────────────────────────────────────────── */
typedef enum {
    RKNN_TENSOR_QNT_NONE = 0,
    RKNN_TENSOR_QNT_DFP = 1,
    RKNN_TENSOR_QNT_AFFINE_ASYMMETRIC = 2,
} rknn_tensor_qnt_type;

/* ── Query 命令 ─────────────────────────────────────────── */
typedef enum {
    RKNN_QUERY_IN_OUT_NUM = 0,
    RKNN_QUERY_INPUT_ATTR = 1,
    RKNN_QUERY_OUTPUT_ATTR = 2,
    RKNN_QUERY_SDK_VERSION = 3,
    RKNN_QUERY_MEM_SIZE = 4,
    RKNN_QUERY_CUSTOM_STRING = 5,
    RKNN_QUERY_NATIVE_INPUT_ATTR = 6,
    RKNN_QUERY_NATIVE_OUTPUT_ATTR = 7,
    RKNN_QUERY_NATIVE_NC1HWC2_INPUT_ATTR = 8,
    RKNN_QUERY_NATIVE_NC1HWC2_OUTPUT_ATTR = 9,
    RKNN_QUERY_DEVICE_MEM_INFO = 10,
    RKNN_QUERY_PERF_RUN = 11,
} rknn_query_cmd;

/* ── SDK 版本 ───────────────────────────────────────────── */
typedef struct {
    char api_version[32];
    char drv_version[32];
} rknn_sdk_version;

/* ── Tensor 属性 ────────────────────────────────────────── */
typedef struct {
    uint32_t index;                     /* tensor 序号 */
    uint32_t n_dims;                    /* 维度数 (通常 4) */
    uint32_t dims[4];                   /* [N, H, W, C] 或 [N, C, H, W] */
    uint32_t n_elems;                   /* 元素总数 */
    uint32_t size;                      /* 字节数 */
    char name[64];                      /* tensor 名称 */
    rknn_tensor_format fmt;             /* NCHW/NHWC */
    rknn_tensor_type type;              /* float32/int8/... */
    rknn_tensor_qnt_type qnt_type;      /* 量化方式 */
    int32_t fl;                         /* 量化小数位 */
    int32_t zp;                         /* 零点 */
    float scale;                        /* 缩放因子 */
    float w_scale;                      /* 权重量化缩放 */
} rknn_tensor_attr;

/* ── 输入 ───────────────────────────────────────────────── */
typedef struct {
    uint32_t index;
    void*    buf;
    uint32_t size;
    uint32_t pass_through;
    rknn_tensor_type type;
    rknn_tensor_format fmt;
} rknn_input;

/* ── 输出 ───────────────────────────────────────────────── */
typedef struct {
    uint8_t  want_float;
    uint8_t  is_prealloc;
    uint32_t index;
    void*    buf;
    uint32_t size;
} rknn_output;

/* ── 推理性能统计 ────────────────────────────────────────── */
typedef struct {
    uint64_t run_duration;              /* 推理耗时 (微秒) */
    uint64_t time_interval;             /* 总耗时 */
} rknn_perf_run;

/* ── API 函数 ────────────────────────────────────────────── */
int rknn_init(rknn_context* ctx, void* model, uint32_t size, uint32_t flag, void* opt);
int rknn_destroy(rknn_context ctx);
int rknn_query(rknn_context ctx, rknn_query_cmd cmd, void* info, uint32_t size);
int rknn_inputs_set(rknn_context ctx, uint32_t n_inputs, rknn_input inputs[]);
int rknn_run(rknn_context ctx, void* extend);
int rknn_outputs_get(rknn_context ctx, uint32_t n_outputs, rknn_output outputs[], void* extend);
int rknn_outputs_release(rknn_context ctx, uint32_t n_outputs, rknn_output outputs[]);

#ifdef __cplusplus
}
#endif

#endif /* RKNN_API_H */