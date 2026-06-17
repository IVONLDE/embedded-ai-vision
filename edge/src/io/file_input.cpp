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

    *data = _frame.data;
    *width = _frame.cols;
    *height = _frame.rows;
    *timestamp_us = _frame_idx * 33333;  /* 30fps ≈ 33.3ms per frame */
    _frame_idx++;

    return true;
}