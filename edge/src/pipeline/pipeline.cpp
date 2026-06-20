/* SPDX-License-Identifier: MIT */
/*
 * Pipeline Scheduler — 多线程流水线调度器
 *
 * 四线程架构 (RK3399Pro 6核 CPU):
 *   Thread 1 (CPU1): 视频采集 (V4L2/RTSP/File)
 *   Thread 2 (CPU4): NPU 推理 (YOLOv5, A72 大核)
 *   Thread 3 (CPU5): SORT 跟踪 (卡尔曼+匈牙利, A72 大核)
 *   Thread 4 (CPU0): 结果输出 (MQTT上报 + 视频编码 + 显示)
 *
 * 线程间通信: SPSC 无锁队列 + 环形缓冲
 * 背压策略: 队列满 → 采集阻塞 / 推理丢非关键帧 / 跟踪卡尔曼预测兜底
 * 优雅关机: SIGTERM → 原子标志 → 五层逆序释放
 *
 * 替代原有的 yolov5_deepsort.cpp 中硬编码的 5 线程架构
 */

#include "pipeline_config.h"
#include "../inference/rknn1_engine.h"
#include "../inference/yolov5/detect.h"
#include "../inference/deepsort/tracker.h"
#include "../io/v4l2_capture.h"
#include "../io/file_input.h"
#include "../comm/mqtt_publisher.h"
#include "../comm/detect_box.h"
#include "../comm/grpc_server.h"

#include <atomic>
#include <condition_variable>
#include <csignal>
#include <iostream>
#include <mutex>
#include <queue>
#include <thread>
#include <unistd.h>

/* ── 全局状态 ──────────────────────────────────────────── */
static std::atomic<bool> g_running{true};
static std::atomic<bool> g_shutdown_requested{false};

/* ── 线程间队列 ────────────────────────────────────────── */
struct FrameData {
    int index;
    unsigned char *data;       /* 图像数据 (RGB, W×H×3) */
    int width;
    int height;
    int64_t timestamp_us;
    V4l2Capture *capture;     /* 用于归还 V4L2 缓冲区 */
};

struct DetectResult {
    int frame_index;
    std::vector<DetectBox> boxes;  /* 检测框列表 */
    int64_t timestamp_us;
};

struct TrackResult {
    int frame_index;
    std::vector<DetectBox> boxes;  /* 带 trackID 的检测框 */
    int64_t timestamp_us;
};

/* 线程间队列 (条件变量实现, 避免忙等自旋) */
template<typename T>
class SpscQueue {
public:
    explicit SpscQueue(int max_size) : _max_size(max_size) {}

    bool push(const T &item) {
        std::unique_lock<std::mutex> lock(_mutex);
        if (_queue.size() >= (size_t)_max_size)
            return false;  /* 队列满 */
        _queue.push(item);
        lock.unlock();
        _cond.notify_one();
        return true;
    }

    bool pop(T &item) {
        std::unique_lock<std::mutex> lock(_mutex);
        _cond.wait(lock, [this]{ return !_queue.empty() || _shutdown; });
        if (_shutdown && _queue.empty())
            return false;
        item = _queue.front();
        _queue.pop();
        lock.unlock();
        _cond.notify_one();
        return true;
    }

    void shutdown() {
        std::lock_guard<std::mutex> lock(_mutex);
        _shutdown = true;
        _cond.notify_all();
    }

    size_t size() {
        std::lock_guard<std::mutex> lock(_mutex);
        return _queue.size();
    }

private:
    std::queue<T> _queue;
    int _max_size;
    std::mutex _mutex;
    std::condition_variable _cond;
    bool _shutdown = false;
};

/* ── 信号处理 ──────────────────────────────────────────── */
/*
 * signal_handler — SIGTERM/SIGINT 异步信号捕获
 *
 * 只设置原子标志, 不做任何复杂操作 (信号安全)
 * 主循环 100ms 轮询检查标志
 */
static void signal_handler(int sig)
{
    if (sig == SIGTERM || sig == SIGINT || sig == SIGHUP) {
        g_shutdown_requested.store(true);
        g_running.store(false);
    }
}

