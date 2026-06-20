/* SPDX-License-Identifier: MIT */
/*
 * Pipeline Configuration — YAML 解析实现
 *
 * 使用 yaml-cpp 库从 YAML 文件加载 PipelineConfig。
 */

#include "pipeline_config.h"

#include <yaml-cpp/yaml.h>
#include <cstdio>
#include <iostream>
#include <fstream>

/* ── YAML → PipelineConfig ──────────────────────────────── */
PipelineConfig PipelineConfig::load_from_yaml(const std::string &yaml_path)
{
    PipelineConfig cfg;

    try {
        YAML::Node root = YAML::LoadFile(yaml_path);

        /* 顶层字段 */
        if (root["config_version"])
            cfg.config_version = root["config_version"].as<std::string>();
        if (root["device_id"])
            cfg.device_id = root["device_id"].as<std::string>();
        if (root["active_scene"])
            cfg.active_scene = root["active_scene"].as<std::string>();

        /* ── 输入源配置 ── */
        if (root["input"]) {
            auto in = root["input"];
            if (in["type"]) {
                std::string t = in["type"].as<std::string>();
                if (t == "v4l2_camera")
                    cfg.input.type = InputType::V4L2_CAMERA;
                else if (t == "rtsp_stream")
                    cfg.input.type = InputType::RTSP_STREAM;
                else if (t == "video_file")
                    cfg.input.type = InputType::VIDEO_FILE;
            }
            if (in["v4l2_device"])
                cfg.input.v4l2_device = in["v4l2_device"].as<std::string>();
            if (in["v4l2_width"])
                cfg.input.v4l2_width = in["v4l2_width"].as<int>();
            if (in["v4l2_height"])
                cfg.input.v4l2_height = in["v4l2_height"].as<int>();
            if (in["v4l2_fps"])
                cfg.input.v4l2_fps = in["v4l2_fps"].as<int>();
            if (in["v4l2_format"])
                cfg.input.v4l2_format = in["v4l2_format"].as<std::string>();
            if (in["rtsp_url"])
                cfg.input.rtsp_url = in["rtsp_url"].as<std::string>();
            if (in["file_path"])
                cfg.input.file_path = in["file_path"].as<std::string>();
        }

        /* ── 推理配置 ── */
        if (root["inference"]) {
            auto inf = root["inference"];
            if (inf["model_path"])
                cfg.inference.model_path = inf["model_path"].as<std::string>();
            if (inf["labels_path"])
                cfg.inference.labels_path = inf["labels_path"].as<std::string>();
            if (inf["det_interval"])
                cfg.inference.det_interval = inf["det_interval"].as<int>();
            if (inf["conf_threshold"])
                cfg.inference.conf_threshold = inf["conf_threshold"].as<float>();
            if (inf["nms_threshold"])
                cfg.inference.nms_threshold = inf["nms_threshold"].as<float>();
            if (inf["cpu_id"])
                cfg.inference.cpu_id = inf["cpu_id"].as<int>();
        }

        /* ── 跟踪配置 ── */
        if (root["tracking"]) {
            auto trk = root["tracking"];
            if (trk["enabled"])
                cfg.tracking.enabled = trk["enabled"].as<bool>();
            if (trk["algorithm"])
                cfg.tracking.algorithm = trk["algorithm"].as<std::string>();
            if (trk["max_age"])
                cfg.tracking.max_age = trk["max_age"].as<int>();
            if (trk["n_init"])
                cfg.tracking.n_init = trk["n_init"].as<int>();
            if (trk["max_iou_distance"])
                cfg.tracking.max_iou_distance = trk["max_iou_distance"].as<float>();
            if (trk["cpu_id"])
                cfg.tracking.cpu_id = trk["cpu_id"].as<int>();
        }

        /* ── 输出配置 ── */
        if (root["output"]) {
            auto out = root["output"];
            if (out["save_video"])
                cfg.output.save_video = out["save_video"].as<bool>();
            if (out["video_path"])
                cfg.output.video_path = out["video_path"].as<std::string>();
            if (out["enable_rtsp"])
                cfg.output.enable_rtsp = out["enable_rtsp"].as<bool>();
            if (out["rtsp_port"])
                cfg.output.rtsp_port = out["rtsp_port"].as<int>();
            if (out["rtsp_mount"])
                cfg.output.rtsp_mount = out["rtsp_mount"].as<std::string>();
            if (out["enable_display"])
                cfg.output.enable_display = out["enable_display"].as<bool>();
        }

        /* ── MQTT 配置 ── */
        if (root["mqtt"]) {
            auto mq = root["mqtt"];
            if (mq["enabled"])
                cfg.mqtt.enabled = mq["enabled"].as<bool>();
            if (mq["broker_host"])
                cfg.mqtt.broker_host = mq["broker_host"].as<std::string>();
            if (mq["broker_port"])
                cfg.mqtt.broker_port = mq["broker_port"].as<int>();
            if (mq["client_id"])
                cfg.mqtt.client_id = mq["client_id"].as<std::string>();
            if (mq["topic_detections"])
                cfg.mqtt.topic_detections = mq["topic_detections"].as<std::string>();
            if (mq["topic_health"])
                cfg.mqtt.topic_health = mq["topic_health"].as<std::string>();
            if (mq["topic_command"])
                cfg.mqtt.topic_command = mq["topic_command"].as<std::string>();
            if (mq["keepalive"])
                cfg.mqtt.keepalive = mq["keepalive"].as<int>();
            if (mq["qos"])
                cfg.mqtt.qos = mq["qos"].as<int>();
        }

        /* ── gRPC 配置 ── */
        if (root["grpc"]) {
            auto gc = root["grpc"];
            if (gc["enabled"])
                cfg.grpc.enabled = gc["enabled"].as<bool>();
            if (gc["listen_address"])
                cfg.grpc.listen_address = gc["listen_address"].as<std::string>();
            if (gc["unix_socket"])
                cfg.grpc.unix_socket = gc["unix_socket"].as<std::string>();
        }

        /* ── 系统配置 ── */
        if (root["system"]) {
            auto sys = root["system"];
            if (sys["cpu_read"])
                cfg.system.cpu_read = sys["cpu_read"].as<int>();
            if (sys["cpu_inference"])
                cfg.system.cpu_inference = sys["cpu_inference"].as<int>();
            if (sys["cpu_tracking"])
                cfg.system.cpu_tracking = sys["cpu_tracking"].as<int>();
            if (sys["cpu_output"])
                cfg.system.cpu_output = sys["cpu_output"].as<int>();
            if (sys["queue_max_size"])
                cfg.system.queue_max_size = sys["queue_max_size"].as<int>();
            if (sys["ring_buffer_frames"])
                cfg.system.ring_buffer_frames = sys["ring_buffer_frames"].as<int>();
            if (sys["log_path"])
                cfg.system.log_path = sys["log_path"].as<std::string>();
            if (sys["log_rotation_days"])
                cfg.system.log_rotation_days = sys["log_rotation_days"].as<int>();
        }

        /* ── 多场景配置 ── */
        if (root["scenes"] && root["scenes"].IsSequence()) {
            for (const auto &s : root["scenes"]) {
                SceneConfig sc;
                if (s["name"])
                    sc.name = s["name"].as<std::string>();
                if (s["model_path"])
                    sc.model_path = s["model_path"].as<std::string>();
                if (s["labels_path"])
                    sc.labels_path = s["labels_path"].as<std::string>();
                if (s["conf_threshold"])
                    sc.conf_threshold = s["conf_threshold"].as<float>();
                if (s["tracking_enabled"])
                    sc.tracking_enabled = s["tracking_enabled"].as<bool>();
                cfg.scenes.push_back(sc);
            }
        }

        printf("[Config] Loaded %s: device=%s, scenes=%zu, model=%s\n",
               yaml_path.c_str(),
               cfg.device_id.c_str(),
               cfg.scenes.size(),
               cfg.inference.model_path.c_str());

    } catch (const YAML::Exception &e) {
        std::cerr << "[Config] YAML parse error in " << yaml_path
                  << ": " << e.what() << std::endl;
        throw std::runtime_error(std::string("Failed to parse config: ") + e.what());
    }

    return cfg;
}

/* ── 命令行覆盖 ──────────────────────────────────────────── */
void PipelineConfig::apply_cli_overrides(int argc, char *argv[])
{
    /* 命令行覆盖由 main.cpp 中的 getopt_long 直接处理,
     * 此方法保留用于编程式接口。
     */
    (void)argc;
    (void)argv;
}