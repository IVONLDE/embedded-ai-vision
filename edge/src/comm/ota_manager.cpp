/* SPDX-License-Identifier: MIT */
/*
 * OTA Manager — 边缘设备远程升级管理 (实现)
 *
 * 模型 OTA 流程:
 *   1. 校验 SHA256
 *   2. 备份当前模型到 .backup/ 目录
 *   3. 原子替换 (写入临时文件 → rename)
 *   4. 热加载新模型
 *   5. 如果热加载失败且 auto_rollback=true → 自动恢复备份
 *
 * 应用 OTA 流程:
 *   1. 校验 SHA256
 *   2. 备份当前二进制
 *   3. 原子替换
 *   4. 通知需要重启 (systemd 自动拉起新版本)
 */

#include "ota_manager.h"

#include <cstdio>
#include <cstring>
#include <fstream>
#include <iomanip>
#include <sstream>
#include <sys/stat.h>
#include <unistd.h>
#include <openssl/sha.h>

/* ── 构造 ──────────────────────────────────────────────── */

OtaManager::OtaManager(Rknn1Engine *engine, const PipelineConfig *config)
    : _engine(engine), _config(config)
{
    load_ota_status();
}

/* ── SHA256 计算 ───────────────────────────────────────── */

std::string OtaManager::compute_sha256(const std::string &data)
{
    unsigned char hash[SHA256_DIGEST_LENGTH];
    SHA256(reinterpret_cast<const unsigned char *>(data.c_str()),
           data.size(), hash);

    std::ostringstream oss;
    oss << std::hex << std::setfill('0');
    for (int i = 0; i < SHA256_DIGEST_LENGTH; i++) {
        oss << std::setw(2) << static_cast<int>(hash[i]);
    }
    return oss.str();
}

std::string OtaManager::compute_file_sha256(const std::string &path)
{
    std::ifstream file(path, std::ios::binary);
    if (!file) return "";

    SHA256_CTX ctx;
    SHA256_Init(&ctx);

    char buf[8192];
    while (file.read(buf, sizeof(buf)) || file.gcount() > 0) {
        SHA256_Update(&ctx, buf, file.gcount());
    }

    unsigned char hash[SHA256_DIGEST_LENGTH];
    SHA256_Final(hash, &ctx);

    std::ostringstream oss;
    oss << std::hex << std::setfill('0');
    for (int i = 0; i < SHA256_DIGEST_LENGTH; i++) {
        oss << std::setw(2) << static_cast<int>(hash[i]);
    }
    return oss.str();
}

/* ── 文件操作工具 ──────────────────────────────────────── */

bool OtaManager::backup_file(const std::string &src,
                              const std::string &backup_dir)
{
    /* 创建备份目录 */
    struct stat st = {0};
    if (stat(backup_dir.c_str(), &st) == -1) {
        if (mkdir(backup_dir.c_str(), 0755) != 0) {
            perror("mkdir backup dir failed");
            return false;
        }
    }

    /* 构建备份路径: /opt/edge-ai/models/.backup/yolov5n.rknn.__previous__ */
    std::string filename = src.substr(src.find_last_of('/') + 1);
    std::string backup_path = backup_dir + "/" + filename + ".__previous__";

    /* 复制文件 (不用 rename, 保留原文件) */
    std::ifstream in(src, std::ios::binary);
    std::ofstream out(backup_path, std::ios::binary);
    if (!in || !out) {
        fprintf(stderr, "[OTA] Backup failed: cannot open files\n");
        return false;
    }
    out << in.rdbuf();

    if (!out.good()) {
        fprintf(stderr, "[OTA] Backup write failed\n");
        /* 删除不完整的备份 */
        unlink(backup_path.c_str());
        return false;
    }

    printf("[OTA] Backed up %s -> %s\n", src.c_str(), backup_path.c_str());
    return true;
}

