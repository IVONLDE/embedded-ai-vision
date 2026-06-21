/* SPDX-License-Identifier: MIT */
/*
 * Video Encoder — GStreamer + Rockchip MPP 硬件编码实现
 */

#include "video_encoder.h"

#include <gst/gst.h>
#include <gst/app/gstappsrc.h>
#include <cstring>
#include <chrono>

/* ── 构造/析构 ──────────────────────────────────────────── */
VideoEncoder::VideoEncoder()
{
    /* GStreamer 初始化 (全局一次) */
    gst_init(nullptr, nullptr);
}

VideoEncoder::~VideoEncoder()
{
    deinit();
}

/* ── 初始化 ────────────────────────────────────────────── */
bool VideoEncoder::init(int width, int height, int fps,
                         const std::string &codec,
                         int bitrate_kbps, int gop)
{
    std::lock_guard<std::mutex> lock(_mutex);

    if (_initialized.load()) {
        fprintf(stderr, "[VideoEncoder] Already initialized\n");
        return false;
    }

    _width = width;
    _height = height;
    _fps = fps;
    _codec = codec;
    _bitrate_kbps = bitrate_kbps;
    _gop = gop;

    _initialized.store(true);
    printf("[VideoEncoder] Initialized: %dx%d @%dfps, codec=%s, bitrate=%dkbps, gop=%d\n",
           width, height, fps, codec.c_str(), bitrate_kbps, gop);
    return true;
}

void VideoEncoder::deinit()
{
    std::lock_guard<std::mutex> lock(_mutex);

    if (!_initialized.load())
        return;

    if (_recording.load())
        stop_recording();

    _initialized.store(false);
    printf("[VideoEncoder] Deinitialized\n");
}

/* ── 创建编码管道 ──────────────────────────────────────── */
bool VideoEncoder::create_pipeline(const std::string &output_path)
{
    /* 管道结构:
     * appsrc → videoconvert → mpph264enc/h265enc → parser → muxer → filesink
     *
     * Rockchip MPP 编码器元素名:
     *   mpph264enc — H.264 硬件编码
     *   mpph265enc — H.265 硬件编码
     */

    const char *encoder_name = (_codec == "h265") ? "mpph265enc" : "mpph264enc";
    const char *parser_name = (_codec == "h265") ? "h265parse" : "h264parse";

    /* 确定封装格式 */
    const char *muxer_name = "qtmux";  /* 默认 MP4 */
    if (output_path.find(".mkv") != std::string::npos)
        muxer_name = "matroskamux";
    else if (output_path.find(".ts") != std::string::npos)
        muxer_name = "mpegtsmux";

    printf("[VideoEncoder] Creating pipeline: appsrc → videoconvert → %s → %s → %s → filesink\n",
           encoder_name, parser_name, muxer_name);

    /* 创建元素 */
    GstElement *pipeline = gst_pipeline_new("video_encoder");
    GstElement *src = gst_element_factory_make("appsrc", "src");
    GstElement *convert = gst_element_factory_make("videoconvert", "convert");
    GstElement *encoder = gst_element_factory_make(encoder_name, "encoder");
    GstElement *parser = gst_element_factory_make(parser_name, "parser");
    GstElement *muxer = gst_element_factory_make(muxer_name, "muxer");
    GstElement *sink = gst_element_factory_make("filesink", "sink");

    if (!pipeline || !src || !convert || !encoder || !parser || !muxer || !sink) {
        fprintf(stderr, "[VideoEncoder] Failed to create elements\n");
        if (pipeline) gst_object_unref(pipeline);
        return false;
    }

    /* 配置 appsrc */
    GstCaps *caps = gst_caps_new_simple("video/x-raw",
        "format", G_TYPE_STRING, "RGB",
        "width", G_TYPE_INT, _width,
        "height", G_TYPE_INT, _height,
        "framerate", GST_TYPE_FRACTION, _fps, 1,
        nullptr);
    gst_app_src_set_caps((GstAppSrc *)src, caps);
    gst_caps_unref(caps);

    /* appsrc 模式: 流模式, 手动推送 */
    gst_app_src_set_stream_type((GstAppSrc *)src, GST_APP_STREAM_TYPE_STREAM);
    gst_app_src_set_emit_signals((GstAppSrc *)src, TRUE);

    /* 配置编码器 */
    g_object_set(encoder,
        "bitrate", _bitrate_kbps,
        "gop", _gop,
        "profile", (_codec == "h264") ? "high" : "main",
        nullptr);

    /* 配置 filesink */
    g_object_set(sink, "location", output_path.c_str(), nullptr);

    /* 添加元素到管道 */
    gst_bin_add_many(GST_BIN(pipeline), src, convert, encoder, parser, muxer, sink, nullptr);

    /* 链接元素 */
    if (!gst_element_link_many(src, convert, encoder, parser, muxer, sink, nullptr)) {
        fprintf(stderr, "[VideoEncoder] Failed to link elements\n");
        gst_object_unref(pipeline);
        return false;
    }

    /* 获取 appsrc 引用 (后续 push_frame 使用) */
    _appsrc = (GstAppSrc *)src;
    _encoder = encoder;
    _muxer = muxer;
    _sink = sink;
    _pipeline = (GstPipeline *)pipeline;

    /* 监听 bus 消息 */
    _bus = gst_pipeline_get_bus(_pipeline);
    gst_bus_add_watch(_bus, (GstBusFunc)on_bus_message, this);

    printf("[VideoEncoder] Pipeline created successfully\n");
    return true;
}