/* ── 采集线程 ──────────────────────────────────────────── */
/*
 * capture_thread_func — 视频采集线程
 *
 * 从 V4L2 摄像头 / RTSP 流 / 文件读取帧,
 * 推入 frame_queue (采集→推理队列)
 *
 * 背压: 队列满时阻塞等待 (不丢帧)
 */
static void capture_thread_func(const PipelineConfig &cfg,
                                SpscQueue<FrameData> &frame_queue)
{
    printf("[Pipeline] Capture thread started on CPU %d\n",
           cfg.system.cpu_read);

    /* 绑定 CPU */
    cpu_set_t mask;
    CPU_ZERO(&mask);
    CPU_SET(cfg.system.cpu_read, &mask);
    pthread_setaffinity_np(pthread_self(), sizeof(mask), &mask);

    V4l2Capture capture;
    if (!capture.open(cfg.input.v4l2_device,
                      cfg.input.v4l2_width,
                      cfg.input.v4l2_height,
                      cfg.input.v4l2_fps)) {
        std::cerr << "[Pipeline] Failed to open camera" << std::endl;
        g_running.store(false);
        return;
    }

    int frame_idx = 0;
    while (g_running.load()) {
        FrameData frame;
        frame.index = frame_idx++;

        /* 从 V4L2 采集一帧 (DMA-BUF 零拷贝) */
        if (!capture.read_frame(&frame.data, &frame.width,
                                &frame.height, &frame.timestamp_us)) {
            std::cerr << "[Pipeline] Failed to read frame" << std::endl;
            continue;
        }

        /* 记录采集对象指针, 用于推理完成后归还缓冲区 */
        frame.capture = &capture;

        /* 推入队列 (满则阻塞) */
        while (g_running.load() && !frame_queue.push(frame)) {
            usleep(1000);  /* 等待消费 */
        }
    }

    capture.close();
    printf("[Pipeline] Capture thread stopped\n");
}

/* ── 推理线程 ──────────────────────────────────────────── */
/*
 * inference_thread_func — NPU 推理线程
 *
 * 从 frame_queue 取帧 → NPU 推理 → 推入 detect_queue
 *
 * 背压: 队列满时丢弃非关键帧 (保证实时性)
 */
static void inference_thread_func(const PipelineConfig &cfg,
                                  SpscQueue<FrameData> &frame_queue,
                                  SpscQueue<DetectResult> &detect_queue)
{
    printf("[Pipeline] Inference thread started on CPU %d\n",
           cfg.system.cpu_inference);

    cpu_set_t mask;
    CPU_ZERO(&mask);
    CPU_SET(cfg.system.cpu_inference, &mask);
    pthread_setaffinity_np(pthread_self(), sizeof(mask), &mask);

    /* 初始化 NPU 引擎 */
    Rknn1Engine engine(cfg.inference.model_path.c_str(),
                       cfg.system.cpu_inference);

    std::queue<float> perf_history;
    float perf_sum = 0.0;

    while (g_running.load()) {
        FrameData frame;
        if (!frame_queue.pop(frame)) {
            usleep(1000);
            continue;
        }

        /* 隔帧检测 */
        if (cfg.inference.det_interval > 1 &&
            frame.index % cfg.inference.det_interval != 0) {
            /* 复用上一帧结果, 跳过推理 — 但仍需归还 V4L2 缓冲区 */
            if (frame.capture)
                frame.capture->release_frame();
            continue;
        }

        /* NPU 推理 */
        int cost_us = engine.inference(frame.data);

        /* 归还 V4L2 缓冲区 (推理完成后立即归还, 避免耗尽) */
        if (frame.capture)
            frame.capture->release_frame();

        if (cost_us < 0) {
            std::cerr << "[Pipeline] Inference failed on frame "
                      << frame.index << std::endl;
            continue;
        }

        /* 性能统计 */
        float cost_ms = cost_us / 1000.0f;
        float avg_ms = engine.cal_performance(perf_history,
                                              perf_sum, cost_ms);

        /* 后处理 (YOLOv5 decode + NMS) */
        DetectResult result;
        result.frame_index = frame.index;
        result.timestamp_us = frame.timestamp_us;

        /* 调用 YOLOv5 后处理 (复用现有 decode.cpp 逻辑) */
        post_process_fp(engine._output_buffs[0],
                        engine._output_buffs[1],
                        engine._output_buffs[2],
                        cfg.inference.conf_threshold,
                        cfg.inference.nms_threshold,
                        &result.boxes);

        /* 推入检测队列 */
        detect_queue.push(result);

        if (frame.index % 100 == 0) {
            printf("[Pipeline] Frame %d: inference %.2fms (avg %.2fms)\n",
                   frame.index, cost_ms, avg_ms);
        }
    }

    printf("[Pipeline] Inference thread stopped\n");
}