bool OtaManager::atomic_replace(const std::string &src, const std::string &dst)
{
    /* 先写入临时文件, 然后 rename 实现原子替换 */
    std::string tmp_path = dst + ".__tmp__";

    std::ifstream in(src, std::ios::binary);
    std::ofstream out(tmp_path, std::ios::binary);
    if (!in || !out) {
        fprintf(stderr, "[OTA] Atomic replace failed: cannot open files\n");
        return false;
    }
    out << in.rdbuf();
    out.close();

    if (!out.good()) {
        unlink(tmp_path.c_str());
        return false;
    }

    /* 原子 rename */
    if (rename(tmp_path.c_str(), dst.c_str()) != 0) {
        perror("[OTA] rename failed");
        unlink(tmp_path.c_str());
        return false;
    }

    printf("[OTA] Replaced %s\n", dst.c_str());
    return true;
}

/* ── 状态管理 ──────────────────────────────────────────── */

void OtaManager::update_status(OtaStatus status, const std::string &message)
{
    _status = status;

    /* 状态名称映射 */
    static const char *status_names[] = {
        "idle", "downloading", "verifying",
        "backing_up", "installing", "rolling_back",
        "success", "failed"
    };

    int idx = static_cast<int>(status);
    std::ostringstream json;
    json << "{";
    json << "\"device_id\":\"" << _config->device_id << "\",";
    json << "\"ota_status\":\"" << status_names[idx] << "\",";
    json << "\"message\":\"" << message << "\",";
    json << "\"model_version\":\"" << _current_model_version << "\",";
    json << "\"app_version\":\"" << _current_app_version << "\"";
    json << "}";

    /* MQTT 上报 */
    if (_mqtt_publish) {
        std::string topic = "edge/" + _config->device_id + "/ota_status";
        _mqtt_publish(topic, json.str());
    }

    /* 回调通知 */
    if (_status_callback) {
        _status_callback(json.str());
    }
}

/* ── 持久化版本信息 ────────────────────────────────────── */

void OtaManager::save_ota_status() const
{
    std::string path = "/opt/edge-ai/models/.ota_status";
    std::ofstream out(path);
    if (!out) return;

    out << "current_model_version=" << _current_model_version << "\n";
    out << "current_app_version=" << _current_app_version << "\n";
    out << "previous_model_version=" << _previous_model_version << "\n";
    out << "previous_app_version=" << _previous_app_version << "\n";
}

void OtaManager::load_ota_status()
{
    std::string path = "/opt/edge-ai/models/.ota_status";
    std::ifstream in(path);
    if (!in) {
        /* 首次运行, 使用默认值 */
        _current_model_version = "unknown";
        _current_app_version = "1.0.0";
        _previous_model_version = "";
        _previous_app_version = "";
        return;
    }

    std::string line;
    while (std::getline(in, line)) {
        auto eq = line.find('=');
        if (eq == std::string::npos) continue;
        std::string key = line.substr(0, eq);
        std::string val = line.substr(eq + 1);

        if (key == "current_model_version") _current_model_version = val;
        else if (key == "current_app_version") _current_app_version = val;
        else if (key == "previous_model_version") _previous_model_version = val;
        else if (key == "previous_app_version") _previous_app_version = val;
    }
}

/* ── 模型 OTA (从文件) ────────────────────────────────── */

