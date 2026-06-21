/* SPDX-License-Identifier: MIT */
/*
 * Video Encoder — GStreamer + Rockchip MPP 硬件编码
 *
 * 功能:
 *   - H.264/H.265 硬件编码 (mpph264enc / mpph265enc)
 *   - 本地文件录制 (MP4/MKV)
 *   - RTSP 实时推流
 *   - 关键帧间隔/码率/Profile 配置
 *   - 报警片段抓取 (GOP 对齐截取)
 *
 * 平台: RK3399Pro + Rockchip MPP
 * 依赖: GStreamer 1.x, gst-plugins-base, mpp
 */

#ifndef VIDEO_ENCODER_H
#define VIDEO_ENCODER_H

#include <string>
#include <cstdint>
#include <mutex>
#include <atomic>

/* GStreamer 前向声明 (避免暴露头文件) */
typedef struct _GstElement GstElement;
typedef struct _GstPipeline GstPipeline;
typedef struct _GstAppSrc GstAppSrc;
typedef struct _GstBus GstBus;
typedef struct _GstSample GstSample;
typedef void* gpointer;

class VideoEncoder {
public:
    VideoEncoder();
    ~VideoEncoder();

    /* ── 生命周期 ──────────────────────────────────────── */

    /**
     * init — 初始化编码器
     * @width, @height: 视频分辨率
     * @fps: 帧率
     * @codec: "h264" 或 "h265"
     * @bitrate_kbps: 目标码率 (kbps), 如 4000 = 4Mbps
     * @gop: 关键帧间隔 (帧数), 如 30 = 每 30 帧一个 I 帧
     *
     * 创建 GStreamer 管道但暂不开始录制
     */
    bool init(int width, int height, int fps,
              const std::string &codec = "h264",
              int bitrate_kbps = 4000,
              int gop = 30);

    /**
     * deinit — 释放资源
     */
    void deinit();

    /* ── 录制控制 ──────────────────────────────────────── */

    /**
     * start_recording — 开始录制到文件
     * @output_path: 输出文件路径 (如 /data/output.mp4)
     *
     * 启动编码管道, 文件封装格式由扩展名决定:
     *   .mp4  → qtmux
     *   .mkv  → matroskamux
     *   .ts   → mpegtsmux
     */
    bool start_recording(const std::string &output_path);

    /**
     * stop_recording — 停止录制
     */
    void stop_recording();

    /**
     * is_recording — 是否正在录制
     */
    bool is_recording() const { return _recording.load(); }

    /* ── 帧推送 ────────────────────────────────────────── */

    /**
     * push_frame — 推入一帧 RGB 数据
     * @data: RGB24 格式数据 (width × height × 3 字节)
     * @timestamp_us: 时间戳 (微秒)
     *
     * 将帧推入 GStreamer appsrc, 编码后写入文件
     */
    bool push_frame(const unsigned char *data, int64_t timestamp_us);

    /* ── 参数调整 ──────────────────────────────────────── */

    /**
     * set_bitrate — 动态调整码率
     * @bitrate_kbps: 新的目标码率
     *
     * 运行时可调用, 下一帧生效
     */
    bool set_bitrate(int bitrate_kbps);

    /**
     * request_keyframe — 请求立即编码一个关键帧
     *
     * 用于报警片段截取 (确保 GOP 对齐)
     */
    bool request_keyframe();

    /* ── 状态查询 ──────────────────────────────────────── */

    int width() const { return _width; }
    int height() const { return _height; }
    int fps() const { return _fps; }
    const std::string& codec() const { return _codec; }

    /* ── 统计信息 ──────────────────────────────────────── */
    struct Stats {
        uint64_t frames_encoded;
        uint64_t bytes_written;
        uint64_t keyframes;
        uint32_t bitrate_kbps;
        float avg_fps;
    };
    Stats get_stats() const;

private:
    /* GStreamer 元素 */
    GstPipeline *_pipeline = nullptr;
    GstAppSrc *_appsrc = nullptr;
    GstElement *_encoder = nullptr;
    GstElement *_muxer = nullptr;
    GstElement *_sink = nullptr;
    GstBus *_bus = nullptr;

    /* 配置 */
    int _width = 0;
    int _height = 0;
    int _fps = 30;
    std::string _codec;
    int _bitrate_kbps = 4000;
    int _gop = 30;

    /* 状态 */
    std::atomic<bool> _initialized{false};
    std::atomic<bool> _recording{false};
    std::atomic<bool> _eos_sent{false};

    /* 统计 */
    std::atomic<uint64_t> _frames_encoded{0};
    std::atomic<uint64_t> _bytes_written{0};
    std::atomic<uint64_t> _keyframes{0};

    /* 线程安全 */
    std::mutex _mutex;

    /* 内部方法 */
    bool create_pipeline(const std::string &output_path);
    void destroy_pipeline();
    static void on_bus_message(GstBus *bus, GstMessage *msg, gpointer data);
};

#endif /* VIDEO_ENCODER_H */
