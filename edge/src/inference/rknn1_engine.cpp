/* SPDX-License-Identifier: MIT */
/*
 * RKNN1 NPU Inference Engine for RK3399Pro
 *
 * 基于 RKNN-Toolkit1 API (librknn_api.so) 的推理引擎封装。
 * 替代原有的 rknn_fp.cpp (RKNN2 API)。
 *
 * API 差异 (RKNN2 → RKNN1):
 *   - 无 rknn_set_core_mask (RK3399Pro 单核 NPU)
 *   - 无 rknn_create_mem / rknn_set_io_mem (零拷贝)
 *   - 使用 rknn_inputs_set / rknn_outputs_get (拷贝模式)
 *   - rknn_init 使用 RKNN_FLAG_COLLECT_PERF_MASK
 *
 * 功能:
 *   - 模型加载与初始化
 *   - NPU 推理 (uint8 输入, float32 输出)
 *   - 性能统计 (推理耗时滑动窗口)
 *   - 模型热加载 (运行时切换模型, 不中断服务)
 *   - CPU 亲和性绑定
 */

#include "rknn1_engine.h"

#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <fstream>
#include <iostream>
#include <pthread.h>
#include <unistd.h>

/* ── 构造: 加载模型 + 初始化 NPU ──────────────────────── */
Rknn1Engine::Rknn1Engine(const char *model_path, int cpu_id)
{
    int ret;

    _cpu_id = cpu_id;
    _model_path = model_path;
    _ctx = 0;
    _model_loaded = false;

    /* CPU 亲和性绑定 */
    cpu_set_t mask;
    CPU_ZERO(&mask);
    CPU_SET(cpu_id, &mask);

    if (pthread_setaffinity_np(pthread_self(), sizeof(mask), &mask) < 0)
        std::cerr << "[RKNN1] set thread affinity failed" << std::endl;
    else
        printf("[RKNN1] Bind NPU process on CPU %d\n", cpu_id);

    /* 加载模型 */
    ret = load_model(model_path);
    if (ret != 0) {
        std::cerr << "[RKNN1] Failed to load model: " << model_path
                  << std::endl;
        throw std::runtime_error("Failed to load RKNN model");
    }
}

/* ── 析构: 释放 NPU 资源 ───────────────────────────────── */
Rknn1Engine::~Rknn1Engine()
{
    if (_ctx) {
        rknn_destroy(_ctx);
        _ctx = 0;
    }
    printf("[RKNN1] Engine destroyed\n");
}

/* ── 加载 RKNN 模型 ────────────────────────────────────── */
int Rknn1Engine::load_model(const char *model_path)
{
    int ret;

    printf("[RKNN1] Loading model: %s\n", model_path);

    /* 读取模型文件 */
    FILE *fp = fopen(model_path, "rb");
    if (!fp) {
        fprintf(stderr, "[RKNN1] fopen %s fail!\n", model_path);
        return -1;
    }

    fseek(fp, 0, SEEK_END);
    long model_len = ftell(fp);
    if (model_len <= 0) {
        fprintf(stderr, "[RKNN1] Invalid model file size: %ld\n", model_len);
        fclose(fp);
        return -1;
    }

    void *model_data = malloc(model_len);
    if (!model_data) {
        fprintf(stderr, "[RKNN1] malloc failed for %ld bytes\n", model_len);
        fclose(fp);
        return -1;
    }

    fseek(fp, 0, SEEK_SET);
    size_t read_len = fread(model_data, 1, model_len, fp);
    fclose(fp);

    if (read_len != (size_t)model_len) {
        fprintf(stderr, "[RKNN1] fread incomplete: got %zu/%ld\n",
                read_len, model_len);
        free(model_data);
        return -1;
    }

    /* 如果已有模型加载, 先释放旧模型 */
    if (_ctx) {
        rknn_destroy(_ctx);
        _ctx = 0;
    }

    /* RKNN1 API: rknn_init
     * 使用 RKNN_FLAG_COLLECT_PERF_MASK 开启性能统计 */
    ret = rknn_init(&_ctx, model_data, model_len,
                    RKNN_FLAG_COLLECT_PERF_MASK, NULL);
    free(model_data);

    if (ret < 0) {
        fprintf(stderr, "[RKNN1] rknn_init fail! ret=%d\n", ret);
        return -1;
    }

    /* 查询 SDK 版本 */
    rknn_sdk_version version;
    ret = rknn_query(_ctx, RKNN_QUERY_SDK_VERSION, &version,
                     sizeof(rknn_sdk_version));
    if (ret >= 0) {
        printf("[RKNN1] SDK: api=%s, driver=%s\n",
               version.api_version, version.drv_version);
    }

    /* 查询输入属性 */
    memset(_input_attrs, 0, sizeof(_input_attrs));
    _input_attrs[0].index = 0;
    ret = rknn_query(_ctx, RKNN_QUERY_INPUT_ATTR,
                     &_input_attrs[0], sizeof(rknn_tensor_attr));
    if (ret < 0) {
        fprintf(stderr, "[RKNN1] query input attr fail! ret=%d\n", ret);
        rknn_destroy(_ctx);
        _ctx = 0;
        return -1;
    }

    dump_tensor_attr(&_input_attrs[0]);

    /* 查询输出属性 (YOLOv5 有3个输出层) */
    memset(_output_attrs, 0, sizeof(_output_attrs));
    for (int i = 0; i < _n_output; i++) {
        _output_attrs[i].index = i;
        ret = rknn_query(_ctx, RKNN_QUERY_OUTPUT_ATTR,
                         &_output_attrs[i], sizeof(rknn_tensor_attr));
        if (ret < 0) {
            fprintf(stderr, "[RKNN1] query output %d attr fail! ret=%d\n",
                    i, ret);
            rknn_destroy(_ctx);
            _ctx = 0;
            return -1;
        }
        dump_tensor_attr(&_output_attrs[i]);
    }

    _model_loaded = true;
    printf("[RKNN1] Model loaded successfully\n");
    return 0;
}