void VideoEncoder::destroy_pipeline()
{
    if (!_pipeline)
        return;

    /* 发送 EOS 并等待 */
    if (!_eos_sent.load() && _appsrc) {
        GstFlowReturn ret = gst_app_src_end_of_stream(_appsrc);
        printf("[VideoEncoder] EOS sent, ret=%d\n", ret);
        _eos_sent.store(true);
    }

    /* 等待管道结束 (最多 5 秒) */
    GstStateChangeReturn state_ret = gst_element_get_state(
        (GstElement *)_pipeline, nullptr, nullptr, 5 * GST_SECOND);
    printf("[VideoEncoder] Pipeline state change ret=%d\n", state_ret);

    /* 停止管道 */
    gst_element_set_state((GstElement *)_pipeline, GST_STATE_NULL);

    /* 释放资源 */
    if (_bus) {
        gst_bus_remove_watch(_bus);
        gst_object_unref(_bus);
        _bus = nullptr;
    }

    if (_pipeline) {
        gst_object_unref(_pipeline);
        _pipeline = nullptr;
        _appsrc = nullptr;
        _encoder = nullptr;
        _muxer = nullptr;
        _sink = nullptr;
    }

    printf("[VideoEncoder] Pipeline destroyed\n");
}

/* ── Bus 消息处理 ──────────────────────────────────────── */
void VideoEncoder::on_bus_message(GstBus *bus, GstMessage *msg, gpointer data)
{
    VideoEncoder *self = (VideoEncoder *)data;

    switch (GST_MESSAGE_TYPE(msg)) {
    case GST_MESSAGE_ERROR: {
        GError *err = nullptr;
        gchar *debug = nullptr;
        gst_message_parse_error(msg, &err, &debug);
        fprintf(stderr, "[VideoEncoder] Error: %s (%s)\n",
                err->message, debug ? debug : "no debug");
        g_error_free(err);
        g_free(debug);
        self->_recording.store(false);
        break;
    }
    case GST_MESSAGE_EOS:
        printf("[VideoEncoder] EOS received\n");
        self->_recording.store(false);
        break;
    case GST_MESSAGE_STATE_CHANGED:
        /* 忽略 */
        break;
    default:
        break;
    }
}

/* ── 录制控制 ──────────────────────────────────────────── */
bool VideoEncoder::start_recording(const std::string &output_path)
{
    std::lock_guard<std::mutex> lock(_mutex);

    if (!_initialized.load()) {
        fprintf(stderr, "[VideoEncoder] Not initialized\n");
        return false;
    }

    if (_recording.load()) {
        fprintf(stderr, "[VideoEncoder] Already recording\n");
        return false;
    }

    /* 创建管道 */
    if (!create_pipeline(output_path))
        return false;

    /* 启动管道 */
    GstStateChangeReturn ret = gst_element_set_state(
        (GstElement *)_pipeline, GST_STATE_PLAYING);
    if (ret == GST_STATE_CHANGE_FAILURE) {
        fprintf(stderr, "[VideoEncoder] Failed to start pipeline\n");
        destroy_pipeline();
        return false;
    }

    _recording.store(true);
    _eos_sent.store(false);
    _frames_encoded.store(0);
    _bytes_written.store(0);
    _keyframes.store(0);

    printf("[VideoEncoder] Recording started: %s\n", output_path.c_str());
    return true;
}

