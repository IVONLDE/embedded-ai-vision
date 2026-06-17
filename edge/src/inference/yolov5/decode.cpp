/* SPDX-License-Identifier: MIT */
/*
 * YOLOv5 Decode + NMS Post-Processing
 *
 * 从原项目 yolov5/src/decode.cpp 简化迁移。
 * 支持 float32 输出 (RKNN output_attrs[].type = RKNN_TENSOR_FLOAT32).
 */

#include "detect.h"
#include <algorithm>
#include <climits>
#include <cmath>
#include <cstring>
#include <cstdio>
#include <vector>

/* ── Anchor 定义 ───────────────────────────────────────── */
static const int anchor0[6] = {10, 13, 16, 30, 33, 23};
static const int anchor1[6] = {30, 61, 62, 45, 59, 119};
static const int anchor2[6] = {116, 90, 156, 198, 373, 326};

static const int strides[3] = {8, 16, 32};
static const int grids[3][2] = {{80, 80}, {40, 40}, {20, 20}};

#define OBJ_CLASS_NUM  1
#define PROP_BOX_SIZE  (5 + OBJ_CLASS_NUM)

static inline int clamp_val(float val, int min, int max)
{
    return val > min ? (val < max ? val : max) : min;
}

static inline float sigmoid(float x)
{
    return 1.0f / (1.0f + expf(-x));
}

/* ── IoU ───────────────────────────────────────────────── */
static float calc_iou(float xmin0, float ymin0, float xmax0, float ymax0,
                      float xmin1, float ymin1, float xmax1, float ymax1)
{
    float w = fmax(0.f, fmin(xmax0, xmax1) - fmax(xmin0, xmin1));
    float h = fmax(0.f, fmin(ymax0, ymax1) - fmax(ymin0, ymin1));
    float i = w * h;
    float u = (xmax0 - xmin0) * (ymax0 - ymin0) +
              (xmax1 - xmin1) * (ymax1 - ymin1) - i;
    return (u <= 0.f) ? 0.f : (i / u);
}

/* ── NMS ───────────────────────────────────────────────── */
static int nms(int valid_count, std::vector<float> &boxes,
               std::vector<int> &order, float threshold)
{
    for (int i = 0; i < valid_count; i++) {
        if (order[i] == -1) continue;
        int n = order[i];
        for (int j = i + 1; j < valid_count; j++) {
            int m = order[j];
            if (m == -1) continue;
            float iou = calc_iou(
                boxes[n * 4 + 0], boxes[n * 4 + 1],
                boxes[n * 4 + 0] + boxes[n * 4 + 2],
                boxes[n * 4 + 1] + boxes[n * 4 + 3],
                boxes[m * 4 + 0], boxes[m * 4 + 1],
                boxes[m * 4 + 0] + boxes[m * 4 + 2],
                boxes[m * 4 + 1] + boxes[m * 4 + 3]);
            if (iou > threshold) order[j] = -1;
        }
    }
    return 0;
}

/* ── 快速排序 ──────────────────────────────────────────── */
static void quick_sort_desc(std::vector<float> &scores, int left, int right,
                            std::vector<int> &indices)
{
    if (left >= right) return;
    int i = left, j = right;
    float pivot = scores[indices[(left + right) / 2]];

    while (i <= j) {
        while (scores[indices[i]] > pivot) i++;
        while (scores[indices[j]] < pivot) j--;
        if (i <= j) {
            std::swap(indices[i], indices[j]);
            i++; j--;
        }
    }
    if (left < j) quick_sort_desc(scores, left, j, indices);
    if (i < right) quick_sort_desc(scores, i, right, indices);
}