/* ── 模型热加载 (运行时切换) ───────────────────────────── */
/*
 * hot_reload_model — 运行时加载新模型, 不中断推理服务
 *
 * 流程:
 *   1. 加载新模型到临时 context
 *   2. 验证新模型输入/输出兼容性
 *   3. 查询新模型输出属性
 *   4. 原子替换 _ctx + _output_attrs + _n_output
 *   5. 释放旧 context
 *
 * 注意: 调用时需确保没有正在进行的推理!
 */
int Rknn1Engine::hot_reload_model(const char *new_model_path)
{
    rknn_context new_ctx = 0;
    int ret;

    printf("[RKNN1] Hot-reloading model: %s\n", new_model_path);

    /* 读取新模型 */
    FILE *fp = fopen(new_model_path, "rb");
    if (!fp) {
        fprintf(stderr, "[RKNN1] fopen %s fail!\n", new_model_path);
        return -1;
    }

    fseek(fp, 0, SEEK_END);
    long model_len = ftell(fp);
    if (model_len <= 0) {
        fprintf(stderr, "[RKNN1] Invalid model file size: %ld\n", model_len);
        fclose(fp);
        return -1;
    }

    void *model_data = malloc(model_len);
    if (!model_data) {
        fprintf(stderr, "[RKNN1] malloc failed for %ld bytes\n", model_len);
        fclose(fp);
        return -1;
    }

    fseek(fp, 0, SEEK_SET);
    size_t read_len = fread(model_data, 1, model_len, fp);
    fclose(fp);

    if (read_len != (size_t)model_len) {
        fprintf(stderr, "[RKNN1] fread incomplete: got %zu/%ld\n",
                read_len, model_len);
        free(model_data);
        return -1;
    }

    /* 初始化新 context */
    ret = rknn_init(&new_ctx, model_data, model_len,
                    RKNN_FLAG_COLLECT_PERF_MASK, NULL);
    free(model_data);

    if (ret < 0) {
        fprintf(stderr, "[RKNN1] hot-reload init fail! ret=%d\n", ret);
        return -1;
    }

    /* 验证输入兼容性 */
    rknn_tensor_attr new_input_attrs;
    memset(&new_input_attrs, 0, sizeof(new_input_attrs));
    new_input_attrs.index = 0;
    ret = rknn_query(new_ctx, RKNN_QUERY_INPUT_ATTR,
                     &new_input_attrs, sizeof(rknn_tensor_attr));
    if (ret < 0) {
        fprintf(stderr, "[RKNN1] hot-reload query input fail!\n");
        rknn_destroy(new_ctx);
        return -1;
    }

    /* 检查输入尺寸是否兼容 */
    if (new_input_attrs.dims[1] != _input_attrs[0].dims[1] ||
        new_input_attrs.dims[2] != _input_attrs[0].dims[2] ||
        new_input_attrs.dims[3] != _input_attrs[0].dims[3]) {
        fprintf(stderr,
                "[RKNN1] hot-reload: input size mismatch! "
                "old=%dx%dx%d new=%dx%dx%d\n",
                _input_attrs[0].dims[1], _input_attrs[0].dims[2],
                _input_attrs[0].dims[3],
                new_input_attrs.dims[1], new_input_attrs.dims[2],
                new_input_attrs.dims[3]);
        rknn_destroy(new_ctx);
        return -1;
    }

    /* 先查询新模型输出层数 (修复: 不同模型 n_output 可能不同) */
    rknn_tensor_attr temp_output_attr;
    memset(&temp_output_attr, 0, sizeof(temp_output_attr));
    temp_output_attr.index = 0;
    ret = rknn_query(new_ctx, RKNN_QUERY_OUTPUT_ATTR,
                     &temp_output_attr, sizeof(rknn_tensor_attr));
    if (ret < 0) {
        fprintf(stderr, "[RKNN1] hot-reload query output fail!\n");
        rknn_destroy(new_ctx);
        return -1;
    }

    /* 查询所有输出层属性 */
    int new_n_output = 1;
    rknn_tensor_attr new_output_attrs[RKNN_MAX_OUTPUTS];
    memset(new_output_attrs, 0, sizeof(new_output_attrs));
    /* 从索引1继续查询, 直到查询失败 (说明没有更多输出层) */
    for (int idx = 1; idx < RKNN_MAX_OUTPUTS; idx++) {
        rknn_tensor_attr probe;
        memset(&probe, 0, sizeof(probe));
        probe.index = idx;
        if (rknn_query(new_ctx, RKNN_QUERY_OUTPUT_ATTR,
                       &probe, sizeof(rknn_tensor_attr)) < 0)
            break;
        new_n_output = idx + 1;
    }

    /* 重新查询所有输出层 (按正确数量) */
    for (int i = 0; i < new_n_output && i < RKNN_MAX_OUTPUTS; i++) {
        new_output_attrs[i].index = i;
        ret = rknn_query(new_ctx, RKNN_QUERY_OUTPUT_ATTR,
                         &new_output_attrs[i], sizeof(rknn_tensor_attr));
        if (ret < 0) {
            fprintf(stderr, "[RKNN1] hot-reload query output %d fail!\n", i);
            rknn_destroy(new_ctx);
            return -1;
        }
    }

    /* 原子替换 */
    rknn_context old_ctx = _ctx;
    _ctx = new_ctx;
    _model_path = new_model_path;

    /* 更新输入/输出属性 + 输出层数 */
    memcpy(&_input_attrs[0], &new_input_attrs, sizeof(rknn_tensor_attr));
    memcpy(_output_attrs, new_output_attrs, sizeof(new_output_attrs));
    _n_output = new_n_output;

    /* 清除旧输出缓存 (新模型输出尺寸可能不同) */
    for (int i = 0; i < RKNN_MAX_OUTPUTS; i++) {
        _output_buffs[i] = nullptr;
        _output_copies[i].clear();
    }

    /* 释放旧 context */
    rknn_destroy(old_ctx);

    printf("[RKNN1] Hot-reload complete (n_output=%d)\n", _n_output);
    return 0;
}

