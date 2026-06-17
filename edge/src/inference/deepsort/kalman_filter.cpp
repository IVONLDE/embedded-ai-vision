/* SPDX-License-Identifier: MIT */
/*
 * Kalman Filter Implementation for SORT
 */

#include "tracker.h"
#include <cmath>

KalmanFilter::KalmanFilter()
    : _std_weight_position(1.0f / 20.0f)
    , _std_weight_velocity(1.0f / 160.0f)
{
    /* 状态转移矩阵 (8×8): x' = F * x */
    _motion_mat = Eigen::Matrix<float, 8, 8>::Identity();
    _motion_mat(0, 4) = 1.0f;
    _motion_mat(1, 5) = 1.0f;
    _motion_mat(2, 6) = 1.0f;
    _motion_mat(3, 7) = 1.0f;

    /* 观测矩阵 (4×8): z = H * x */
    _update_mat = Eigen::Matrix<float, 4, 8>::Zero();
    _update_mat(0, 0) = 1.0f;
    _update_mat(1, 1) = 1.0f;
    _update_mat(2, 2) = 1.0f;
    _update_mat(3, 3) = 1.0f;
}

KAL_MEAN KalmanFilter::initiate(float cx, float cy, float aspect, float h)
{
    KAL_MEAN mean = KAL_MEAN::Zero();
    mean(0) = cx;
    mean(1) = cy;
    mean(2) = aspect;
    mean(3) = h;
    return mean;
}

void KalmanFilter::predict(KAL_MEAN &mean, KAL_COVA &covariance)
{
    float std_pos = _std_weight_position * mean(3);    /* std = w * h */
    float std_vel = _std_weight_velocity * mean(3);

    /* 过程噪声 Q */
    _motion_cov = Eigen::Matrix<float, 8, 8>::Identity();
    _motion_cov(0, 0) = std_pos * std_pos;
    _motion_cov(1, 1) = std_pos * std_pos;
    _motion_cov(2, 2) = 1e-2f;
    _motion_cov(3, 3) = std_pos * std_pos;
    _motion_cov(4, 4) = std_vel * std_vel;
    _motion_cov(5, 5) = std_vel * std_vel;
    _motion_cov(6, 6) = 1e-5f;
    _motion_cov(7, 7) = std_vel * std_vel;

    mean = _motion_mat * mean;
    covariance = _motion_mat * covariance * _motion_mat.transpose() + _motion_cov;
}

void KalmanFilter::update(KAL_MEAN &mean, KAL_COVA &covariance,
                          float cx, float cy, float aspect, float h)
{
    Eigen::Matrix<float, 4, 1> measurement;
    measurement << cx, cy, aspect, h;

    /* 观测噪声 R */
    float std_pos = _std_weight_position * mean(3);
    _update_cov = Eigen::Matrix<float, 4, 4>::Identity();
    _update_cov(0, 0) = std_pos * std_pos;
    _update_cov(1, 1) = std_pos * std_pos;
    _update_cov(2, 2) = 1e-2f;
    _update_cov(3, 3) = std_pos * std_pos;

    /* 卡尔曼增益 K = P * H^T * (H * P * H^T + R)^(-1) */
    Eigen::Matrix<float, 4, 8> H = _update_mat;
    Eigen::Matrix<float, 4, 4> S = H * covariance * H.transpose() + _update_cov;
    Eigen::Matrix<float, 8, 4> K = covariance * H.transpose() * S.inverse();

    /* 更新 */
    Eigen::Matrix<float, 4, 1> y = measurement - H * mean;
    mean = mean + K * y;

    Eigen::Matrix<float, 8, 8> I = Eigen::Matrix<float, 8, 8>::Identity();
    covariance = (I - K * H) * covariance;
}

/* ── Track ──────────────────────────────────────────────── */

Track::Track(KAL_MEAN mean, int track_id, int n_init, int max_age,
             int cls, float conf)
    : _mean(mean)
    , track_id(track_id)
    , time_since_update(0)
    , hits(0)
    , age(0)
    , cls(cls)
    , conf(conf)
    , state(Tentative)
    , _n_init(n_init)
    , _max_age(max_age)
{
    _covariance = Eigen::Matrix<float, 8, 8>::Identity() * 10.0f;
}

void Track::predict(KalmanFilter &kf)
{
    kf.predict(_mean, _covariance);
    age++;
    time_since_update++;
}

void Track::update(KalmanFilter &kf, const DetectBox &det)
{
    float w = det.x2 - det.x1;
    float h = det.y2 - det.y1;
    float cx = det.x1 + w / 2.0f;
    float cy = det.y1 + h / 2.0f;
    float aspect = w / (h + 1e-6f);

    kf.update(_mean, _covariance, cx, cy, aspect, h);
    cls = (int)det.classID;
    conf = det.confidence;

    hits++;
    time_since_update = 0;
    if (state == Tentative && hits >= _n_init)
        state = Confirmed;
}

void Track::mark_missed()
{
    time_since_update++;
    if (time_since_update > _max_age)
        state = Deleted;
}

DetectBox Track::to_tlwh() const
{
    DetectBox box;
    box.x1 = _mean(0) - _mean(2) * _mean(3) / 2.0f;
    box.y1 = _mean(1) - _mean(3) / 2.0f;
    box.x2 = _mean(0) + _mean(2) * _mean(3) / 2.0f;
    box.y2 = _mean(1) + _mean(3) / 2.0f;
    box.trackID = track_id;
    box.classID = cls;
    box.confidence = conf;
    return box;
}

void Track::get_bbox(float &x, float &y, float &w, float &h) const
{
    x = _mean(0) - _mean(2) * _mean(3) / 2.0f;
    y = _mean(1) - _mean(3) / 2.0f;
    w = _mean(2) * _mean(3);
    h = _mean(3);
}