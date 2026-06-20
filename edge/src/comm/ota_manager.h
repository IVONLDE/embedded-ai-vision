/* SPDX-License-Identifier: MIT */
/*
 * OTA Manager — 边缘设备远程升级管理
 *
 * 功能:
 *   - 模型热替换: 接收新模型 → 校验 SHA256 → 备份旧模型 → 原子替换 → 热加载
 *   - 应用二进制 OTA: 下载新版本 → 校验 → 备份 → 替换 → 重启服务
 *   - 版本回滚: 恢复上一版本模型或应用
 *   - 状态上报: 通过 MQTT 上报升级进度和结果
 *
 * 文件布局:
 *   /opt/edge-ai/models/              — 模型目录
 *   /opt/edge-ai/models/.backup/      — 备份目录
 *   /opt/edge-ai/models/.ota_status   — OTA 状态文件
 *   /usr/bin/edge-ai-camera           — 应用二进制
 *   /usr/bin/.backup/                 — 应用备份目录
 */

#ifndef OTA_MANAGER_H
#define OTA_MANAGER_H

#include <string>
#include <functional>
#include <mutex>
#include "../inference/rknn1_engine.h"
#include "../pipeline/pipeline_config.h"

/* OTA 状态 */
enum class OtaStatus {
    IDLE,           /* 空闲 */
    DOWNLOADING,    /* 下载中 */
    VERIFYING,      /* 校验中 */
    BACKING_UP,     /* 备份中 */
    INSTALLING,     /* 安装中 */
    ROLLING_BACK,   /* 回滚中 */
    SUCCESS,        /* 成功 */
    FAILED,         /* 失败 */
};

/* OTA 结果 */
struct OtaResult {
    int status = 0;              /* 0=成功, -1=失败 */
    std::string message;
    std::string version;         /* 当前版本 */
    std::string previous_version;/* 上一版本 (可回滚) */
    bool needs_restart = false;  /* 是否需要重启 */
};

/* MQTT 状态上报回调 */
using OtaStatusCallback = std::function<void(const std::string &status_json)>;

class OtaManager {
public:
    OtaManager(Rknn1Engine *engine, const PipelineConfig *config);
    ~OtaManager() = default;

    /* ── 模型 OTA ─────────────────────────────────────── */

    /* 接收并安装新模型 (从文件路径, SCP 方式) */
    OtaResult install_model(const std::string &model_path,
                            const std::string &model_version,
                            const std::string &sha256_checksum = "",
                            bool auto_rollback = true);

    /* 接收并安装新模型 (从内存字节, gRPC/MQTT 内联方式) */
    OtaResult install_model_from_data(const std::string &model_data,
                                      const std::string &model_name,
                                      const std::string &model_version,
                                      const std::string &sha256_checksum = "",
                                      bool auto_rollback = true);

    /* ── 应用 OTA ─────────────────────────────────────── */

    /* 接收并安装应用更新 */
    OtaResult install_app(const std::string &app_path,
                          const std::string &app_version,
                          const std::string &sha256_checksum = "",
                          bool auto_rollback = true);

    /* ── 回滚 ─────────────────────────────────────── */

    /* 回滚到上一版本 (model 或 app) */
    OtaResult rollback(const std::string &target_type);

    /* ── 查询 ─────────────────────────────────────── */

    /* 获取当前版本信息 */
    std::string get_version_info() const;

    /* 当前 OTA 状态 */
    OtaStatus get_status() const { return _status; }

    /* 设置 MQTT 状态上报回调 */
    void set_status_callback(OtaStatusCallback cb) {
        _status_callback = cb;
    }

    /* 设置 MQTT publisher (用于上报 OTA 状态) */
    void set_mqtt_publish_fn(std::function<bool(const std::string &,
                                                const std::string &)> fn) {
        _mqtt_publish = fn;
    }

private:
    Rknn1Engine *_engine;
    const PipelineConfig *_config;
    std::mutex _mutex;           /* OTA 操作互斥, 防止并发 */
    OtaStatus _status = OtaStatus::IDLE;

    /* 版本记录 (写入 .ota_status 文件持久化) */
    std::string _current_model_version;
    std::string _current_app_version;
    std::string _previous_model_version;
    std::string _previous_app_version;

    /* 状态上报 */
    OtaStatusCallback _status_callback;
    std::function<bool(const std::string &, const std::string &)> _mqtt_publish;

    /* ── 内部方法 ─────────────────────────────────────── */

    /* SHA256 计算 */
    static std::string compute_sha256(const std::string &data);
    static std::string compute_file_sha256(const std::string &path);

    /* 备份文件 */
    static bool backup_file(const std::string &src, const std::string &backup_dir);

    /* 原子替换文件 */
    static bool atomic_replace(const std::string &src, const std::string &dst);

    /* 更新 OTA 状态并上报 */
    void update_status(OtaStatus status, const std::string &message = "");

    /* 持久化版本信息到文件 */
    void save_ota_status() const;

    /* 从文件加载版本信息 */
    void load_ota_status();
};

#endif /* OTA_MANAGER_H */