/* ── NPU 推理 ──────────────────────────────────────────── */
/*
 * inference — 执行一次 NPU 推理
 *
 * 输入: input_data (uint8, NHWC 格式, 尺寸 = W×H×C)
 * 输出: _output_buffs[0..2] (float32, 由调用方读取)
 * 返回: 推理耗时 (微秒), -1 表示失败
 *
 * RKNN1 流程:
 *   1. rknn_inputs_set  — 设置输入 (拷贝模式)
 *   2. rknn_run          — 触发 NPU 推理
 *   3. rknn_outputs_get  — 获取输出
 *   4. 复制输出到本地缓存 (防止悬空指针)
 *   5. rknn_outputs_release — 释放输出
 */
int Rknn1Engine::inference(unsigned char *input_data)
{
    int ret;

    if (!_model_loaded || !_ctx) {
        fprintf(stderr, "[RKNN1] Model not loaded!\n");
        return -1;
    }

    /* ── 设置输入 ── */
    rknn_input inputs[1];
    memset(inputs, 0, sizeof(inputs));

    int input_size = _input_attrs[0].dims[1] *
                     _input_attrs[0].dims[2] *
                     _input_attrs[0].dims[3];

    inputs[0].index = 0;
    inputs[0].type = RKNN_TENSOR_UINT8;
    inputs[0].size = input_size;
    inputs[0].fmt = RKNN_TENSOR_NHWC;
    inputs[0].buf = input_data;

    ret = rknn_inputs_set(_ctx, 1, inputs);
    if (ret < 0) {
        fprintf(stderr, "[RKNN1] rknn_inputs_set fail! ret=%d\n", ret);
        return -1;
    }

    /* ── 触发推理 ── */
    ret = rknn_run(_ctx, NULL);
    if (ret < 0) {
        fprintf(stderr, "[RKNN1] rknn_run fail! ret=%d\n", ret);
        return -1;
    }

    /* ── 获取输出 ── */
    rknn_output outputs[3];
    memset(outputs, 0, sizeof(outputs));

    for (int i = 0; i < _n_output; i++) {
        outputs[i].index = i;
        outputs[i].want_float = 1;  /* 要求 float32 输出 */
    }

    ret = rknn_outputs_get(_ctx, _n_output, outputs, NULL);
    if (ret < 0) {
        fprintf(stderr, "[RKNN1] rknn_outputs_get fail! ret=%d\n", ret);
        return -1;
    }

    /* 保存输出指针 */
    for (int i = 0; i < _n_output; i++) {
        _output_buffs[i] = (float *)outputs[i].buf;
    }

    /* 复制输出数据到本地缓存 (避免 rknn_outputs_release 后悬空指针) */
    copy_outputs_to_buffer();

    /* ── 查询推理耗时 ── */
    rknn_perf_run perf_run;
    ret = rknn_query(_ctx, RKNN_QUERY_PERF_RUN,
                     &perf_run, sizeof(perf_run));

    /* 释放输出 (RKNN1 必须手动释放) */
    rknn_outputs_release(_ctx, _n_output, outputs);

    if (ret >= 0)
        return perf_run.run_duration;  /* 微秒 */

    return 0;  /* 查询失败但推理成功 */
}

