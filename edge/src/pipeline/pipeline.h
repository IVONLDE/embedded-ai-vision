/* SPDX-License-Identifier: MIT */
/*
 * Pipeline Scheduler — 多线程流水线调度器 (Header)
 *
 * 四线程架构 (RK3399Pro 6核 CPU):
 *   Thread 1 (CPU1): 视频采集 (V4L2/RTSP/File)
 *   Thread 2 (CPU4): NPU 推理 (YOLOv5, A72 大核)
 *   Thread 3 (CPU5): SORT 跟踪 (卡尔曼+匈牙利, A72 大核)
 *   Thread 4 (CPU0): 结果输出 (MQTT上报 + 视频编码 + 显示)
 */

#ifndef PIPELINE_H
#define PIPELINE_H

#include "pipeline_config.h"

/*
 * pipeline_run — 启动四线程流水线
 *
 * 流程:
 *   1. 注册信号处理 (SIGTERM/SIGINT)
 *   2. 创建线程间队列
 *   3. 启动 4 个工作线程 + 1 个 gRPC 线程
 *   4. 主线程 100ms 轮询 shutdown 标志
 *   5. 收到 shutdown → 原子标志 → join 所有线程
 *   6. 五层逆序释放资源
 */
int pipeline_run(const PipelineConfig &cfg);

#endif /* PIPELINE_H */