OtaResult OtaManager::install_model(const std::string &model_path,
                                     const std::string &model_version,
                                     const std::string &sha256_checksum,
                                     bool auto_rollback)
{
    std::lock_guard<std::mutex> lock(_mutex);

    OtaResult result;
    update_status(OtaStatus::VERIFYING, "校验模型文件");

    /* 1. SHA256 校验 */
    if (!sha256_checksum.empty()) {
        std::string actual = compute_file_sha256(model_path);
        if (actual != sha256_checksum) {
            update_status(OtaStatus::FAILED, "SHA256 校验失败");
            result.status = -1;
            result.message = "SHA256 mismatch: expected " + sha256_checksum
                           + " got " + actual;
            return result;
        }
        printf("[OTA] SHA256 verified: %s\n", actual.c_str());
    }

    /* 2. 备份当前模型 */
    update_status(OtaStatus::BACKING_UP, "备份当前模型");
    std::string model_dir = "/opt/edge-ai/models";
    std::string current_model = _config->inference.model_path;

    struct stat st;
    if (stat(current_model.c_str(), &st) == 0) {
        if (!backup_file(current_model, model_dir + "/.backup")) {
            update_status(OtaStatus::FAILED, "备份失败");
            result.status = -1;
            result.message = "Failed to backup current model";
            return result;
        }
    }

    /* 3. 原子替换 */
    update_status(OtaStatus::INSTALLING, "安装新模型");
    if (!atomic_replace(model_path, current_model)) {
        update_status(OtaStatus::FAILED, "替换模型文件失败");
        result.status = -1;
        result.message = "Failed to replace model file";
        return result;
    }

    /* 4. 热加载 */
    if (_engine) {
        int ret = _engine->hot_reload_model(current_model.c_str());
        if (ret != 0) {
            fprintf(stderr, "[OTA] Hot-reload failed\n");

            /* 5. 自动回滚 */
            if (auto_rollback) {
                update_status(OtaStatus::ROLLING_BACK, "热加载失败, 自动回滚");
                std::string backup_path = model_dir + "/.backup/"
                    + current_model.substr(current_model.find_last_of('/') + 1)
                    + ".__previous__";

                struct stat bst;
                if (stat(backup_path.c_str(), &bst) == 0) {
                    atomic_replace(backup_path, current_model);
                    _engine->hot_reload_model(current_model.c_str());
                }

                update_status(OtaStatus::FAILED, "热加载失败, 已回滚");
                result.status = -1;
                result.message = "Hot-reload failed, rolled back to previous version";
                return result;
            }

            update_status(OtaStatus::FAILED, "热加载失败");
            result.status = -1;
            result.message = "Hot-reload failed";
            return result;
        }
    }

    /* 6. 更新版本信息 */
    _previous_model_version = _current_model_version;
    _current_model_version = model_version;
    save_ota_status();

    update_status(OtaStatus::SUCCESS, "模型更新成功");

    result.status = 0;
    result.message = "Model updated successfully";
    result.version = model_version;
    result.previous_version = _previous_model_version;
    return result;
}

/* ── 模型 OTA (从内存数据) ────────────────────────────── */

OtaResult OtaManager::install_model_from_data(
    const std::string &model_data,
    const std::string &model_name,
    const std::string &model_version,
    const std::string &sha256_checksum,
    bool auto_rollback)
{
    /* 写入临时文件, 再调用 install_model */
    std::string tmp_path = "/opt/edge-ai/models/.__ota_tmp__" + model_name;
    {
        std::ofstream out(tmp_path, std::ios::binary);
        if (!out) {
            OtaResult result;
            result.status = -1;
            result.message = "Failed to write temp model file";
            return result;
        }
        out.write(model_data.c_str(), model_data.size());
    }

    OtaResult result = install_model(tmp_path, model_version,
                                     sha256_checksum, auto_rollback);

    /* 清理临时文件 */
    unlink(tmp_path.c_str());
    return result;
}

/* ── 应用 OTA ──────────────────────────────────────────── */

OtaResult OtaManager::install_app(const std::string &app_path,
                                   const std::string &app_version,
                                   const std::string &sha256_checksum,
                                   bool auto_rollback)
{
    std::lock_guard<std::mutex> lock(_mutex);

    OtaResult result;
    update_status(OtaStatus::VERIFYING, "校验应用文件");

    /* 1. SHA256 校验 */
    if (!sha256_checksum.empty()) {
        std::string actual = compute_file_sha256(app_path);
        if (actual != sha256_checksum) {
            update_status(OtaStatus::FAILED, "SHA256 校验失败");
            result.status = -1;
            result.message = "SHA256 mismatch";
            return result;
        }
    }

    /* 2. 备份当前二进制 */
    update_status(OtaStatus::BACKING_UP, "备份当前应用");
    std::string app_binary = "/usr/bin/edge-ai-camera";
    std::string backup_dir = "/usr/bin/.backup";

    struct stat st;
    if (stat(app_binary.c_str(), &st) == 0) {
        if (!backup_file(app_binary, backup_dir)) {
            update_status(OtaStatus::FAILED, "备份失败");
            result.status = -1;
            result.message = "Failed to backup app binary";
            return result;
        }
    }

    /* 3. 原子替换 */
    update_status(OtaStatus::INSTALLING, "安装新版本");
    if (!atomic_replace(app_path, app_binary)) {
        update_status(OtaStatus::FAILED, "替换应用文件失败");
        result.status = -1;
        result.message = "Failed to replace app binary";
        return result;
    }

    /* 设置可执行权限 */
    chmod(app_binary.c_str(), 0755);

    /* 4. 更新版本信息 */
    _previous_app_version = _current_app_version;
    _current_app_version = app_version;
    save_ota_status();

    update_status(OtaStatus::SUCCESS, "应用更新成功, 需要重启");

    result.status = 2;  /* 2=需重启 */
    result.message = "App updated, needs restart";
    result.version = app_version;
    result.previous_version = _previous_app_version;
    result.needs_restart = true;
    return result;
}