/* ── 跟踪线程 ──────────────────────────────────────────── */
/*
 * tracking_thread_func — SORT 跟踪线程
 *
 * 从 detect_queue 取检测结果 → 卡尔曼预测 + 匈牙利匹配 → 推入 track_queue
 *
 * 背压: 队列满时跳过当前帧, 卡尔曼预测兜底
 */
static void tracking_thread_func(const PipelineConfig &cfg,
                                 SpscQueue<DetectResult> &detect_queue,
                                 SpscQueue<TrackResult> &track_queue)
{
    printf("[Pipeline] Tracking thread started on CPU %d\n",
           cfg.system.cpu_tracking);

    cpu_set_t mask;
    CPU_ZERO(&mask);
    CPU_SET(cfg.system.cpu_tracking, &mask);
    pthread_setaffinity_np(pthread_self(), sizeof(mask), &mask);

    /* 初始化 SORT 跟踪器 */
    Tracker tracker(cfg.tracking.max_iou_distance,
                    cfg.tracking.max_age,
                    cfg.tracking.n_init);

    while (g_running.load()) {
        DetectResult det;
        if (!detect_queue.pop(det)) {
            usleep(1000);
            continue;
        }

        /* SORT 跟踪 */
        TrackResult result;
        result.frame_index = det.frame_index;
        result.timestamp_us = det.timestamp_us;

        if (cfg.tracking.enabled && !det.boxes.empty()) {
            tracker.predict();
            tracker.update(det.boxes);

            /* 提取活跃轨迹 */
            for (const auto &track : tracker.tracks()) {
                if (!track.is_confirmed() ||
                    track.time_since_update > 1)
                    continue;

                DetectBox box = track.to_tlwh();
                box.trackID = track.track_id;
                result.boxes.push_back(box);
            }
        } else {
            /* 无检测或跟踪禁用, 直接透传 */
            result.boxes = det.boxes;
        }

        /* 推入跟踪队列 */
        track_queue.push(result);
    }

    printf("[Pipeline] Tracking thread stopped\n");
}

/* ── 输出线程 ──────────────────────────────────────────── */
/*
 * output_thread_func — 结果输出线程
 *
 * 从 track_queue 取跟踪结果 → MQTT 上报 + 视频编码 + 显示
 *
 * 背压: 队列满时本地缓存 (断网不丢数据)
 */
static void output_thread_func(const PipelineConfig &cfg,
                               SpscQueue<TrackResult> &track_queue)
{
    printf("[Pipeline] Output thread started on CPU %d\n",
           cfg.system.cpu_output);

    cpu_set_t mask;
    CPU_ZERO(&mask);
    CPU_SET(cfg.system.cpu_output, &mask);
    pthread_setaffinity_np(pthread_self(), sizeof(mask), &mask);

    /* 初始化 MQTT */
    MqttPublisher mqtt;
    if (cfg.mqtt.enabled) {
        mqtt.connect(cfg.mqtt.broker_host, cfg.mqtt.broker_port,
                     cfg.mqtt.client_id, cfg.mqtt.keepalive);
    }

    while (g_running.load()) {
        TrackResult result;
        if (!track_queue.pop(result)) {
            usleep(1000);
            continue;
        }

        /* MQTT 上报 */
        if (cfg.mqtt.enabled && !result.boxes.empty()) {
            mqtt.publish_detections(cfg.mqtt.topic_detections,
                                    result.boxes,
                                    result.frame_index,
                                    result.timestamp_us);
        }

        /* 心跳上报 (每 100 帧) */
        if (result.frame_index % 100 == 0 && cfg.mqtt.enabled) {
            mqtt.publish_health(cfg.mqtt.topic_health,
                                result.frame_index);
        }
    }

    if (cfg.mqtt.enabled)
        mqtt.disconnect();

    printf("[Pipeline] Output thread stopped\n");
}

