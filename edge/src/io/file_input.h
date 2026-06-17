/* SPDX-License-Identifier: MIT */
/*
 * File Input — 本地视频文件读取
 *
 * 用于测试和离线模式，从本地文件读取视频帧。
 */

#ifndef FILE_INPUT_H
#define FILE_INPUT_H

#include <string>
#include <opencv2/opencv.hpp>

class FileInput {
public:
    FileInput() = default;
    ~FileInput() { close(); }

    bool open(const std::string &path);
    void close();
    bool read_frame(unsigned char **data, int *width, int *height,
                    int64_t *timestamp_us);

private:
    cv::VideoCapture _cap;
    cv::Mat _frame;
    int _width = 0;
    int _height = 0;
    int _frame_idx = 0;
};

#endif /* FILE_INPUT_H */