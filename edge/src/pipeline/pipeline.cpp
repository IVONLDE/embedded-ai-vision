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
#include "../io/video_encoder.h"
#include "../io/rtsp_server.h"
#include "../comm/mqtt_publisher.h"
#include "../comm/detect_box.h"
#include "../comm/grpc_server.h"
#include "../comm/ota_manager.h"

#include <atomic>
#include <condition_variable>
#include <csignal>
#include <cstring>
#include <ctime>
#include <fcntl.h>
#include <iostream>
#include <mutex>
#include <queue>
#include <thread>
#include <unistd.h>
#include <new>

#ifdef HAVE_LIBSYSTEMD
#include <systemd/sd-daemon.h>
#else
/* fallback: sd_notify 空实现 (无 systemd 环境编译兼容) */
static inline int sd_notify(int unset_environment, const char *state) {
    (void)unset_environment; (void)state;
    return 0;
}
#endif

/* ── 全局状态 ──────────────────────────────────────────── */
static std::atomic<bool> g_running{true};
static std::atomic<bool> g_shutdown_requested{false};
static GrpcServer *g_grpc_server = nullptr;  /* 用于 MQTT 命令转发 */

/* 远程控制标志 (PC 端通过 MQTT 命令设置) */
static std::atomic<bool> g_recording_requested{false};
static std::atomic<bool> g_rtsp_requested{false};

/* ── 线程健康监控 ──────────────────────────────────────── */
/*
 * 每个工作线程定期更新心跳时间戳 (原子操作, 无锁)
 * 主循环每 100ms 检查所有线程心跳, 超时 (5s) 则判定线程异常
 * 异常时触发优雅关机, 避免管线半死不活
 */
enum class ThreadRole {
    CAPTURE,    /* 采集线程 */
    INFERENCE,  /* 推理线程 */
    TRACKING,   /* 跟踪线程 */
    OUTPUT,     /* 输出线程 */
    GRPC,       /* gRPC 线程 */
    _COUNT
};

static constexpr int THREAD_WATCHDOG_TIMEOUT_MS = 5000;  /* 5秒无心跳 → 异常 */
static constexpr int THREAD_WATCHDOG_CHECK_MS   = 100;   /* 100ms 检查间隔 */

static std::atomic<int64_t> g_thread_heartbeats[static_cast<int>(ThreadRole::_COUNT)];
static const char *g_thread_names[] = {"Capture", "Inference", "Tracking", "Output", "gRPC"};

static void thread_heartbeat(ThreadRole role) {
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    g_thread_heartbeats[static_cast<int>(role)].store(
        ts.tv_sec * 1000LL + ts.tv_nsec / 1000000LL,
        std::memory_order_release);
}

static int64_t get_time_ms() {
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return ts.tv_sec * 1000LL + ts.tv_nsec / 1000000LL;
}

/*
 * check_thread_health — 检查所有线程心跳
 * 返回: 0 = 全部正常, >0 = 异常线程数
 * 异常线程名打印到 stderr
 */
static int check_thread_health() {
    int64_t now = get_time_ms();
    int dead = 0;
    for (int i = 0; i < static_cast<int>(ThreadRole::_COUNT); i++) {
        int64_t last = g_thread_heartbeats[i].load(std::memory_order_acquire);
        /* 未初始化的线程跳过 (如 gRPC 未启用时) */
        if (last == 0) continue;
        if (now - last > THREAD_WATCHDOG_TIMEOUT_MS) {
            fprintf(stderr, "[Watchdog] Thread %s dead! (last heartbeat %lldms ago)\n",
                    g_thread_names[i], (long long)(now - last));
            dead++;
        }
    }
    return dead;
}

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

    /* 原始帧数据 (从 FrameData 复制), 传递给跟踪线程
     * unique_ptr 自动管理生命周期，任何路径退出均无泄漏 */
    std::unique_ptr<unsigned char[]> frame_data;
    int frame_width = 0;
    int frame_height = 0;
};

struct TrackResult {
    int frame_index;
    std::vector<DetectBox> boxes;  /* 带 trackID 的检测框 */
    int64_t timestamp_us;

