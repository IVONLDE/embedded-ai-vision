/* SPDX-License-Identifier: MIT */
/*
 * V4L2 Camera Capture with DMA-BUF Zero-Copy
 *
 * 功能: 从 V4L2 设备 (/dev/video0) 采集视频帧,
 *       使用 DMA-BUF 实现摄像头→NPU 零拷贝。
 *
 * 内核要求:
 *   - V4L2 + Media Controller + MIPI CSI
 *   - DMA-BUF (CONFIG_DMA_SHARED_BUFFER)
 *   - ISP 输出 NV12/RGB 格式
 *
 * 参考:
 *   - Documentation/media/uapi/v4l/
 *   - Linux Media Infrastructure API
 */

#include "v4l2_capture.h"

#include <fcntl.h>
#include <sys/ioctl.h>
#include <sys/mman.h>
#include <unistd.h>
#include <cstring>
#include <cerrno>
#include <iostream>

/* ── V4L2 设备操作 ──────────────────────────────────────── */

bool V4l2Capture::open(const std::string &device,
                       int width, int height, int fps)
{
    /* 完全重置状态 (支持 re-open) */
    if (_fd >= 0)
        close();

    _device = device;
    _width = width;
    _height = height;
    _fps = fps;
    _fd = -1;
    _streaming = false;
    _current_buf_index = -1;

    /* 打开 V4L2 设备 */
    _fd = ::open(device.c_str(), O_RDWR | O_NONBLOCK);
    if (_fd < 0) {
        std::cerr << "[V4L2] Failed to open " << device
                  << ": " << strerror(errno) << std::endl;
        return false;
    }

    /* 查询设备能力 */
    struct v4l2_capability cap;
    memset(&cap, 0, sizeof(cap));
    if (ioctl(_fd, VIDIOC_QUERYCAP, &cap) < 0) {
        std::cerr << "[V4L2] VIDIOC_QUERYCAP failed" << std::endl;
        close();
        return false;
    }

    printf("[V4L2] Device: %s, Driver: %s, Card: %s\n",
           cap.driver, cap.card, cap.bus_info);

    if (!(cap.capabilities & V4L2_CAP_VIDEO_CAPTURE)) {
        std::cerr << "[V4L2] Not a video capture device" << std::endl;
        close();
        return false;
    }

    if (!(cap.capabilities & V4L2_CAP_STREAMING)) {
        std::cerr << "[V4L2] No streaming support" << std::endl;
        close();
        return false;
    }

    /* 设置格式 */
    struct v4l2_format fmt;
    memset(&fmt, 0, sizeof(fmt));
    fmt.type = V4L2_BUF_TYPE_VIDEO_CAPTURE;
    fmt.fmt.pix.width = width;
    fmt.fmt.pix.height = height;
    fmt.fmt.pix.pixelformat = V4L2_PIX_FMT_RGB24;  /* RGB888 */
    fmt.fmt.pix.field = V4L2_FIELD_NONE;

    if (ioctl(_fd, VIDIOC_S_FMT, &fmt) < 0) {
        std::cerr << "[V4L2] VIDIOC_S_FMT failed" << std::endl;
        close();
        return false;
    }

    printf("[V4L2] Format: %dx%d, pixelformat=%.4s, stride=%d\n",
           fmt.fmt.pix.width, fmt.fmt.pix.height,
           (char *)&fmt.fmt.pix.pixelformat,
           fmt.fmt.pix.bytesperline);

    _width = fmt.fmt.pix.width;
    _height = fmt.fmt.pix.height;
    _stride = fmt.fmt.pix.bytesperline;

    /* 设置帧率 */
    struct v4l2_streamparm parm;
    memset(&parm, 0, sizeof(parm));
    parm.type = V4L2_BUF_TYPE_VIDEO_CAPTURE;
    parm.parm.capture.timeperframe.numerator = 1;
    parm.parm.capture.timeperframe.denominator = fps;

    if (ioctl(_fd, VIDIOC_S_PARM, &parm) < 0) {
        std::cerr << "[V4L2] VIDIOC_S_PARM failed" << std::endl;
        /* 非致命, 继续 */
    }

    /* 请求缓冲区 (DMA-BUF 模式) */
    struct v4l2_requestbuffers req;
    memset(&req, 0, sizeof(req));
    req.count = _num_buffers;
    req.type = V4L2_BUF_TYPE_VIDEO_CAPTURE;
    req.memory = V4L2_MEMORY_MMAP;  /* mmap 模式 (DMA-BUF 通过 export) */

    if (ioctl(_fd, VIDIOC_REQBUFS, &req) < 0) {
        std::cerr << "[V4L2] VIDIOC_REQBUFS failed" << std::endl;
        close();
        return false;
    }

    printf("[V4L2] Allocated %d buffers\n", req.count);
    _num_buffers = req.count;

    /* 映射缓冲区 */
    _buffers = new BufferInfo[_num_buffers];

    for (unsigned int i = 0; i < _num_buffers; i++) {
        struct v4l2_buffer buf;
        memset(&buf, 0, sizeof(buf));
        buf.type = V4L2_BUF_TYPE_VIDEO_CAPTURE;
        buf.memory = V4L2_MEMORY_MMAP;
        buf.index = i;

        if (ioctl(_fd, VIDIOC_QUERYBUF, &buf) < 0) {
            std::cerr << "[V4L2] VIDIOC_QUERYBUF failed for buf "
                      << i << std::endl;
            close();
            return false;
        }

        _buffers[i].length = buf.length;
        _buffers[i].start = mmap(NULL, buf.length,
                                 PROT_READ | PROT_WRITE,
                                 MAP_SHARED, _fd, buf.m.offset);

        if (_buffers[i].start == MAP_FAILED) {
            std::cerr << "[V4L2] mmap failed for buf " << i << std::endl;
            close();
            return false;
        }

        /* 导出 DMA-BUF fd (用于零拷贝共享给 NPU) */
        struct v4l2_exportbuffer expbuf;
        memset(&expbuf, 0, sizeof(expbuf));
        expbuf.type = V4L2_BUF_TYPE_VIDEO_CAPTURE;
        expbuf.index = i;
        expbuf.flags = O_RDONLY;

        if (ioctl(_fd, VIDIOC_EXPBUF, &expbuf) == 0) {
            _buffers[i].dma_fd = expbuf.fd;
            printf("[V4L2] Buffer %d: DMA-BUF fd=%d, size=%d\n",
                   i, expbuf.fd, buf.length);
        } else {
            _buffers[i].dma_fd = -1;
        }
    }

    printf("[V4L2] Device opened successfully\n");
    return true;
}