void VideoEncoder::stop_recording()
{
    std::lock_guard<std::mutex> lock(_mutex);

    if (!_recording.load())
        return;

    printf("[VideoEncoder] Stopping recording...\n");

    /* 发送 EOS */
    if (_appsrc && !_eos_sent.load()) {
        gst_app_src_end_of_stream(_appsrc);
        _eos_sent.store(true);

        /* 等待 EOS 处理完成 (最多 3 秒) */
        GstClockTime timeout = 3 * GST_SECOND;
        GstMessage *msg = gst_bus_timed_pop_filtered(
            _bus, timeout, GST_MESSAGE_EOS | GST_MESSAGE_ERROR);
        if (msg) {
            gst_message_unref(msg);
        } else {
            printf("[VideoEncoder] Timeout waiting for EOS\n");
        }
    }

    destroy_pipeline();
    _recording.store(false);

    printf("[VideoEncoder] Recording stopped: %llu frames, %llu bytes, %llu keyframes\n",
           _frames_encoded.load(), _bytes_written.load(), _keyframes.load());
}

/* ── 帧推送 ────────────────────────────────────────────── */
bool VideoEncoder::push_frame(const unsigned char *data, int64_t timestamp_us)
{
    if (!_recording.load() || !_appsrc) {
        return false;
    }

    /* 计算 buffer 大小 */
    int frame_size = _width * _height * 3;  /* RGB24 */

    /* 创建 GstBuffer */
    GstBuffer *buffer = gst_buffer_new_allocate(nullptr, frame_size, nullptr);
    if (!buffer) {
        fprintf(stderr, "[VideoEncoder] Failed to allocate buffer\n");
        return false;
    }

    /* 映射 buffer 并拷贝数据 */
    GstMapInfo map;
    if (!gst_buffer_map(buffer, &map, GST_MAP_WRITE)) {
        gst_buffer_unref(buffer);
        fprintf(stderr, "[VideoEncoder] Failed to map buffer\n");
        return false;
    }

    memcpy(map.data, data, frame_size);
    gst_buffer_unmap(buffer, &map);

    /* 设置时间戳 */
    GST_BUFFER_PTS(buffer) = timestamp_us * 1000;  /* us → ns */
    GST_BUFFER_DTS(buffer) = GST_CLOCK_TIME_NONE;
    GST_BUFFER_DURATION(buffer) = GST_CLOCK_TIME_NONE;

    /* 推入 appsrc */
    GstFlowReturn ret = gst_app_src_push_buffer(_appsrc, buffer);

    if (ret != GST_FLOW_OK) {
        fprintf(stderr, "[VideoEncoder] push_buffer failed: %d\n", ret);
        return false;
    }

    _frames_encoded.fetch_add(1);

    /* 每隔一段时间打印进度 */
    uint64_t frames = _frames_encoded.load();
    if (frames % 100 == 0) {
        printf("[VideoEncoder] Encoded %llu frames\n", frames);
    }

    return true;
}

/* ── 参数调整 ──────────────────────────────────────────── */
bool VideoEncoder::set_bitrate(int bitrate_kbps)
{
    std::lock_guard<std::mutex> lock(_mutex);

    if (!_encoder)
        return false;

    _bitrate_kbps = bitrate_kbps;
    g_object_set(_encoder, "bitrate", bitrate_kbps, nullptr);
    printf("[VideoEncoder] Bitrate changed to %dkbps\n", bitrate_kbps);
    return true;
}

bool VideoEncoder::request_keyframe()
{
    std::lock_guard<std::mutex> lock(_mutex);

    if (!_encoder)
        return false;

    /* 发送 ForceKeyUnit event */
    GstEvent *event = gst_video_event_new_downstream_force_key_unit(
        GST_CLOCK_TIME_NONE,  /* timestamp */
        GST_CLOCK_TIME_NONE,  /* running_time */
        GST_CLOCK_TIME_NONE,  /* all_headers timestamp */
        TRUE,                 /* all_headers */
        0                     /* count */
    );

    gst_element_send_event(_encoder, event);
    _keyframes.fetch_add(1);
    printf("[VideoEncoder] Keyframe requested\n");
    return true;
}

/* ── 统计信息 ──────────────────────────────────────────── */
VideoEncoder::Stats VideoEncoder::get_stats() const
{
    Stats s;
    s.frames_encoded = _frames_encoded.load();
    s.bytes_written = _bytes_written.load();
    s.keyframes = _keyframes.load();
    s.bitrate_kbps = _bitrate_kbps;
    s.avg_fps = 0.0f;  /* 需要时间戳计算 */
    return s;
}