    /* 原始帧数据 (RGB24, W×H×3), 用于视频编码和 RTSP 推流
     * unique_ptr 自动管理生命周期，nullptr 表示无图像数据 */
    std::unique_ptr<unsigned char[]> frame_data;
    int frame_width = 0;
    int frame_height = 0;
};

/* 线程安全队列 (mutex + condition_variable, 支持阻塞等待与优雅 shutdown) */
template<typename T>
class ThreadSafeQueue {
public:
    explicit ThreadSafeQueue(int max_size) : _max_size(max_size) {}

    bool push(const T &item) {
        std::unique_lock<std::mutex> lock(_mutex);
        if (_queue.size() >= (size_t)_max_size)
            return false;  /* 队列满 */
        _queue.push(item);
        lock.unlock();
        _cond.notify_one();
        return true;
    }

    void push_or_wait(const T &item) {
        std::unique_lock<std::mutex> lock(_mutex);
        _not_full.wait(lock, [this]{ return _queue.size() < (size_t)_max_size || _shutdown; });
        if (_shutdown) return;
        _queue.push(item);
        lock.unlock();
        _cond.notify_one();
    }

    bool pop(T &item) {
        std::unique_lock<std::mutex> lock(_mutex);
        _cond.wait(lock, [this]{ return !_queue.empty() || _shutdown; });
        if (_shutdown && _queue.empty())
            return false;
        item = _queue.front();
        _queue.pop();
        lock.unlock();
        _not_full.notify_one();
        return true;
    }

