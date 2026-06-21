/* SPDX-License-Identifier: MIT */
/*
 * Pipeline Configuration — 运行时配置结构体
 *
 * 从 YAML 配置文件解析, 替代原有硬编码参数。
 * 使用 yaml-cpp 库解析。
 */

#ifndef PIPELINE_CONFIG_H
#define PIPELINE_CONFIG_H

#include <string>
#include <vector>

/* ── 输入源配置 ────────────────────────────────────────── */
enum class InputType {
    V4L2_CAMERA,    /* V4L2 摄像头 (DMA-BUF 零拷贝) */
    RTSP_STREAM,    /* RTSP 网络流 */
    VIDEO_FILE,     /* 本地视频文件 */
};

struct InputConfig {
    InputType type = InputType::V4L2_CAMERA;

    /* V4L2 配置 */
    std::string v4l2_device = "/dev/video0";
    int v4l2_width = 1920;
    int v4l2_height = 1080;
    int v4l2_fps = 30;
    std::string v4l2_format = "NV12";  /* NV12 / YUYV / RGB */

    /* RTSP 配置 */
    std::string rtsp_url;

    /* 文件配置 */
    std::string file_path;
};

/* ── 推理配置 ──────────────────────────────────────────── */
struct InferenceConfig {
    std::string model_path = "/opt/edge-ai/models/yolov5.rknn";
    std::string labels_path = "/opt/edge-ai/models/labels.txt";
    int det_interval = 1;       /* 隔帧检测间隔 */
    float conf_threshold = 0.3; /* 置信度阈值 */
    float nms_threshold = 0.45; /* NMS IoU 阈值 */
    int cpu_id = 4;             /* NPU 推理线程绑定的 CPU (A72) */
};

/* ── 跟踪配置 ──────────────────────────────────────────── */
struct TrackingConfig {
    bool enabled = true;        /* 是否启用跟踪 */
    std::string algorithm = "SORT";  /* SORT / ByteTrack */
    int max_age = 30;           /* 轨迹最大丢失帧数 */
    int n_init = 2;             /* 确认轨迹所需连续命中帧数 */
    float max_iou_distance = 0.7;  /* IoU 匹配阈值 */
    int cpu_id = 5;             /* 跟踪线程绑定的 CPU (A72) */
};

/* ── 输出配置 ──────────────────────────────────────────── */
struct OutputConfig {
    bool save_video = false;
    std::string video_path = "/data/results.mp4";
    std::string video_codec = "h264";      /* "h264" 或 "h265" */
    int video_bitrate_kbps = 4000;         /* 4Mbps */
    int video_gop = 30;                    /* 关键帧间隔 */

    bool enable_rtsp = false;
    int rtsp_port = 8554;
    std::string rtsp_mount = "/edge_camera";
    std::string rtsp_codec = "h264";

    bool enable_display = false;
};

/* ── MQTT 配置 ──────────────────────────────────────────── */
struct MqttConfig {
    bool enabled = true;
    std::string broker_host = "192.168.1.100";
    int broker_port = 1883;
    std::string client_id = "rk3399pro-edge-001";
    std::string topic_detections = "edge/rk3399pro-001/detections";
    std::string topic_health = "edge/rk3399pro-001/health";
    std::string topic_command = "edge/rk3399pro-001/command";
    int keepalive = 60;
    int qos = 1;
};

/* ── gRPC 配置 ──────────────────────────────────────────── */
struct GrpcConfig {
    bool enabled = true;
    std::string listen_address = "0.0.0.0:50051";
    std::string unix_socket = "/tmp/edge-ai-grpc.sock";
};

/* ── 系统配置 ──────────────────────────────────────────── */
struct SystemConfig {
    int cpu_read = 1;           /* 视频读取线程 CPU */
    int cpu_inference = 4;      /* NPU 推理线程 CPU */
    int cpu_tracking = 5;       /* 跟踪线程 CPU */
    int cpu_output = 0;         /* 输出线程 CPU */

    int queue_max_size = 16;    /* 线程间队列最大长度 */
    int ring_buffer_frames = 8; /* 环形缓冲帧数 */

    std::string log_path = "/var/log/edge-ai/";
    int log_rotation_days = 7;
};

/* ── 场景配置 (多场景切换) ─────────────────────────────── */
struct SceneConfig {
    std::string name;           /* 场景名称: face/body/vehicle/defect */
    std::string model_path;     /* 对应模型路径 */
    std::string labels_path;    /* 对应标签路径 */
    float conf_threshold;       /* 场景特定阈值 */
    bool tracking_enabled;      /* 是否启用跟踪 */
};

/* ── 总配置 ────────────────────────────────────────────── */
struct PipelineConfig {
    std::string config_version = "1.0";
    std::string device_id = "rk3399pro-edge-001";

    InputConfig input;
    InferenceConfig inference;
    TrackingConfig tracking;
    OutputConfig output;
    MqttConfig mqtt;
    GrpcConfig grpc;
    SystemConfig system;

    /* 多场景支持 */
    std::vector<SceneConfig> scenes;
    std::string active_scene;   /* 当前活跃场景 */

    /* 从 YAML 文件加载 */
    static PipelineConfig load_from_yaml(const std::string &yaml_path);

    /* 从命令行参数覆盖 */
    void apply_cli_overrides(int argc, char *argv[]);
};

#endif /* PIPELINE_CONFIG_H */
