/* SPDX-License-Identifier: MIT */
/*
 * Simple Online Realtime Tracking (SORT) for RK3399Pro
 *
 * 纯 CPU 算法，不依赖 ReID 网络，适配 RK3399Pro 单核 NPU。
 * 基于原项目 deepsort/ 代码简化 — 移除 ReID 特征提取和余弦距离匹配。
 *
 * 数据关联:
 *   1. 卡尔曼预测: predict() 每个轨迹的状态
 *   2. IoU 匹配: 匈牙利算法求解最优分配
 *   3. 轨迹更新: 匹配成功 → update, 未匹配 → mark_missed
 *   4. 新轨迹: 未匹配的检测 → 初始化新轨迹 (tentative)
 *
 * 轨迹状态:
 *   Tentative → (连续 n_init 帧命中) → Confirmed
 *   Confirmed → (连续 max_age 帧丢失) → Deleted
 */

#include "tracker.h"
#include "kalman_filter.h"
#include "hungarian.h"
#include <algorithm>
#include <cfloat>
#include <cmath>
#include <iostream>

/* ── 构造 ───────────────────────────────────────────────── */
Tracker::Tracker(float max_iou_distance, int max_age, int n_init)
{
    _max_iou_distance = max_iou_distance;
    _max_age = max_age;
    _n_init = n_init;
    _next_id = 1;
    _kf = KalmanFilter();
}

/* ── 卡尔曼预测 ────────────────────────────────────────── */
void Tracker::predict()
{
    for (auto &track : _tracks) {
        track.predict(_kf);
    }
}

/* ── 轨迹更新 ──────────────────────────────────────────── */
/*
 * update — 用检测结果更新轨迹
 *
 * 流程:
 *   1. 分离 confirmed / unconfirmed 轨迹
 *   2. 级联匹配 (confirmed tracks 按 age 分级匹配)
 *   3. IoU 匹配 (unconfirmed + unmatched confirmed)
 *   4. 更新匹配成功的轨迹
 *   5. 初始化新轨迹
 *   6. 清理已删除轨迹
 */
void Tracker::update(const std::vector<DetectBox> &detections)
{
    if (detections.empty()) {
        /* 无检测: 所有轨迹标记丢失 */
        for (auto &track : _tracks) {
            track.mark_missed();
        }

        /* 清理 */
        _tracks.erase(
            std::remove_if(_tracks.begin(), _tracks.end(),
                [](const Track &t) { return t.is_deleted(); }),
            _tracks.end());
        return;
    }

    /* ── 分离轨迹 ── */
    std::vector<int> confirmed_idx, unconfirmed_idx;
    for (int i = 0; i < (int)_tracks.size(); i++) {
        if (_tracks[i].is_confirmed())
            confirmed_idx.push_back(i);
        else
            unconfirmed_idx.push_back(i);
    }

    /* ── Step 1: 级联匹配 (confirmed tracks) ── */
    MatchResult cascade_res = cascade_match(confirmed_idx, detections);

    /* ── Step 2: IoU 匹配 (unconfirmed + unmatched) ── */
    std::vector<int> iou_candidates = unconfirmed_idx;
    for (int idx : cascade_res.unmatched_tracks) {
        /* 只有最近丢失的轨迹才参与 IoU 匹配 */
        if (_tracks[idx].time_since_update == 1) {
            iou_candidates.push_back(idx);
        } else {
            cascade_res.unmatched_tracks2.push_back(idx);
        }
    }

    MatchResult iou_res = iou_match(iou_candidates,
                                     cascade_res.unmatched_detections,
                                     detections);

    /* ── 合并匹配结果 ── */
    std::vector<MatchPair> all_matches = cascade_res.matches;
    all_matches.insert(all_matches.end(),
                       iou_res.matches.begin(),
                       iou_res.matches.end());

    std::vector<int> all_unmatched_tracks = iou_res.unmatched_tracks;
    all_unmatched_tracks.insert(all_unmatched_tracks.end(),
                                 cascade_res.unmatched_tracks2.begin(),
                                 cascade_res.unmatched_tracks2.end());

    std::vector<int> all_unmatched_dets = iou_res.unmatched_detections;

    /* ── 更新匹配成功的轨迹 ── */
    for (const auto &pair : all_matches) {
        _tracks[pair.track_idx].update(_kf, detections[pair.det_idx]);
    }

    /* ── 标记未匹配轨迹 ── */
    for (int idx : all_unmatched_tracks) {
        _tracks[idx].mark_missed();
    }

    /* ── 初始化新轨迹 ── */
    for (int idx : all_unmatched_dets) {
        const DetectBox &det = detections[idx];
        /* 转换为 [x, y, w, h] */
        float x = det.x1;
        float y = det.y1;
        float w = det.x2 - det.x1;
        float h = det.y2 - det.y1;

        /* 转换为 [cx, cy, a, h] */
        float cx = x + w / 2.0f;
        float cy = y + h / 2.0f;
        float aspect = w / h;

        KAL_MEAN mean = _kf.initiate(cx, cy, aspect, h);
        _tracks.push_back(Track(mean, _next_id++, _n_init, _max_age,
                                det.classID, det.confidence));
    }

    /* ── 清理已删除轨迹 ── */
    _tracks.erase(
        std::remove_if(_tracks.begin(), _tracks.end(),
            [](const Track &t) { return t.is_deleted(); }),
        _tracks.end());
}

