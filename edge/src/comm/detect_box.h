/* SPDX-License-Identifier: MIT */
/*
 * DetectBox — 统一检测框结构体
 *
 * 在 pipeline、tracker、mqtt、decode 中共享,
 * 避免 ODR 违规和重复定义。
 */

#ifndef DETECT_BOX_H
#define DETECT_BOX_H

struct DetectBox {
    float x1 = 0, y1 = 0, x2 = 0, y2 = 0;
    float confidence = 0;
    float classID = -1;
    float trackID = -1;

    DetectBox() = default;
    DetectBox(float _x1, float _y1, float _x2, float _y2,
              float _conf = 0, float _cls = -1)
        : x1(_x1), y1(_y1), x2(_x2), y2(_y2),
          confidence(_conf), classID(_cls), trackID(-1) {}
};

#endif /* DETECT_BOX_H */