/* ── 回滚 ──────────────────────────────────────────────── */

OtaResult OtaManager::rollback(const std::string &target_type)
{
    std::lock_guard<std::mutex> lock(_mutex);

    OtaResult result;
    update_status(OtaStatus::ROLLING_BACK, "回滚到上一版本");

    if (target_type == "model") {
        if (_previous_model_version.empty()) {
            update_status(OtaStatus::FAILED, "无可回滚的模型版本");
            result.status = -1;
            result.message = "No previous model version to rollback to";
            return result;
        }

        std::string model_dir = "/opt/edge-ai/models";
        std::string current_model = _config->inference.model_path;
        std::string filename = current_model.substr(
            current_model.find_last_of('/') + 1);
        std::string backup_path = model_dir + "/.backup/"
                                  + filename + ".__previous__";

        struct stat st;
        if (stat(backup_path.c_str(), &st) != 0) {
            update_status(OtaStatus::FAILED, "备份文件不存在");
            result.status = -1;
            result.message = "Backup file not found";
            return result;
        }

        /* 恢复备份 */
        if (!atomic_replace(backup_path, current_model)) {
            update_status(OtaStatus::FAILED, "恢复备份失败");
            result.status = -1;
            result.message = "Failed to restore backup";
            return result;
        }

        /* 热加载恢复的模型 */
        if (_engine) {
            _engine->hot_reload_model(current_model.c_str());
        }

        /* 交换版本号 */
        std::swap(_current_model_version, _previous_model_version);
        save_ota_status();

        update_status(OtaStatus::SUCCESS, "模型回滚成功");

        result.status = 0;
        result.message = "Model rolled back successfully";
        result.version = _current_model_version;
        result.needs_restart = false;

    } else if (target_type == "app") {
        if (_previous_app_version.empty()) {
            update_status(OtaStatus::FAILED, "无可回滚的应用版本");
            result.status = -1;
            result.message = "No previous app version to rollback to";
            return result;
        }

        std::string app_binary = "/usr/bin/edge-ai-camera";
        std::string backup_path = "/usr/bin/.backup/edge-ai-camera.__previous__";

        struct stat st;
        if (stat(backup_path.c_str(), &st) != 0) {
            update_status(OtaStatus::FAILED, "备份文件不存在");
            result.status = -1;
            result.message = "Backup file not found";
            return result;
        }

        if (!atomic_replace(backup_path, app_binary)) {
            update_status(OtaStatus::FAILED, "恢复备份失败");
            result.status = -1;
            result.message = "Failed to restore backup";
            return result;
        }

        chmod(app_binary.c_str(), 0755);

        std::swap(_current_app_version, _previous_app_version);
        save_ota_status();

        update_status(OtaStatus::SUCCESS, "应用回滚成功, 需要重启");

        result.status = 0;
        result.message = "App rolled back, needs restart";
        result.version = _current_app_version;
        result.needs_restart = true;

    } else {
        update_status(OtaStatus::FAILED, "未知回滚类型");
        result.status = -1;
        result.message = "Unknown rollback type: " + target_type;
    }

    return result;
}

/* ── 版本信息查询 ──────────────────────────────────────── */

std::string OtaManager::get_version_info() const
{
    std::ostringstream json;
    json << "{";
    json << "\"device_id\":\"" << _config->device_id << "\",";
    json << "\"app_version\":\"" << _current_app_version << "\",";
    json << "\"model_version\":\"" << _current_model_version << "\",";
    json << "\"previous_model_version\":\"" << _previous_model_version << "\",";
    json << "\"previous_app_version\":\"" << _previous_app_version << "\",";
    json << "\"scene\":\"" << _config->active_scene << "\",";
    json << "\"rollback_available\":"
         << (!_previous_model_version.empty() || !_previous_app_version.empty()
             ? "true" : "false");
    json << "}";
    return json.str();
}
