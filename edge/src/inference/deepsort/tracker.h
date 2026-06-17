/* SPDX-License-Identifier: MIT */
/*
 * SORT Tracker — Header
 *
 * 纯 CPU 卡尔曼滤波 + 匈牙利匹配，适配 RK3399Pro 单核 NPU。
 */

#ifndef TRACKER_H
#define TRACKER_H

#include <vector>
#include <Eigen/Dense>

/* ── 检测框 (与原项目 box.h 兼容) ──────────────────────── */
struct DetectBox {
    float x1, y1, x2, y2;
    float confidence;
    float classID;
    float trackID = -1;

    DetectBox() : x1(0), y1(0), x2(0), y2(0),
                  confidence(0), classID(-1), trackID(-1) {}
    DetectBox(float _x1, float _y1, float _x2, float _y2,
              float _conf = 0, float _cls = -1)
        : x1(_x1), y1(_y1), x2(_x2), y2(_y2),
          confidence(_conf), classID(_cls), trackID(-1) {}
};

/* ── 卡尔曼滤波器 ──────────────────────────────────────── */
/* 状态: [x, y, a, h, vx, vy, va, vh] — 8维 */
typedef Eigen::Matrix<float, 1, 8, Eigen::RowMajor> KAL_MEAN;
typedef Eigen::Matrix<float, 8, 8, Eigen::RowMajor> KAL_COVA;

class KalmanFilter {
public:
    KalmanFilter();
    KAL_MEAN initiate(float cx, float cy, float aspect, float h);
    void predict(KAL_MEAN &mean, KAL_COVA &covariance);
    void update(KAL_MEAN &mean, KAL_COVA &covariance,
                float cx, float cy, float aspect, float h);

private:
    Eigen::Matrix<float, 8, 8> _motion_mat;   /* 状态转移矩阵 F */
    Eigen::Matrix<float, 4, 8> _update_mat;   /* 观测矩阵 H */
    Eigen::Matrix<float, 8, 8> _motion_cov;   /* 过程噪声 Q */
    Eigen::Matrix<float, 4, 4> _update_cov;   /* 观测噪声 R */
    float _std_weight_position;
    float _std_weight_velocity;
};

/* ── 轨迹 ──────────────────────────────────────────────── */
class Track {
public:
    enum TrackState { Tentative = 1, Confirmed, Deleted };

    Track(KAL_MEAN mean, int track_id, int n_init, int max_age,
          int cls = -1, float conf = 0.0f);
    ~Track() = default;

    void predict(KalmanFilter &kf);
    void update(KalmanFilter &kf, const DetectBox &det);
    void mark_missed();
    bool is_confirmed() const { return state == Confirmed; }
    bool is_deleted() const { return state == Deleted; }
    bool is_tentative() const { return state == Tentative; }
    DetectBox to_tlwh() const;
    void get_bbox(float &x, float &y, float &w, float &h) const;

    int track_id;
    int time_since_update;
    int hits;
    int age;
    int cls;
    float conf;
    TrackState state;

private:
    KAL_MEAN _mean;
    KAL_COVA _covariance;
    int _n_init;
    int _max_age;
};

/* ── SORT 跟踪器 ───────────────────────────────────────── */
class Tracker {
public:
    Tracker(float max_iou_distance = 0.7f, int max_age = 30, int n_init = 2);

    void predict();
    void update(const std::vector<DetectBox> &detections);
    std::vector<DetectBox> get_active_tracks() const;
    std::vector<Track> &tracks();

private:
    struct MatchPair {
        int track_idx;
        int det_idx;
    };
    struct MatchResult {
        std::vector<MatchPair> matches;
        std::vector<int> unmatched_tracks;
        std::vector<int> unmatched_tracks2;
        std::vector<int> unmatched_detections;
    };

    MatchResult cascade_match(const std::vector<int> &track_indices,
                              const std::vector<DetectBox> &detections);
    MatchResult iou_match(const std::vector<int> &track_indices,
                          const std::vector<int> &det_indices,
                          const std::vector<DetectBox> &detections);
    Eigen::MatrixXf build_iou_matrix(const std::vector<int> &track_indices,
                                     const std::vector<int> &det_indices,
                                     const std::vector<DetectBox> &detections);
    static float compute_iou(float x1, float y1, float w1, float h1,
                             float x2, float y2, float w2, float h2);

    float _max_iou_distance;
    int _max_age;
    int _n_init;
    int _next_id;
    KalmanFilter _kf;
    std::vector<Track> _tracks;
};

#endif /* TRACKER_H */