/* ── 开始/停止视频流 ────────────────────────────────────── */

bool V4l2Capture::start_stream()
{
    /* 将所有缓冲区入队 */
    for (unsigned int i = 0; i < _num_buffers; i++) {
        struct v4l2_buffer buf;
        memset(&buf, 0, sizeof(buf));
        buf.type = V4L2_BUF_TYPE_VIDEO_CAPTURE;
        buf.memory = V4L2_MEMORY_MMAP;
        buf.index = i;

        if (ioctl(_fd, VIDIOC_QBUF, &buf) < 0) {
            std::cerr << "[V4L2] VIDIOC_QBUF failed" << std::endl;
            return false;
        }
    }

    /* 启动流 */
    enum v4l2_buf_type type = V4L2_BUF_TYPE_VIDEO_CAPTURE;
    if (ioctl(_fd, VIDIOC_STREAMON, &type) < 0) {
        std::cerr << "[V4L2] VIDIOC_STREAMON failed" << std::endl;
        return false;
    }

    _streaming = true;
    printf("[V4L2] Stream started\n");
    return true;
}

bool V4l2Capture::stop_stream()
{
    if (!_streaming)
        return true;

    enum v4l2_buf_type type = V4L2_BUF_TYPE_VIDEO_CAPTURE;
    if (ioctl(_fd, VIDIOC_STREAMOFF, &type) < 0) {
        std::cerr << "[V4L2] VIDIOC_STREAMOFF failed" << std::endl;
        return false;
    }

    _streaming = false;
    printf("[V4L2] Stream stopped\n");
    return true;
}