/* ── 级联匹配 ──────────────────────────────────────────── */
/*
 * cascade_match — 按轨迹 age 分级匹配
 *
 * 先匹配"最近更新过"的轨迹，再匹配"久未更新"的轨迹。
 * 优先保证活跃轨迹的连续性。
 */
Tracker::MatchResult
Tracker::cascade_match(const std::vector<int> &track_indices,
                       const std::vector<DetectBox> &detections)
{
    MatchResult result;

    /* 按 time_since_update 分组 */
    int max_age = 0;
    for (int idx : track_indices) {
        max_age = std::max(max_age, _tracks[idx].time_since_update);
    }

    /* 未匹配的检测索引 */
    std::vector<int> unmatched_dets;
    for (int i = 0; i < (int)detections.size(); i++)
        unmatched_dets.push_back(i);

    /* 按 age 逐级匹配 */
    for (int level = 0; level <= max_age && !unmatched_dets.empty(); level++) {
        std::vector<int> level_tracks;
        for (int idx : track_indices) {
            if (_tracks[idx].time_since_update == level)
                level_tracks.push_back(idx);
        }

        if (level_tracks.empty())
            continue;

        /* 构建 IoU 代价矩阵 */
        Eigen::MatrixXf cost_matrix = build_iou_matrix(level_tracks,
                                                        unmatched_dets,
                                                        detections);

        /* 匈牙利算法求解 */
        Hungarian hungarian(cost_matrix.rows(), cost_matrix.cols());
        hungarian.solve(cost_matrix);

        std::vector<int> matched_dets;

        for (int i = 0; i < (int)level_tracks.size(); i++) {
            int j = hungarian.assignment(i);
            if (j >= 0 && j < (int)unmatched_dets.size() &&
                cost_matrix(i, j) < _max_iou_distance) {
                /* 匹配成功 */
                result.matches.push_back(
                    {level_tracks[i], unmatched_dets[j]});
                matched_dets.push_back(unmatched_dets[j]);
            } else {
                /* 当前轨迹未匹配 */
                result.unmatched_tracks.push_back(level_tracks[i]);
            }
        }

        /* 从未匹配检测中移除已匹配的 */
        std::sort(matched_dets.begin(), matched_dets.end());
        unmatched_dets.erase(
            std::remove_if(unmatched_dets.begin(), unmatched_dets.end(),
                [&matched_dets](int d) {
                    return std::binary_search(matched_dets.begin(),
                                              matched_dets.end(), d);
                }),
            unmatched_dets.end());
    }

    result.unmatched_detections = unmatched_dets;
    return result;
}