/* ── 单层处理 ──────────────────────────────────────────── */
static int process_layer_fp(float *input, const int *anchor,
                            int grid_h, int grid_w, int stride,
                            std::vector<float> &boxes,
                            std::vector<float> &box_scores,
                            float threshold)
{
    int valid_count = 0;
    int grid_len = grid_h * grid_w;
    float thres = -1.0f * logf((1.0f / threshold) - 1.0f);

    for (int a = 0; a < 3; a++) {
        for (int i = 0; i < grid_h; i++) {
            for (int j = 0; j < grid_w; j++) {
                float box_conf = input[(PROP_BOX_SIZE * a + 4) * grid_len + i * grid_w + j];
                if (box_conf < thres) continue;

                int offset = (PROP_BOX_SIZE * a) * grid_len + i * grid_w + j;
                float *in_ptr = input + offset;

                float bx = sigmoid(in_ptr[0]) * 2.0f - 0.5f;
                float by = sigmoid(in_ptr[grid_len]) * 2.0f - 0.5f;
                float bw = sigmoid(in_ptr[2 * grid_len]) * 2.0f;
                float bh = sigmoid(in_ptr[3 * grid_len]) * 2.0f;

                bx = (bx + j) * stride;
                by = (by + i) * stride;
                bw = bw * bw * anchor[a * 2];
                bh = bh * bh * anchor[a * 2 + 1];
                bx -= bw / 2.0f;
                by -= bh / 2.0f;

                boxes.push_back(bx);
                boxes.push_back(by);
                boxes.push_back(bw);
                boxes.push_back(bh);

                float max_class_prob = in_ptr[5 * grid_len];
                float conf = sigmoid(box_conf);
                box_scores.push_back(conf * sigmoid(max_class_prob));
                valid_count++;
            }
        }
    }
    return valid_count;
}

/* ── YOLOv5 后处理入口 ─────────────────────────────────── */
/*
 * post_process_fp — YOLOv5 float32 输出后处理
 *
 * 调用方式 (来自 pipeline.cpp):
 *   post_process_fp(
 *       engine._output_buffs[0], engine._output_buffs[1], engine._output_buffs[2],
 *       conf_threshold, nms_threshold, &result->boxes);
 */
int post_process_fp(float *input0, float *input1, float *input2,
                    float conf_threshold, float nms_threshold,
                    std::vector<DetectBox> *result)
{
    std::vector<float> boxes;
    std::vector<float> scores;

    /* Layer 0: stride 8, grid 80×80 */
    int v0 = process_layer_fp(input0, (int *)anchor0, grids[0][0], grids[0][1],
                              strides[0], boxes, scores, conf_threshold);
    /* Layer 1: stride 16, grid 40×40 */
    int v1 = process_layer_fp(input1, (int *)anchor1, grids[1][0], grids[1][1],
                              strides[1], boxes, scores, conf_threshold);
    /* Layer 2: stride 32, grid 20×20 */
    int v2 = process_layer_fp(input2, (int *)anchor2, grids[2][0], grids[2][1],
                              strides[2], boxes, scores, conf_threshold);

    int valid_count = v0 + v1 + v2;
    if (valid_count <= 0) return 0;

    /* 按置信度排序 */
    std::vector<int> indices(valid_count);
    for (int i = 0; i < valid_count; i++) indices[i] = i;
    quick_sort_desc(scores, 0, valid_count - 1, indices);

    /* NMS */
    nms(valid_count, boxes, indices, nms_threshold);

    /* 构建结果 */
    for (int i = 0; i < valid_count; i++) {
        if (indices[i] == -1 || scores[i] < conf_threshold) continue;
        int n = indices[i];

        DetectBox det;
        det.x1 = boxes[n * 4 + 0];
        det.y1 = boxes[n * 4 + 1];
        det.x2 = boxes[n * 4 + 0] + boxes[n * 4 + 2];
        det.y2 = boxes[n * 4 + 1] + boxes[n * 4 + 3];
        det.confidence = scores[i];
        det.classID = 0;  /* 单类 */
        det.trackID = -1;

        result->push_back(det);
    }

    return 0;
}