/* ── 读取一帧 ──────────────────────────────────────────── */
/*
 * read_frame — 从 V4L2 读取一帧 (DMA-BUF 零拷贝)
 *
 * 流程:
 *   1. VIDIOC_DQBUF — 取出填充好的缓冲区
 *   2. 返回缓冲区指针 (DMA-BUF 映射的内存, 无需拷贝)
 *   3. 调用方使用完毕后调用 release_frame 归还缓冲区
 *
 * 注意: 返回的 data 指针指向 DMA-BUF 映射内存,
 *       调用方不应修改, 直接传给 NPU 推理。
 */
bool V4l2Capture::read_frame(unsigned char **data,
                              int *width, int *height,
                              int64_t *timestamp_us)
{
    if (!_streaming) {
        if (!start_stream())
            return false;
    }

    struct v4l2_buffer buf;
    memset(&buf, 0, sizeof(buf));
    buf.type = V4L2_BUF_TYPE_VIDEO_CAPTURE;
    buf.memory = V4L2_MEMORY_MMAP;

    /* 等待帧 (阻塞) */
    if (ioctl(_fd, VIDIOC_DQBUF, &buf) < 0) {
        if (errno == EAGAIN)
            return false;  /* 无可用帧 */
        std::cerr << "[V4L2] VIDIOC_DQBUF failed: "
                  << strerror(errno) << std::endl;
        return false;
    }

    _current_buf_index = buf.index;

    *data = (unsigned char *)_buffers[buf.index].start;
    *width = _width;
    *height = _height;

    /* 时间戳 (V4L2 提供) */
    *timestamp_us = (int64_t)buf.timestamp.tv_sec * 1000000 +
                    buf.timestamp.tv_usec;

    return true;
}

/*
 * release_frame — 归还缓冲区给 V4L2 驱动
 */
void V4l2Capture::release_frame()
{
    if (_current_buf_index < 0)
        return;

    struct v4l2_buffer buf;
    memset(&buf, 0, sizeof(buf));
    buf.type = V4L2_BUF_TYPE_VIDEO_CAPTURE;
    buf.memory = V4L2_MEMORY_MMAP;
    buf.index = _current_buf_index;

    if (ioctl(_fd, VIDIOC_QBUF, &buf) < 0) {
        std::cerr << "[V4L2] VIDIOC_QBUF failed" << std::endl;
    }

    _current_buf_index = -1;
}

/* ── 获取 DMA-BUF fd ───────────────────────────────────── */
/*
 * get_dma_fd — 获取当前帧的 DMA-BUF 文件描述符
 *
 * 用于零拷贝共享给 NPU (通过 rknn_create_mem_from_fd)
 */
int V4l2Capture::get_dma_fd()
{
    if (_current_buf_index < 0)
        return -1;
    return _buffers[_current_buf_index].dma_fd;
}

/* ── 关闭设备 ──────────────────────────────────────────── */

void V4l2Capture::close()
{
    if (_streaming)
        stop_stream();

    /* 解除 mmap */
    if (_buffers) {
        for (unsigned int i = 0; i < _num_buffers; i++) {
            if (_buffers[i].start && _buffers[i].start != MAP_FAILED) {
                munmap(_buffers[i].start, _buffers[i].length);
            }
            if (_buffers[i].dma_fd >= 0) {
                ::close(_buffers[i].dma_fd);
            }
        }
        delete[] _buffers;
        _buffers = nullptr;
    }

    if (_fd >= 0) {
        ::close(_fd);
        _fd = -1;
    }

    printf("[V4L2] Device closed\n");
}
