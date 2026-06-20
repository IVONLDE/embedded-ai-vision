/* SPDX-License-Identifier: MIT */
/*
 * Edge AI Camera — Main Entry Point
 *
 * 嵌入式 AI 边缘推理系统主入口。
 * 支持:
 *   - YAML 配置文件驱动
 *   - 命令行参数覆盖
 *   - systemd Type=notify 集成
 *   - 多场景热切换
 *
 * 用法:
 *   edge-ai-camera --config /opt/edge-ai/config/pipeline.yaml
 *   edge-ai-camera --config pipeline.yaml --scene vehicle
 *   edge-ai-camera --config pipeline.yaml --model /tmp/new_model.rknn
 */

#include "pipeline/pipeline_config.h"
#include "pipeline/pipeline.h"  /* 流水线入口声明 */

#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <getopt.h>
#include <unistd.h>
#include <systemd/sd-daemon.h>

/* ── 命令行选项 ────────────────────────────────────────── */
static struct option long_options[] = {
    {"config",  required_argument, 0, 'c'},
    {"scene",   required_argument, 0, 's'},
    {"model",   required_argument, 0, 'm'},
    {"device",  required_argument, 0, 'd'},
    {"help",    no_argument,       0, 'h'},
    {"version", no_argument,       0, 'v'},
    {0, 0, 0, 0}
};

static void print_usage(const char *prog)
{
    printf("Edge AI Camera — RK3399Pro Embedded Inference System\n");
    printf("Usage: %s [OPTIONS]\n\n", prog);
    printf("Options:\n");
    printf("  -c, --config FILE    YAML configuration file (required)\n");
    printf("  -s, --scene NAME     Active scene (overrides config)\n");
    printf("  -m, --model PATH     Model file path (overrides config)\n");
    printf("  -d, --device ID      Device ID (overrides config)\n");
    printf("  -h, --help           Show this help\n");
    printf("  -v, --version        Show version\n");
}

static void print_version()
{
    printf("edge-ai-camera v1.0.0\n");
    printf("Embedded AI Edge Inference System\n");
    printf("Platform: RK3399Pro (RKNN-Toolkit1)\n");
    printf("Project: https://github.com/IVONLDE/embedded-ai-vision\n");
}

/* ── 主函数 ────────────────────────────────────────────── */
int main(int argc, char *argv[])
{
    const char *config_path = nullptr;
    const char *scene_override = nullptr;
    const char *model_override = nullptr;
    const char *device_override = nullptr;

    /* 解析命令行 */
    int opt;
    while ((opt = getopt_long(argc, argv, "c:s:m:d:hv",
                              long_options, NULL)) != -1) {
        switch (opt) {
        case 'c':
            config_path = optarg;
            break;
        case 's':
            scene_override = optarg;
            break;
        case 'm':
            model_override = optarg;
            break;
        case 'd':
            device_override = optarg;
            break;
        case 'h':
            print_usage(argv[0]);
            return 0;
        case 'v':
            print_version();
            return 0;
        default:
            print_usage(argv[0]);
            return 1;
        }
    }

    if (!config_path) {
        /* 默认配置路径 */
        config_path = "/opt/edge-ai/config/pipeline.yaml";

        /* 检查默认路径是否存在 */
        FILE *fp = fopen(config_path, "r");
        if (!fp) {
            fprintf(stderr, "Error: No config file specified and "
                    "default not found at %s\n", config_path);
            print_usage(argv[0]);
            return 1;
        }
        fclose(fp);
    }

    printf("╔══════════════════════════════════════════════╗\n");
    printf("║  Edge AI Camera v1.0.0                      ║\n");
    printf("║  Platform: RK3399Pro (RKNN-Toolkit1)        ║\n");
    printf("║  Config:   %-32s ║\n", config_path);
    printf("╚══════════════════════════════════════════════╝\n");

    /* 加载配置 */
    PipelineConfig cfg = PipelineConfig::load_from_yaml(config_path);

    /* 命令行覆盖 */
    if (scene_override)
        cfg.active_scene = scene_override;
    if (model_override)
        cfg.inference.model_path = model_override;
    if (device_override)
        cfg.device_id = device_override;

    /* 如果指定了场景, 查找对应模型 */
    if (scene_override) {
        for (const auto &scene : cfg.scenes) {
            if (scene.name == scene_override) {
                cfg.inference.model_path = scene.model_path;
                cfg.inference.labels_path = scene.labels_path;
                cfg.inference.conf_threshold = scene.conf_threshold;
                cfg.tracking.enabled = scene.tracking_enabled;
                printf("[Main] Scene '%s': model=%s, tracking=%s\n",
                       scene.name.c_str(),
                       scene.model_path.c_str(),
                       scene.tracking_enabled ? "on" : "off");
                break;
            }
        }
    }

    /* ── systemd 通知: 服务就绪 ── */
    char notify_buf[256]; snprintf(notify_buf, sizeof(notify_buf), "READY=1\nSTATUS=Edge AI Camera running\nMAINPID=%lu", (unsigned long)getpid()); sd_notify(0, notify_buf);

    printf("[Main] Systemd notification sent: READY=1\n");

    /* ── 启动流水线 ── */
    int ret = pipeline_run(cfg);

    /* ── systemd 通知: 服务停止 ── */
    sd_notify(0, "STOPPING=1\n"
                 "STATUS=Shutting down");

    return ret;
}