/* ── IoU 匹配 ──────────────────────────────────────────── */
Tracker::MatchResult
Tracker::iou_match(const std::vector<int> &track_indices,
                   const std::vector<int> &det_indices,
                   const std::vector<DetectBox> &detections)
{
    MatchResult result;

    if (track_indices.empty() || det_indices.empty()) {
        result.unmatched_tracks = track_indices;
        result.unmatched_detections = det_indices;
        return result;
    }

    Eigen::MatrixXf cost_matrix = build_iou_matrix(track_indices,
                                                    det_indices,
                                                    detections);

    Hungarian hungarian(cost_matrix.rows(), cost_matrix.cols());
    hungarian.solve(cost_matrix);

    for (int i = 0; i < (int)track_indices.size(); i++) {
        int j = hungarian.assignment(i);
        if (j >= 0 && j < (int)det_indices.size() &&
            cost_matrix(i, j) < _max_iou_distance) {
            result.matches.push_back({track_indices[i], det_indices[j]});
        } else {
            result.unmatched_tracks.push_back(track_indices[i]);
        }
    }

    /* 找出未匹配的检测 */
    std::vector<bool> det_matched(det_indices.size(), false);
    for (const auto &pair : result.matches) {
        for (int j = 0; j < (int)det_indices.size(); j++) {
            if (det_indices[j] == pair.det_idx) {
                det_matched[j] = true;
                break;
            }
        }
    }

    for (int j = 0; j < (int)det_indices.size(); j++) {
        if (!det_matched[j])
            result.unmatched_detections.push_back(det_indices[j]);
    }

    return result;
}

/* ── IoU 代价矩阵 ──────────────────────────────────────── */
Eigen::MatrixXf
Tracker::build_iou_matrix(const std::vector<int> &track_indices,
                          const std::vector<int> &det_indices,
                          const std::vector<DetectBox> &detections)
{
    int rows = track_indices.size();
    int cols = det_indices.size();
    Eigen::MatrixXf cost = Eigen::MatrixXf::Constant(rows, cols, 1.0f);

    for (int i = 0; i < rows; i++) {
        Track &track = _tracks[track_indices[i]];
        float tx, ty, tw, th;
        track.get_bbox(tx, ty, tw, th);

        for (int j = 0; j < cols; j++) {
            const DetectBox &det = detections[det_indices[j]];
            float dx = det.x1;
            float dy = det.y1;
            float dw = det.x2 - det.x1;
            float dh = det.y2 - det.y1;

            float iou = compute_iou(tx, ty, tw, th, dx, dy, dw, dh);
            cost(i, j) = 1.0f - iou;  /* 代价 = 1 - IoU */
        }
    }

    return cost;
}

/* ── IoU 计算 ──────────────────────────────────────────── */
float Tracker::compute_iou(float x1, float y1, float w1, float h1,
                           float x2, float y2, float w2, float h2)
{
    float left = std::max(x1, x2);
    float top = std::max(y1, y2);
    float right = std::min(x1 + w1, x2 + w2);
    float bottom = std::min(y1 + h1, y2 + h2);

    float inter_w = std::max(0.0f, right - left);
    float inter_h = std::max(0.0f, bottom - top);
    float inter_area = inter_w * inter_h;

    float area1 = w1 * h1;
    float area2 = w2 * h2;
    float union_area = area1 + area2 - inter_area;

    if (union_area <= 0.0f)
        return 0.0f;
    return inter_area / union_area;
}

/* ── 获取活跃轨迹 ──────────────────────────────────────── */
std::vector<DetectBox> Tracker::get_active_tracks() const
{
    std::vector<DetectBox> result;

    for (const auto &track : _tracks) {
        if (!track.is_confirmed() || track.time_since_update > 1)
            continue;

        DetectBox box = track.to_tlwh();  /* 直接返回 (x1,y1,x2,y2) 格式 */
        box.trackID = track.track_id;
        box.classID = track.cls;
        box.confidence = track.conf;
        result.push_back(box);
    }

    return result;
}

std::vector<Track> &Tracker::tracks()
{
    return _tracks;
}