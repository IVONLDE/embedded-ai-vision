/* SPDX-License-Identifier: MIT */
/*
 * RTSP Server — 基于 GStreamer gst-rtsp-server 实现的实时推流
 */

#include "rtsp_server.h"

#include <gst/gst.h>
#include <gst/rtsp-server/rtsp-server.h>
#include <gst/app/gstappsrc.h>
#include <cstring>

/* ── 构造/析构 ──────────────────────────────────────────── */
RtspServer::RtspServer()
{
    gst_init(nullptr, nullptr);
}

RtspServer::~RtspServer()
{
    stop();
}

/* ── RTSP 服务线程 ──────────────────────────────────────── */
void RtspServer::server_thread_func()
{
    printf("[RtspServer] Server thread started on port %d\n", _port);

    /* 创建专用 main context (避免与其他线程冲突) */
    _context = g_main_context_new();
    g_main_context_push_thread_default(_context);

    /* 创建 RTSP server */
    _server = gst_rtsp_server_new();
    gst_rtsp_server_set_service(_server, std::to_string(_port).c_str());

    /* 获取挂载点 */
    GstRTSPMountPoints *mounts = gst_rtsp_server_get_mount_points(_server);
    GstRTSPMediaFactory *factory = gst_rtsp_media_factory_new();

    /* 设置编码管道
     * launch 字符串格式:
     *   ( appsrc name=src ! videoconvert ! mpph264enc ! h264parse ! rtph264pay name=pay )
     *
     * rtph264pay 是 RTSP 必需的 payload 元素
     * name=pay 是 gst-rtsp-server 的约定, 必须存在
     */
    const char *encoder = (_codec == "h265") ? "mpph265enc" : "mpph264enc";
    const char *parser = (_codec == "h265") ? "h265parse" : "h264parse";
    const char *payloader = (_codec == "h265") ? "rtph265pay" : "rtph264pay";

    std::string launch = std::string("( appsrc name=src ! videoconvert ! ")
                         + encoder + " ! " + parser + " ! "
                         + payloader + " name=pay pt=96 )";

    printf("[RtspServer] Launch: %s\n", launch.c_str());

    gst_rtsp_media_factory_set_launch(factory, launch.c_str());
    gst_rtsp_media_factory_set_shared(factory, TRUE);

    /* 挂载到指定路径 */
    gst_rtsp_mount_points_add_factory(mounts, _mount.c_str(), factory);
    g_object_unref(mounts);

    /* 连接 media-configure 信号 (获取 appsrc 引用) */
    g_signal_connect(_server, "media-configure",
                     G_CALLBACK(on_media_configure), this);

    /* 启动服务 */
    gst_rtsp_server_attach(_server, _context);

    printf("[RtspServer] Server running at rtsp://<IP>:%d%s\n", _port, _mount.c_str());

    /* 运行 main loop */
    _running.store(true);
    _loop = g_main_loop_new(_context, FALSE);
    g_main_loop_run(_loop);

    /* 清理 */
    printf("[RtspServer] Server thread stopping...\n");
    g_main_loop_unref(_loop);
    _loop = nullptr;

    g_main_context_pop_thread_default(_context);
    g_main_context_unref(_context);
    _context = nullptr;

    if (_server) {
        gst_object_unref(_server);
        _server = nullptr;
    }

    _running.store(false);
    printf("[RtspServer] Server thread stopped\n");
}

