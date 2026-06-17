/* SPDX-License-Identifier: MIT */
/*
 * RKNN1 NPU Inference Engine — Header
 *
 * RK3399Pro 单核 NPU (RK1808) 推理引擎封装
 * 基于 RKNN-Toolkit1 API (librknn_api.so)
 */

#ifndef RKNN1_ENGINE_H
#define RKNN1_ENGINE_H

#include "rknn_api.h"
#include <queue>
#include <string>
#include <vector>
#include <stdexcept>

class Rknn1Engine {
public:
    /*
     * 构造函数
     * @param model_path  RKNN 模型文件路径
     * @param cpu_id      绑定的 CPU 核心 (A72: 4/5, A53: 0-3)
     */
    Rknn1Engine(const char *model_path, int cpu_id);

    ~Rknn1Engine();

    /*
     * inference — 执行一次 NPU 推理
     * @param input_data  uint8 输入数据 (NHWC, W×H×C)
     * @return 推理耗时 (微秒), -1 失败
     *
     * 输出通过 _output_buffs[0..2] 获取 (float32)
     */
    int inference(unsigned char *input_data);

    /*
     * hot_reload_model — 运行时热加载新模型
     * @param new_model_path  新模型路径
     * @return 0 成功, -1 失败
     *
     * 原子替换 context, 不中断推理服务
     */
    int hot_reload_model(const char *new_model_path);

    /*
     * cal_performance — 滑动窗口平均推理耗时
     * @param history  最近N次耗时队列
     * @param sum      队列总和
     * @param cost_ms  本次耗时 (ms)
     * @return 平均耗时 (ms)
     */
    float cal_performance(std::queue<float> &history,
                          float &sum, float cost_ms);

    /* 调试 */
    void dump_tensor_attr(rknn_tensor_attr *attr);

    /* 公共成员 */
    int _cpu_id;
    int _n_input = 1;
    int _n_output = 3;  /* YOLOv5 3个输出层 */

    rknn_context _ctx;
    rknn_tensor_attr _input_attrs[1];
    rknn_tensor_attr _output_attrs[3];
    float *_output_buffs[3];  /* 推理输出指针 (每次推理后更新) */

    /* 输出缓冲区副本 (解决悬空指针: rknn_outputs_release 后数据仍可用) */
    std::vector<float> _output_copies[3];
    void copy_outputs_to_buffer();

    std::string _model_path;
    bool _model_loaded;

private:
    int load_model(const char *model_path);

    static const char *get_format_string(rknn_tensor_format fmt);
    static const char *get_type_string(rknn_tensor_type type);
    static const char *get_qnt_type_string(rknn_tensor_qnt_type qnt);
};

#endif /* RKNN1_ENGINE_H */
