/* SPDX-License-Identifier: MIT */
/*
 * File Input — 本地视频文件读取实现
 */

#include "file_input.h"
#include <cstdio>

bool FileInput::open(const std::string &path)
{
    if (!_cap.open(path)) {
        fprintf(stderr, "[FileInput] Failed to open: %s\n", path.c_str());
        return false;
    }

    _width = (int)_cap.get(cv::CAP_PROP_FRAME_WIDTH);
    _height = (int)_cap.get(cv::CAP_PROP_FRAME_HEIGHT);
    _frame_idx = 0;

    printf("[FileInput] Opened: %s (%dx%d)\n",
           path.c_str(), _width, _height);
    return true;
}

void FileInput::close()
{
    if (_cap.isOpened())
        _cap.release();
    printf("[FileInput] Closed\n");
}

bool FileInput::read_frame(unsigned char **data, int *width, int *height,
                            int64_t *timestamp_us)
{
    if (!_cap.isOpened())
        return false;

    if (!_cap.read(_frame))
        return false;

    /* 深拷贝帧数据避免悬空指针:
     * cv::Mat _frame 是成员变量，下次 read() 会覆盖内存。
     * 调用方负责释放此缓冲区。 */
    int data_size = _frame.total() * _frame.elemSize();
    unsigned char *copy_data = new unsigned char[data_size];
    memcpy(copy_data, _frame.data, data_size);

    *data = copy_data;
    *width = _frame.cols;
    *height = _frame.rows;
    *timestamp_us = _frame_idx * 33333;  /* 30fps ≈ 33.3ms per frame */
    _frame_idx++;

    return true;
}

/*
 * release_frame — 释放 read_frame 中分配的帧数据
 */
void FileInput::release_frame(unsigned char *data)
{
    delete[] data;
}