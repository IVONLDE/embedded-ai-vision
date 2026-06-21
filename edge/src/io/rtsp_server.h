/* SPDX-License-Identifier: MIT */
/*
 * RTSP Server — 基于 GStreamer gst-rtsp-server 的实时推流
 *
 * 功能:
 *   - 将视频帧通过 RTSP 协议对外发布
 *   - 支持 H.264/H.265 硬件编码
 *   - 客户端 (VLC/FFplay) 可通过 rtsp://IP:8554/edge_camera 查看
 *
 * 平台: RK3399Pro + Rockchip MPP
 * 依赖: gstreamer1, gst-rtsp-server-1.0, mpp
 */

#ifndef RTSP_SERVER_H
#define RTSP_SERVER_H

#include <string>
#include <cstdint>
#include <mutex>
#include <atomic>
#include <thread>

/* GStreamer 前向声明 */
typedef struct _GstRTSPServer GstRTSPServer;
typedef struct _GstAppSrc GstAppSrc;
typedef struct _GstPipeline GstPipeline;
typedef struct _GMainLoop GMainLoop;
typedef struct _GMainContext GMainContext;

class RtspServer {
public:
    RtspServer();
    ~RtspServer();

    /* ── 生命周期 ──────────────────────────────────────── */

    /**
     * start — 启动 RTSP 服务
     * @port: 端口号 (默认 8554)
     * @mount: 挂载点 (如 "/edge_camera")
     * @width, @height: 视频分辨率
     * @fps: 帧率
     * @codec: "h264" 或 "h265"
     *
     * 在独立线程中运行 GLib main loop
     */
    bool start(int port, const std::string &mount,
               int width, int height, int fps,
               const std::string &codec = "h264");

    /**
     * stop — 停止 RTSP 服务
     */
    void stop();

    /**
     * is_running — 是否正在运行
     */
    bool is_running() const { return _running.load(); }

    /* ── 帧推送 ────────────────────────────────────────── */

    /**
     * push_frame — 向 RTSP 管道推帧
     * @data: RGB24 格式数据
     * @timestamp_us: 时间戳 (微秒)
     *
     * 线程安全: 可从任意线程调用
     */
    bool push_frame(const unsigned char *data, int64_t timestamp_us);

    /* ── 状态查询 ──────────────────────────────────────── */
    int port() const { return _port; }
    const std::string& mount() const { return _mount; }

private:
    /* RTSP 服务 */
    GstRTSPServer *_server = nullptr;
    GstAppSrc *_appsrc = nullptr;

    /* GLib main loop (独立线程) */
    GMainLoop *_loop = nullptr;
    GMainContext *_context = nullptr;
    std::thread _thread;

    /* 配置 */
    int _width = 0;
    int _height = 0;
    int _fps = 30;
    int _port = 8554;
    std::string _mount;
    std::string _codec;

    /* 状态 */
    std::atomic<bool> _running{false};
    std::atomic<uint64_t> _frames_pushed{0};

    /* 线程安全 */
    std::mutex _mutex;

    /* 内部方法 */
    void server_thread_func();
    static void on_media_configure(GstRTSPServer *server,
                                    GstRTSPMedia *media,
                                    gpointer user_data);
};

#endif /* RTSP_SERVER_H */