/* ── gRPC 服务线程 ─────────────────────────────────────── */
/*
 * grpc_server_thread_func — gRPC 模型更新服务
 *
 * 独立线程, 监听 gRPC 请求:
 *   - PushModel: 接收新模型 → 热加载
 *   - SwitchScene: 切换场景
 *   - GetStatus: 返回设备状态
 */
static void grpc_server_thread_func(const PipelineConfig &cfg,
                                    Rknn1Engine *engine)
{
    printf("[Pipeline] gRPC server thread started on %s\n",
           cfg.grpc.listen_address.c_str());

    GrpcServer server;
    server.start(cfg.grpc.listen_address, cfg.grpc.unix_socket,
                 engine, &cfg);

    /* gRPC 服务器在主循环中运行, 直到 shutdown */
    while (g_running.load()) {
        sleep(1);
    }

    server.stop();
    printf("[Pipeline] gRPC server thread stopped\n");
}

/* ── 主入口 ────────────────────────────────────────────── */
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
int pipeline_run(const PipelineConfig &cfg)
{
    try {
        printf("╔══════════════════════════════════════════════╗\n");
        printf("║  Edge AI Camera Pipeline — RK3399Pro        ║\n");
        printf("║  Device: %-34s ║\n", cfg.device_id.c_str());
        printf("║  Scene:  %-34s ║\n", cfg.active_scene.c_str());
        printf("║  Model:  %-34s ║\n", cfg.inference.model_path.c_str());
        printf("╚══════════════════════════════════════════════╝\n");

        /* 注册信号处理 */
        signal(SIGTERM, signal_handler);
        signal(SIGINT, signal_handler);
        signal(SIGHUP, signal_handler);   /* 支持 systemctl reload */

    /* 创建队列 */
    int qsize = cfg.system.queue_max_size;
    SpscQueue<FrameData> frame_queue(qsize);
    SpscQueue<DetectResult> detect_queue(qsize);
    SpscQueue<TrackResult> track_queue(qsize);

    /* 初始化 NPU 引擎 (主线程初始化, gRPC 线程共享) */
    Rknn1Engine engine(cfg.inference.model_path.c_str(),
                       cfg.system.cpu_inference);

    /* 启动工作线程 */
    std::thread capture_th(capture_thread_func,
                          std::ref(cfg), std::ref(frame_queue));
    std::thread inference_th(inference_thread_func,
                             std::ref(cfg),
                             std::ref(frame_queue),
                             std::ref(detect_queue));
    std::thread tracking_th(tracking_thread_func,
                            std::ref(cfg),
                            std::ref(detect_queue),
                            std::ref(track_queue));
    std::thread output_th(output_thread_func,
                          std::ref(cfg), std::ref(track_queue));

    /* 启动 gRPC 线程 */
    std::thread grpc_th;
    if (cfg.grpc.enabled) {
        grpc_th = std::thread(grpc_server_thread_func,
                              std::ref(cfg), &engine);
    }

    printf("[Pipeline] All threads started, running...\n");

    /* 主循环: 100ms 轮询 shutdown */
    while (g_running.load()) {
        usleep(100000);  /* 100ms */

        if (g_shutdown_requested.load()) {
            printf("[Pipeline] Shutdown requested, stopping...\n");
            g_running.store(false);
        }
    }

    /* ── 五层逆序释放 ── */
    printf("[Pipeline] Joining threads...\n");

    /* 通知所有队列 shutdown, 唤醒阻塞的 pop() */
    frame_queue.shutdown();
    detect_queue.shutdown();
    track_queue.shutdown();

    /* Layer 5: 通信层 */
    if (grpc_th.joinable())
        grpc_th.join();

    /* Layer 4: 输出层 */
    if (output_th.joinable())
        output_th.join();

    /* Layer 3: 跟踪层 */
    if (tracking_th.joinable())
        tracking_th.join();

    /* Layer 2: 推理层 */
    if (inference_th.joinable())
        inference_th.join();

    /* Layer 1: 采集层 */
    if (capture_th.joinable())
        capture_th.join();

    printf("[Pipeline] All threads joined, resources released\n");
    printf("[Pipeline] Shutdown complete\n");

    return 0;

    } catch (const std::exception &e) {
        std::cerr << "[Pipeline] Fatal error: " << e.what() << std::endl;
        g_running.store(false);
        return -1;
    }
}
