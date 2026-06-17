/* SPDX-License-Identifier: MIT */
/*
 * V4L2 Camera Capture — Header
 */

#ifndef V4L2_CAPTURE_H
#define V4L2_CAPTURE_H

#include <string>
#include <linux/videodev2.h>

class V4l2Capture {
public:
    V4l2Capture() = default;
    ~V4l2Capture() { close(); }

    bool open(const std::string &device, int width, int height, int fps);
    void close();

    bool start_stream();
    bool stop_stream();

    bool read_frame(unsigned char **data, int *width, int *height,
                    int64_t *timestamp_us);
    void release_frame();

    int get_dma_fd();  /* DMA-BUF fd for zero-copy NPU sharing */

    int width()  const { return _width; }
    int height() const { return _height; }
    int stride() const { return _stride; }

private:
    struct BufferInfo {
        void *start = nullptr;
        unsigned int length = 0;
        int dma_fd = -1;
    };

    std::string _device;
    int _fd = -1;
    int _width = 0;
    int _height = 0;
    int _stride = 0;
    int _fps = 30;
    bool _streaming = false;

    unsigned int _num_buffers = 4;
    BufferInfo *_buffers = nullptr;
    int _current_buf_index = -1;
};

#endif /* V4L2_CAPTURE_H */