    void shutdown() {
        std::lock_guard<std::mutex> lock(_mutex);
        _shutdown = true;
        _cond.notify_all();
        _not_full.notify_all();
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
    std::condition_variable _not_full;  /* 队列满时生产者等待 */
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
                                ThreadSafeQueue<FrameData> &frame_queue)
{
    printf("[Pipeline] Capture thread started on CPU %d, input type=%d\n",
           cfg.system.cpu_read, (int)cfg.input.type);

    cpu_set_t mask;
    CPU_ZERO(&mask);
    CPU_SET(cfg.system.cpu_read, &mask);
    pthread_setaffinity_np(pthread_self(), sizeof(mask), &mask);

    int frame_idx = 0;

    if (cfg.input.type == InputType::V4L2_CAMERA) {
        V4l2Capture capture;
        if (!capture.open(cfg.input.v4l2_device,
                          cfg.input.v4l2_width,
                          cfg.input.v4l2_height,
                          cfg.input.v4l2_fps)) {
            std::cerr << "[Pipeline] Failed to open camera" << std::endl;
            g_running.store(false);
            return;
        }
        while (g_running.load()) {
            thread_heartbeat(ThreadRole::CAPTURE);
            FrameData frame;
            frame.index = frame_idx++;
            if (!capture.read_frame(&frame.data, &frame.width,
                                    &frame.height, &frame.timestamp_us)) {
                std::cerr << "[Pipeline] Failed to read frame" << std::endl;
                continue;
            }
            frame.capture = &capture;
            frame_queue.push_or_wait(frame);
        }
        capture.close();
    } else {
        FileInput file_input;
        const char *source_path = (cfg.input.type == InputType::RTSP_STREAM)
            ? cfg.input.rtsp_url.c_str()
            : cfg.input.file_path.c_str();
        if (!file_input.open(source_path)) {
            std::cerr << "[Pipeline] Failed to open input: " << source_path << std::endl;
            g_running.store(false);
            return;
        }
        while (g_running.load()) {
            thread_heartbeat(ThreadRole::CAPTURE);
            FrameData frame;
            frame.index = frame_idx++;
            frame.capture = nullptr;
            frame.data = nullptr;
            if (!file_input.read_frame(&frame.data, &frame.width,
                                       &frame.height, &frame.timestamp_us)) {
                /* 视频文件播放完毕，循环播放 */
                if (frame.data) delete[] frame.data;
                printf("[Pipeline] Video file ended, restarting (frame_idx=%d)\n", frame_idx);
                file_input.close();
                if (!file_input.open(source_path)) {
                    std::cerr << "[Pipeline] Failed to reopen input: " << source_path << std::endl;
                    g_running.store(false);
                    return;
                }
                frame_idx = 0;  /* 重置帧计数 */
                continue;
            }
            frame_queue.push_or_wait(frame);
        }
        file_input.close();
    }
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
                                  ThreadSafeQueue<FrameData> &frame_queue,
                                  ThreadSafeQueue<DetectResult> &detect_queue,
                                  Rknn1Engine *shared_engine)
{
    printf("[Pipeline] Inference thread started on CPU %d\n",
           cfg.system.cpu_inference);

    cpu_set_t mask;
    CPU_ZERO(&mask);
    CPU_SET(cfg.system.cpu_inference, &mask);
    pthread_setaffinity_np(pthread_self(), sizeof(mask), &mask);

    /* 使用主线程共享的 NPU 引擎 (RK3399Pro 只允许一个 NPU 上下文) */
    Rknn1Engine *engine_ptr = shared_engine;
    bool has_inf_engine = (engine_ptr != nullptr);

    std::queue<float> perf_history;
    float perf_sum = 0.0;

    while (g_running.load()) {
        thread_heartbeat(ThreadRole::INFERENCE);
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
        int cost_us = has_inf_engine ? engine_ptr->inference(frame.data) : -1;

        if (cost_us < 0) {
            std::cerr << "[Pipeline] Inference failed on frame "
                      << frame.index << std::endl;
            /* 清理帧数据 */
            if (frame.capture)
                frame.capture->release_frame();
            else if (frame.data)
                delete[] frame.data;
            continue;
        }

        /* 复制帧数据用于编码/推流 (必须在归还 V4L2 缓冲区之前)
         * 编码器始终初始化 (支持远程 MQTT 命令随时启动录制/RTSP),
         * 因此帧数据始终需要复制, 否则远程启动录制后推帧会收到 nullptr
         * RGB24: width × height × 3 字节
         * unique_ptr 管理: 任何路径退出均自动释放, 无内存泄漏 */
        std::unique_ptr<unsigned char[]> frame_copy;
        {
            size_t frame_size = (size_t)frame.width * frame.height * 3;
            frame_copy = std::make_unique<unsigned char[]>(frame_size);
            memcpy(frame_copy.get(), frame.data, frame_size);
        }

        /* 归还缓冲区 */
        if (frame.capture)
            frame.capture->release_frame();
        else if (frame.data)
            delete[] frame.data;

        /* 性能统计 */
        float cost_ms = cost_us / 1000.0f;
        float avg_ms = engine_ptr->cal_performance(perf_history,
                                              perf_sum, cost_ms);

        /* 后处理 (YOLOv5 decode + NMS) */
        DetectResult result;
        result.frame_index = frame.index;
        result.timestamp_us = frame.timestamp_us;
        result.frame_data = std::move(frame_copy);
        result.frame_width = frame.width;
        result.frame_height = frame.height;

        /* 调用 YOLOv5 后处理 (复用现有 decode.cpp 逻辑) */
        post_process_fp(engine_ptr->_output_buffs[0],
                        engine_ptr->_output_buffs[1],
                        engine_ptr->_output_buffs[2],
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
                                 ThreadSafeQueue<DetectResult> &detect_queue,
                                 ThreadSafeQueue<TrackResult> &track_queue)
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
        thread_heartbeat(ThreadRole::TRACKING);
        DetectResult det;
        if (!detect_queue.pop(det)) {
            usleep(1000);
            continue;
        }

        /* SORT 跟踪 */
        TrackResult result;
        result.frame_index = det.frame_index;
        result.timestamp_us = det.timestamp_us;
        /* 传递帧数据 (所有权转移: DetectResult → TrackResult, unique_ptr 自动管理) */
        result.frame_data = std::move(det.frame_data);
        result.frame_width = det.frame_width;
        result.frame_height = det.frame_height;

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
 * 从 track_queue 取跟踪结果 → MQTT 上报 + 视频编码 + RTSP 推流
 *
 * 背压: 队列满时本地缓存 (断网不丢数据)
 */
static void output_thread_func(const PipelineConfig &cfg,
                               ThreadSafeQueue<TrackResult> &track_queue)
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

        /* 设置 MQTT 命令回调 → 转发到 gRPC server 的 handle_command
         * 同时处理视频录制/RTSP 远程控制命令 */
        mqtt.set_command_callback([](const char *topic,
                                      const char *payload, int len) {
            std::string msg(payload, len);
            std::string cmd;

            /* 视频录制/RTSP 远程控制 (直接设置全局原子标志) */
            if (msg.find("\"start_recording\"") != std::string::npos) {
                g_recording_requested.store(true);
                printf("[Pipeline] MQTT: start_recording requested\n");
                return;
            } else if (msg.find("\"stop_recording\"") != std::string::npos) {
                g_recording_requested.store(false);
                printf("[Pipeline] MQTT: stop_recording requested\n");
                return;
            } else if (msg.find("\"start_rtsp\"") != std::string::npos) {
                g_rtsp_requested.store(true);
                printf("[Pipeline] MQTT: start_rtsp requested\n");
                return;
            } else if (msg.find("\"stop_rtsp\"") != std::string::npos) {
                g_rtsp_requested.store(false);
                printf("[Pipeline] MQTT: stop_rtsp requested\n");
                return;
            }

            /* 其他命令转发到 gRPC server */
            if (!g_grpc_server) return;

            if (msg.find("\"switch_scene\"") != std::string::npos)
                cmd = "switch_scene";
            else if (msg.find("\"reload_model\"") != std::string::npos)
                cmd = "reload_model";
            else if (msg.find("\"app_update\"") != std::string::npos)
                cmd = "app_update";
            else if (msg.find("\"rollback\"") != std::string::npos)
                cmd = "rollback";

            if (!cmd.empty())
                g_grpc_server->handle_command(cmd, msg);
        });
    }

    /* 初始化视频编码器 (H.264/H.265 硬件编码)
     * 支持两种启动方式:
     *   1. 配置文件 save_video=true → 自动启动
     *   2. PC 端 MQTT 命令 → 远程启动/停止
     */
    VideoEncoder video_encoder;
    bool encoder_initialized = false;
    if (cfg.output.save_video || true) {  /* 始终初始化, 支持远程启动 */
        encoder_initialized = video_encoder.init(
            cfg.input.v4l2_width, cfg.input.v4l2_height,
            cfg.input.v4l2_fps,
            cfg.output.video_codec,
            cfg.output.video_bitrate_kbps,
            cfg.output.video_gop);
        if (!encoder_initialized) {
            fprintf(stderr, "[Pipeline] Failed to init video encoder\n");
        }
    }

    /* 初始化 RTSP 推流服务 */
    RtspServer rtsp_server;
    bool rtsp_initialized = false;
    if (cfg.output.enable_rtsp || true) {  /* 始终初始化, 支持远程启动 */
        rtsp_initialized = true;
    }

    /* 配置文件自动启动 */
    if (cfg.output.save_video && encoder_initialized) {
        video_encoder.start_recording(cfg.output.video_path);
        printf("[Pipeline] Video recording started: %s (%s, %dkbps)\n",
               cfg.output.video_path.c_str(),
               cfg.output.video_codec.c_str(),
               cfg.output.video_bitrate_kbps);
    }
    if (cfg.output.enable_rtsp && rtsp_initialized) {
        if (rtsp_server.start(cfg.output.rtsp_port, cfg.output.rtsp_mount,
                              cfg.input.v4l2_width, cfg.input.v4l2_height,
                              cfg.input.v4l2_fps,
                              cfg.output.rtsp_codec)) {
            printf("[Pipeline] RTSP server started on port %d%s\n",
                   cfg.output.rtsp_port, cfg.output.rtsp_mount.c_str());
        } else {
            fprintf(stderr, "[Pipeline] Failed to start RTSP server\n");
        }
    }

    /* ── 初始化传感器设备 ── */
    int uart_fd = -1;
    int spi_fd  = -1;
    if (cfg.sensor.uart_enabled) {
        uart_fd = open(cfg.sensor.uart_device.c_str(), O_RDONLY | O_NONBLOCK);
        if (uart_fd < 0)
            fprintf(stderr, "[Pipeline] Failed to open UART sensor: %s\n",
                    cfg.sensor.uart_device.c_str());
        else
            printf("[Pipeline] UART sensor opened: %s\n",
                   cfg.sensor.uart_device.c_str());
    }
    if (cfg.sensor.spi_enabled) {
        spi_fd = open(cfg.sensor.spi_device.c_str(), O_RDONLY | O_NONBLOCK);
        if (spi_fd < 0)
            fprintf(stderr, "[Pipeline] Failed to open SPI sensor: %s\n",
                    cfg.sensor.spi_device.c_str());
        else
            printf("[Pipeline] SPI sensor opened: %s\n",
                   cfg.sensor.spi_device.c_str());
    }

    /* 传感器数据缓冲 */
    char uart_buf[128] = {0};
    char spi_buf[128]  = {0};
    int sensor_read_counter = 0;

    while (g_running.load()) {
        thread_heartbeat(ThreadRole::OUTPUT);
        /* ── 远程控制: 录制启动/停止 ── */
        if (encoder_initialized) {
            bool want_rec = g_recording_requested.load();
            if (want_rec && !video_encoder.is_recording()) {
                video_encoder.start_recording(cfg.output.video_path);
                printf("[Pipeline] Remote: recording started\n");
            } else if (!want_rec && video_encoder.is_recording()) {
                video_encoder.stop_recording();
                printf("[Pipeline] Remote: recording stopped\n");
            }
        }

        /* ── 远程控制: RTSP 启动/停止 ── */
        if (rtsp_initialized) {
            bool want_rtsp = g_rtsp_requested.load();
            if (want_rtsp && !rtsp_server.is_running()) {
                rtsp_server.start(cfg.output.rtsp_port, cfg.output.rtsp_mount,
                                  cfg.input.v4l2_width, cfg.input.v4l2_height,
                                  cfg.input.v4l2_fps,
                                  cfg.output.rtsp_codec);
                printf("[Pipeline] Remote: RTSP started on port %d\n",
                       cfg.output.rtsp_port);
            } else if (!want_rtsp && rtsp_server.is_running()) {
                rtsp_server.stop();
                printf("[Pipeline] Remote: RTSP stopped\n");
            }
        }

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

        /* ── 传感器数据读取 (每 10 帧, 非阻塞) ── */
        if (++sensor_read_counter >= 10) {
            sensor_read_counter = 0;
            if (uart_fd >= 0) {
                ssize_t n = read(uart_fd, uart_buf, sizeof(uart_buf) - 1);
                if (n > 0) {
                    uart_buf[n] = '\0';
                    /* MQTT 上报传感器数据 */
                    if (cfg.mqtt.enabled) {
                        std::string sen_topic = "edge/" + cfg.mqtt.client_id + "/sensor/uart";
                        mqtt.publish_detections(sen_topic, result.boxes,
                                                result.frame_index, result.timestamp_us);
                    }
                }
            }
            if (spi_fd >= 0) {
                ssize_t n = read(spi_fd, spi_buf, sizeof(spi_buf) - 1);
                if (n > 0) {
                    spi_buf[n] = '\0';
                    if (cfg.mqtt.enabled) {
                        std::string sen_topic = "edge/" + cfg.mqtt.client_id + "/sensor/spi";
                        mqtt.publish_detections(sen_topic, result.boxes,
                                                result.frame_index, result.timestamp_us);
                    }
                }
            }
        }

        /* 视频编码: 将原始帧推入编码器 */
        if (video_encoder.is_recording() && result.frame_data) {
            video_encoder.push_frame(result.frame_data.get(),
                                     result.timestamp_us);
        }

        /* RTSP 推流: 将原始帧推入 RTSP 服务器 */
        if (rtsp_server.is_running() && result.frame_data) {
            rtsp_server.push_frame(result.frame_data.get(),
                                   result.timestamp_us);
        }

        /* 帧数据由 unique_ptr 自动释放, 无需手动 delete[] */
    }

    /* 停止编码和推流 */
    if (video_encoder.is_recording()) {
        video_encoder.stop_recording();
        printf("[Pipeline] Video recording stopped\n");
    }
    if (rtsp_server.is_running()) {
        rtsp_server.stop();
        printf("[Pipeline] RTSP server stopped\n");
    }

    /* 关闭传感器设备 */
    if (uart_fd >= 0) {
        close(uart_fd);
        printf("[Pipeline] UART sensor closed\n");
    }
    if (spi_fd >= 0) {
        close(spi_fd);
        printf("[Pipeline] SPI sensor closed\n");
    }

    if (cfg.mqtt.enabled)
        mqtt.disconnect();

    printf("[Pipeline] Output thread stopped\n");
}

/* ── gRPC 服务线程 ─────────────────────────────────────── */
/*
 * grpc_server_thread_func — gRPC 模型更新服务 + OTA
 *
 * 独立线程, 监听 gRPC 请求:
 *   - PushModel: 接收新模型 → 热加载
 *   - SwitchScene: 切换场景
 *   - GetStatus: 返回设备状态
 *   - Rollback: 版本回滚
 *   - GetVersionInfo: 查询版本
 */
static void grpc_server_thread_func(const PipelineConfig &cfg,
                                    Rknn1Engine *engine)
{
    printf("[Pipeline] gRPC server thread started on %s\n",
           cfg.grpc.listen_address.c_str());

    /* 初始化 OTA Manager */
    OtaManager ota_manager(engine, &cfg);

    GrpcServer server;
    g_grpc_server = &server;
    server.start(cfg.grpc.listen_address, cfg.grpc.unix_socket,
                 engine, &cfg);

    /* 连接 OTA Manager 到 gRPC server */
    grpc_set_ota_manager(&ota_manager);

    /* gRPC 服务器在主循环中运行, 直到 shutdown */
    while (g_running.load()) {
        thread_heartbeat(ThreadRole::GRPC);
        sleep(1);
    }

    g_grpc_server = nullptr;
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
    ThreadSafeQueue<FrameData> frame_queue(qsize);
    ThreadSafeQueue<DetectResult> detect_queue(qsize);
    ThreadSafeQueue<TrackResult> track_queue(qsize);

    /* 初始化 NPU 引擎 (主线程初始化, gRPC 线程共享) */
    printf("[Pipeline] Creating RKNN engine...\n"); fflush(stdout);
    Rknn1Engine engine(cfg.inference.model_path.c_str(),
                       cfg.system.cpu_inference);
    printf("[Pipeline] RKNN engine created, starting threads...\n"); fflush(stdout);

    /* 启动工作线程 */
    std::thread capture_th(capture_thread_func,
                          std::ref(cfg), std::ref(frame_queue));
    std::thread inference_th(inference_thread_func,
                             std::ref(cfg),
                             std::ref(frame_queue),
                             std::ref(detect_queue),
                             &engine);
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

    printf("[Pipeline] All threads started, running...\n"); fflush(stdout);

    /* 主循环: 100ms 轮询 shutdown + 线程健康监控 */
    while (g_running.load()) {
        usleep(100000);  /* 100ms */

        if (g_shutdown_requested.load()) {
            printf("[Pipeline] Shutdown requested, stopping...\n");
            g_running.store(false);
        }

        /* 线程健康检查: 有线程死亡 → 触发优雅关机 */
        int dead_threads = check_thread_health();
        if (dead_threads > 0) {
            fprintf(stderr, "[Pipeline] %d thread(s) dead, triggering shutdown\n",
                    dead_threads);
            g_running.store(false);
        }

        /* systemd watchdog: 通知 systemd 本服务仍存活
         * 需在 service unit 中配置 WatchdogSec=10 */
        sd_notify(0, "WATCHDOG=1");
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