/*
 * copy_outputs_to_buffer — 将 RKNN 输出复制到本地缓存
 *
 * 必须在 rknn_outputs_release 之前调用！
 * 保证后处理阶段不会访问已释放的内存。
 */
void Rknn1Engine::copy_outputs_to_buffer()
{
    for (int i = 0; i < _n_output; i++) {
        if (!_output_buffs[i])
            continue;
        int n_elems = _output_attrs[i].n_elems;
        _output_copies[i].resize(n_elems);
        memcpy(_output_copies[i].data(), _output_buffs[i],
               n_elems * sizeof(float));
        _output_buffs[i] = _output_copies[i].data();  /* 指向本地副本 */
    }
}

/* ── 性能统计 ──────────────────────────────────────────── */
/*
 * cal_performance — 滑动窗口平均推理耗时
 *
 * 维护最近 10 次推理耗时, 计算平均值。
 * 用于监控 NPU 性能变化 (温度/频率影响)。
 */
float Rknn1Engine::cal_performance(std::queue<float> &history,
                                   float &sum, float cost_ms)
{
    if (history.size() < 10) {
        history.push(cost_ms);
        sum += cost_ms;
    } else {
        /* 队列已满, 替换最旧的数据 */
        sum -= history.front();
        sum += cost_ms;
        history.pop();
        history.push(cost_ms);
    }
    return sum / history.size();
}

/* ── 调试: 打印 tensor 属性 ────────────────────────────── */
void Rknn1Engine::dump_tensor_attr(rknn_tensor_attr *attr)
{
    printf("  index=%d, name=%s, n_dims=%d, dims=[%d,%d,%d,%d], "
           "n_elems=%d, size=%d, fmt=%s, type=%s, qnt_type=%s, "
           "zp=%d, scale=%f\n",
           attr->index, attr->name, attr->n_dims,
           attr->dims[0], attr->dims[1], attr->dims[2], attr->dims[3],
           attr->n_elems, attr->size,
           get_format_string(attr->fmt),
           get_type_string(attr->type),
           get_qnt_type_string(attr->qnt_type),
           attr->zp, attr->scale);
}

/* ── 辅助: 格式/类型字符串 ─────────────────────────────── */
const char *Rknn1Engine::get_format_string(rknn_tensor_format fmt)
{
    switch (fmt) {
    case RKNN_TENSOR_NCHW: return "NCHW";
    case RKNN_TENSOR_NHWC: return "NHWC";
    case RKNN_TENSOR_NC1HWC2: return "NC1HWC2";
    case RKNN_TENSOR_UNDEFINED: return "UNDEFINED";
    default: return "UNKNOWN";
    }
}

const char *Rknn1Engine::get_type_string(rknn_tensor_type type)
{
    switch (type) {
    case RKNN_TENSOR_FLOAT32: return "FP32";
    case RKNN_TENSOR_FLOAT16: return "FP16";
    case RKNN_TENSOR_INT8: return "INT8";
    case RKNN_TENSOR_UINT8: return "UINT8";
    case RKNN_TENSOR_INT16: return "INT16";
    default: return "UNKNOWN";
    }
}

const char *Rknn1Engine::get_qnt_type_string(rknn_tensor_qnt_type qnt)
{
    switch (qnt) {
    case RKNN_TENSOR_QNT_NONE: return "NONE";
    case RKNN_TENSOR_QNT_DFP: return "DFP";
    case RKNN_TENSOR_QNT_AFFINE_ASYMMETRIC: return "AFFINE";
    default: return "UNKNOWN";
    }
}