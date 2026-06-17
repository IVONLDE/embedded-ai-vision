/* SPDX-License-Identifier: MIT */
/*
 * YOLOv5 Post-Processing — Header
 */

#ifndef YOLOV5_DECODE_H
#define YOLOV5_DECODE_H

#include <vector>

struct DetectBox;

/*
 * post_process_fp — YOLOv5 float32 输出后处理
 * @input0/1/2: NPU 输出的三个特征层 (float32)
 * @conf_threshold: 置信度阈值
 * @nms_threshold: NMS IoU 阈值
 * @result: 输出的检测框列表
 * @return: 0 成功
 */
int post_process_fp(float *input0, float *input1, float *input2,
                    float conf_threshold, float nms_threshold,
                    std::vector<DetectBox> *result);

#endif /* YOLOV5_DECODE_H */