/* ── Media Configure 回调 ───────────────────────────────── */
void RtspServer::on_media_configure(GstRTSPServer *server,
                                     GstRTSPMedia *media,
                                     gpointer user_data)
{
    RtspServer *self = (RtspServer *)user_data;

    printf("[RtspServer] Media configured, getting appsrc...\n");

    /* 获取 appsrc 元素 */
    GstElement *element = gst_rtsp_media_get_element(media);
    GstElement *src = gst_bin_get_by_name(GST_BIN(element), "src");

    if (src && GST_IS_APP_SRC(src)) {
        self->_appsrc = (GstAppSrc *)src;

        /* 设置 caps */
        GstCaps *caps = gst_caps_new_simple("video/x-raw",
            "format", G_TYPE_STRING, "RGB",
            "width", G_TYPE_INT, self->_width,
            "height", G_TYPE_INT, self->_height,
            "framerate", GST_TYPE_FRACTION, self->_fps, 1,
            nullptr);
        gst_app_src_set_caps(self->_appsrc, caps);
        gst_caps_unref(caps);

        /* 设置流模式 */
        gst_app_src_set_stream_type(self->_appsrc, GST_APP_STREAM_TYPE_STREAM);
        gst_app_src_set_emit_signals(self->_appsrc, TRUE);

        printf("[RtspServer] Appsrc configured: %dx%d @%dfps\n",
               self->_width, self->_height, self->_fps);
    }

    if (element)
        gst_object_unref(element);
}

/* ── 启动服务 ────────────────────────────────────────────── */
bool RtspServer::start(int port, const std::string &mount,
                        int width, int height, int fps,
                        const std::string &codec)
{
    std::lock_guard<std::mutex> lock(_mutex);

    if (_running.load()) {
        fprintf(stderr, "[RtspServer] Already running\n");
        return false;
    }

    _port = port;
    _mount = mount;
    _width = width;
    _height = height;
    _fps = fps;
    _codec = codec;

    /* 启动服务线程 */
    _thread = std::thread(&RtspServer::server_thread_func, this);

    /* 等待服务启动 */
    for (int i = 0; i < 50 && !_running.load(); i++) {
        usleep(100000);  /* 100ms */
    }

    if (!_running.load()) {
        fprintf(stderr, "[RtspServer] Failed to start\n");
        if (_thread.joinable())
            _thread.join();
        return false;
    }

    printf("[RtspServer] Started successfully\n");
    return true;
}

/* ── 停止服务 ────────────────────────────────────────────── */
void RtspServer::stop()
{
    std::lock_guard<std::mutex> lock(_mutex);

    if (!_running.load())
        return;

    printf("[RtspServer] Stopping...\n");

    /* 停止 main loop */
    if (_loop && _context) {
        g_main_context_invoke(_context, (GSourceFunc)g_main_loop_quit, _loop);
    }

    /* 等待线程结束 */
    if (_thread.joinable())
        _thread.join();

    _appsrc = nullptr;
    printf("[RtspServer] Stopped\n");
}

/* ── 帧推送 ────────────────────────────────────────────── */
bool RtspServer::push_frame(const unsigned char *data, int64_t timestamp_us)
{
    if (!_running.load() || !_appsrc)
        return false;

    /* 计算 buffer 大小 */
    int frame_size = _width * _height * 3;

    /* 创建 GstBuffer */
    GstBuffer *buffer = gst_buffer_new_allocate(nullptr, frame_size, nullptr);
    if (!buffer) {
        fprintf(stderr, "[RtspServer] Failed to allocate buffer\n");
        return false;
    }

    /* 拷贝数据 */
    GstMapInfo map;
    if (!gst_buffer_map(buffer, &map, GST_MAP_WRITE)) {
        gst_buffer_unref(buffer);
        return false;
    }

    memcpy(map.data, data, frame_size);
    gst_buffer_unmap(buffer, &map);

    /* 设置时间戳 */
    GST_BUFFER_PTS(buffer) = timestamp_us * 1000;
    GST_BUFFER_DTS(buffer) = GST_CLOCK_TIME_NONE;
    GST_BUFFER_DURATION(buffer) = GST_CLOCK_TIME_NONE;

    /* 推入 appsrc */
    GstFlowReturn ret = gst_app_src_push_buffer(_appsrc, buffer);

    if (ret != GST_FLOW_OK) {
        fprintf(stderr, "[RtspServer] push_buffer failed: %d\n", ret);
        return false;
    }

    _frames_pushed.fetch_add(1);
    return true;
}
