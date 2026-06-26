#!/bin/bash
# RK3399Pro 边缘 AI 平台性能测试脚本
# 运行方式: ./run_all_benchmarks.sh [实验编号]
# 例如: ./run_all_benchmarks.sh 1 2 3

BOARD_USER="toybrick"
BOARD_IP="192.168.1.200"
SSH_OPTS="-o ConnectTimeout=5 -o StrictHostKeyChecking=no -o BatchMode=yes"
RKNN_LIB_DIR="/home/toybrick/RK3399Pro_npu/rknn-api/librknn_api/Linux/lib64"
MODEL_PATH="/opt/edge-ai/models/yolov5n.rknn"
RESULTS_DIR="/tmp/benchmark_results_$(date +%Y%m%d_%H%M%S)"

# 颜色输出
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

log_info() { echo -e "${GREEN}[INFO]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

# 检查 SSH 连接
check_ssh() {
    log_info "检查 SSH 连接..."
    ssh $SSH_OPTS $BOARD_USER@$BOARD_IP "echo 'SSH OK'" 2>&1 | grep -q "SSH OK" && {
        log_info "SSH 连接正常"
        return 0
    } || {
        log_error "SSH 连接失败"
        return 1
    }
}

# 实验 1: NPU 推理延迟测量
run_exp1_npu_latency() {
    log_info "=== 实验 1: NPU 推理延迟测量 ==="

    # 创建测试程序
    cat > /tmp/test_npu_latency.cpp << 'EOF'
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <sys/time.h>
#include <rknn_api.h>

#define TEST_ITERATIONS 200
#define WARMUP_ITERATIONS 10
#define MODEL_PATH "/opt/edge-ai/models/yolov5n.rknn"
#define INPUT_WIDTH 640
#define INPUT_HEIGHT 640
#define INPUT_CHANNELS 3

// 快速排序用于计算百分位
int compare_float(const void *a, const void *b) {
    float fa = *(const float*)a;
    float fb = *(const float*)b;
    return (fa > fb) - (fa < fb);
}

int main() {
    rknn_context ctx;
    FILE *fp = fopen(MODEL_PATH, "rb");
    if (!fp) {
        fprintf(stderr, "Error: Cannot open model file %s\n", MODEL_PATH);
        return -1;
    }

    fseek(fp, 0, SEEK_END);
    int model_len = ftell(fp);
    fseek(fp, 0, SEEK_SET);
    char *model_data = (char*)malloc(model_len);
    fread(model_data, 1, model_len, fp);
    fclose(fp);

    int ret = rknn_init(&ctx, model_data, model_len, 0, NULL);
    if (ret < 0) {
        fprintf(stderr, "Error: rknn_init failed: %d\n", ret);
        free(model_data);
        return -1;
    }
    printf("[INFO] RKNN context initialized\n");

    rknn_input_output_num io_num;
    ret = rknn_query(ctx, RKNN_QUERY_IN_OUT_NUM, &io_num, sizeof(io_num));
    if (ret < 0) {
        fprintf(stderr, "Error: rknn_query failed\n");
        rknn_destroy(ctx);
        free(model_data);
        return -1;
    }
    printf("[INFO] Model has %d inputs, %d outputs\n", io_num.n_input, io_num.n_output);

    rknn_input inputs[1];
    memset(inputs, 0, sizeof(inputs));
    inputs[0].index = 0;
    inputs[0].type = RKNN_INPUT_TYPE_UINT8;
    inputs[0].size = INPUT_WIDTH * INPUT_HEIGHT * INPUT_CHANNELS;
    inputs[0].fmt = RKNN_INPUT_FMT_RGB;
    inputs[0].buf = malloc(INPUT_WIDTH * INPUT_HEIGHT * INPUT_CHANNELS);
    memset(inputs[0].buf, 128, INPUT_WIDTH * INPUT_HEIGHT * INPUT_CHANNELS);

    // 预热
    printf("[INFO] Warming up (%d iterations)...\n", WARMUP_ITERATIONS);
    for (int i = 0; i < WARMUP_ITERATIONS; i++) {
        rknn_inputs_set(ctx, io_num.n_input, inputs);
        rknn_run(ctx, NULL);
    }

    // 正式测试
    printf("[INFO] Running benchmark (%d iterations)...\n", TEST_ITERATIONS);
    float latencies[TEST_ITERATIONS];
    struct timespec ts1, ts2;

    for (int i = 0; i < TEST_ITERATIONS; i++) {
        clock_gettime(CLOCK_MONOTONIC, &ts1);
        rknn_inputs_set(ctx, io_num.n_input, inputs);
        rknn_run(ctx, NULL);
        clock_gettime(CLOCK_MONOTONIC, &ts2);

        latencies[i] = (ts2.tv_sec - ts1.tv_sec) * 1000.0 +
                       (ts2.tv_nsec - ts1.tv_nsec) / 1000000.0;
    }

    // 排序用于百分位计算
    qsort(latencies, TEST_ITERATIONS, sizeof(float), compare_float);

    // 计算统计值
    double sum = 0, min = latencies[0], max = latencies[0];
    for (int i = 0; i < TEST_ITERATIONS; i++) {
        sum += latencies[i];
        if (latencies[i] < min) min = latencies[i];
        if (latencies[i] > max) max = latencies[i];
    }
    double avg = sum / TEST_ITERATIONS;

    double variance = 0;
    for (int i = 0; i < TEST_ITERATIONS; i++) {
        variance += (latencies[i] - avg) * (latencies[i] - avg);
    }
    double stddev = sqrt(variance / TEST_ITERATIONS);

    // 输出结果
    printf("\n");
    printf("╔══════════════════════════════════════════════════════╗\n");
    printf("║        NPU Inference Latency (YOLOv5n 640x640)       ║\n");
    printf("╠══════════════════════════════════════════════════════╣\n");
    printf("║  Iterations:    %-37d ║\n", TEST_ITERATIONS);
    printf("║  Average:       %-37.2f ║\n", avg);
    printf("║  Min:           %-37.2f ║\n", min);
    printf("║  Max:           %-37.2f ║\n", max);
    printf("║  Stddev:        %-37.2f ║\n", stddev);
    printf("║  P50 (Median):  %-37.2f ║\n", latencies[(int)(TEST_ITERATIONS * 0.50)]);
    printf("║  P90:           %-37.2f ║\n", latencies[(int)(TEST_ITERATIONS * 0.90)]);
    printf("║  P95:           %-37.2f ║\n", latencies[(int)(TEST_ITERATIONS * 0.95)]);
    printf("║  P99:           %-37.2f ║\n", latencies[(int)(TEST_ITERATIONS * 0.99)]);
    printf("╠══════════════════════════════════════════════════════╣\n");
    printf("║  Target: < 40ms, Stddev < 5ms                        ║\n");
    printf("║  Result: %-44s ║\n", (avg < 40.0 && stddev < 5.0) ? "PASS ✓" : "FAIL ✗");
    printf("╚══════════════════════════════════════════════════════╝\n");

    rknn_destroy(ctx);
    free(model_data);
    free(inputs[0].buf);
    return 0;
}
EOF

    # 上传并编译
    log_info "上传测试程序到板子..."
    scp $SSH_OPTS /tmp/test_npu_latency.cpp $BOARD_USER@$BOARD_IP:/tmp/

    log_info "在板子上编译测试程序..."
    ssh $SSH_OPTS $BOARD_USER@$BOARD_IP "cd /tmp && g++ -o test_npu_latency test_npu_latency.cpp -I/home/toybrick/RK3399Pro_npu/rknn-api/librknn_api/Linux/include -L$RKNN_LIB_DIR -lrknn_api -lrt -lpthread 2>&1"

    # 运行测试
    log_info "运行 NPU 推理延迟测试..."
    ssh $SSH_OPTS $BOARD_USER@$BOARD_IP "export LD_LIBRARY_PATH=$RKNN_LIB_DIR:\$LD_LIBRARY_PATH && /tmp/test_npu_latency" 2>&1
}

# 实验 5: 启动时间测量
run_exp5_boot_time() {
    log_info "=== 实验 5: 系统启动时间测量 ==="

    ssh $SSH_OPTS $BOARD_USER@$BOARD_IP << 'REMOTE_EOF'
echo "╔══════════════════════════════════════════════════════╗"
echo "║           System Boot Time Analysis                  ║"
echo "╠══════════════════════════════════════════════════════╣"
echo ""

echo "--- systemd-analyze time ---"
systemd-analyze time

echo ""
echo "--- Top 10 Slowest Services ---"
systemd-analyze blame | head -10

echo ""
echo "--- Kernel Command Line ---"
cat /proc/cmdline

echo ""
echo "--- CPU Isolation Status ---"
echo "Isolated CPUs: $(cat /sys/devices/system/cpu/isolated 2>/dev/null || echo 'none')"
echo "Online CPUs: $(cat /sys/devices/system/cpu/online)"

echo ""
echo "--- CMA Memory ---"
cat /proc/meminfo | grep -i cma

echo ""
echo "╠══════════════════════════════════════════════════════╣"
echo "║  Target: Total boot time < 5s                        ║"
echo "║  Current: ~21s (see systemd-analyze time above)      ║"
echo "║  Note: rknn-npu.service takes 13.5s, main bottleneck ║"
echo "╚══════════════════════════════════════════════════════╝"
REMOTE_EOF
}

# 实验 6: 镜像体积分析
run_exp6_image_size() {
    log_info "=== 实验 6: 镜像体积分析 ==="

    ssh $SSH_OPTS $BOARD_USER@$BOARD_IP << 'REMOTE_EOF'
echo "╔══════════════════════════════════════════════════════╗"
echo "║           Storage and Package Analysis                ║"
echo "╠══════════════════════════════════════════════════════╣"
echo ""

echo "--- Disk Usage ---"
df -h | grep -E "Filesystem|mmcblk"

echo ""
echo "--- Directory Sizes ---"
du -sh /* 2>/dev/null | sort -hr | head -15

echo ""
echo "--- Largest Packages (by installed size) ---"
dpkg-query -W --showformat='${Package}\t${Installed-Size}\n' 2>/dev/null | sort -k2 -hr | head -15 | awk '{printf "%-30s %s KB\n", $1, $2}'

echo ""
echo "--- /opt/edge-ai Size ---"
du -sh /opt/edge-ai 2>/dev/null || echo "N/A"

echo ""
echo "╠══════════════════════════════════════════════════════╣"
echo "║  Note: Need comparison with default buildroot image   ║"
echo "║  to calculate 30% reduction claim                    ║"
echo "╚══════════════════════════════════════════════════════╝"
REMOTE_EOF
}

# 实验 7: cyclictest 中断延迟
run_exp7_cyclictest() {
    log_info "=== 实验 7: 中断响应延迟测量 (cyclictest) ==="

    ssh $SSH_OPTS $BOARD_USER@$BOARD_IP << 'REMOTE_EOF'
echo "╔══════════════════════════════════════════════════════╗"
echo "║           Cyclictest Latency Measurement             ║"
echo "╠══════════════════════════════════════════════════════╣"
echo ""

# 检查 cyclictest 是否可用
if ! command -v cyclictest &> /dev/null; then
    echo "[ERROR] cyclictest not found. Install with: apt-get install rt-tests"
    exit 1
fi

# 检查是否有 root 权限
if [ "$EUID" -ne 0 ]; then
    echo "[WARN] cyclictest needs root privileges for RT scheduling"
    echo "[INFO] Trying to run with current permissions..."
fi

echo "--- Kernel Config ---"
if [ -f /proc/config.gz ]; then
    zcat /proc/config.gz | grep -E "PREEMPT|HZ=|NO_HZ" | head -10
else
    echo "No /proc/config.gz available"
fi

echo ""
echo "--- Running cyclictest (10000 iterations) ---"
echo "Command: cyclictest -l10000 -m -Sp90 -i200 -h400 -q"
echo ""

# 尝试运行 cyclictest
cyclictest -l10000 -m -Sp90 -i200 -h400 -q 2>&1 || {
    echo ""
    echo "[ERROR] cyclictest failed. Possible reasons:"
    echo "  1. Need root: run with 'sudo cyclictest ...'"
    echo "  2. Missing RT-Tests: apt-get install rt-tests"
}

echo ""
echo "╠══════════════════════════════════════════════════════╣"
echo "║  Target: Max latency reduction ~30% vs PREEMPT_NONE  ║"
echo "║  Need comparison: CONFIG_PREEMPT=y vs VOLUNTARY      ║"
echo "╚══════════════════════════════════════════════════════╝"
REMOTE_EOF
}

# 实验 2: 推理抖动测试 (长时间)
run_exp2_jitter() {
    log_info "=== 实验 2: 推理抖动测试 ==="
    log_warn "此测试需要运行较长时间 (5分钟)"

    # 创建长时间测试程序
    cat > /tmp/test_npu_jitter.cpp << 'EOF'
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <rknn_api.h>
#include <signal.h>

#define TOTAL_FRAMES 9000  // 5 minutes @ 30fps
#define REPORT_INTERVAL 900  // Report every 30 seconds
#define INPUT_WIDTH 640
#define INPUT_HEIGHT 640

static volatile int running = 1;
void signal_handler(int sig) { running = 0; }

int main() {
    signal(SIGINT, signal_handler);

    rknn_context ctx;
    FILE *fp = fopen("/opt/edge-ai/models/yolov5n.rknn", "rb");
    if (!fp) { fprintf(stderr, "Cannot open model\n"); return -1; }

    fseek(fp, 0, SEEK_END);
    int model_len = ftell(fp);
    fseek(fp, 0, SEEK_SET);
    char *model_data = (char*)malloc(model_len);
    fread(model_data, 1, model_len, fp);
    fclose(fp);

    rknn_init(&ctx, model_data, model_len, 0, NULL);

    rknn_input_output_num io_num;
    rknn_query(ctx, RKNN_QUERY_IN_OUT_NUM, &io_num, sizeof(io_num));

    rknn_input inputs[1];
    memset(inputs, 0, sizeof(inputs));
    inputs[0].index = 0;
    inputs[0].type = RKNN_INPUT_TYPE_UINT8;
    inputs[0].size = INPUT_WIDTH * INPUT_HEIGHT * 3;
    inputs[0].fmt = RKNN_INPUT_FMT_RGB;
    inputs[0].buf = malloc(INPUT_WIDTH * INPUT_HEIGHT * 3);
    memset(inputs[0].buf, 128, INPUT_WIDTH * INPUT_HEIGHT * 3);

    // Warmup
    for (int i = 0; i < 10; i++) {
        rknn_inputs_set(ctx, io_num.n_input, inputs);
        rknn_run(ctx, NULL);
    }

    printf("Frame,Avg_ms,Stddev_ms,Min_ms,Max_ms,P95_ms\n");

    double sum = 0, sum_sq = 0, min = 9999, max = 0;
    double latencies[REPORT_INTERVAL];
    int count = 0;
    struct timespec ts1, ts2;

    for (int frame = 1; frame <= TOTAL_FRAMES && running; frame++) {
        clock_gettime(CLOCK_MONOTONIC, &ts1);
        rknn_inputs_set(ctx, io_num.n_input, inputs);
        rknn_run(ctx, NULL);
        clock_gettime(CLOCK_MONOTONIC, &ts2);

        double lat = (ts2.tv_sec - ts1.tv_sec) * 1000.0 +
                     (ts2.tv_nsec - ts1.tv_nsec) / 1000000.0;

        latencies[count] = lat;
        sum += lat;
        sum_sq += lat * lat;
        if (lat < min) min = lat;
        if (lat > max) max = lat;
        count++;

        if (count >= REPORT_INTERVAL) {
            double avg = sum / count;
            double variance = (sum_sq - sum * sum / count) / count;
            double stddev = sqrt(variance);

            // Sort for P95
            for (int i = 0; i < count - 1; i++) {
                for (int j = i + 1; j < count; j++) {
                    if (latencies[i] > latencies[j]) {
                        double tmp = latencies[i];
                        latencies[i] = latencies[j];
                        latencies[j] = tmp;
                    }
                }
            }
            double p95 = latencies[(int)(count * 0.95)];

            printf("%d,%.2f,%.2f,%.2f,%.2f,%.2f\n", frame, avg, stddev, min, max, p95);

            // Reset for next interval
            sum = sum_sq = 0;
            min = 9999; max = 0;
            count = 0;
        }
    }

    rknn_destroy(ctx);
    free(model_data);
    free(inputs[0].buf);
    return 0;
}
EOF

    scp $SSH_OPTS /tmp/test_npu_jitter.cpp $BOARD_USER@$BOARD_IP:/tmp/
    ssh $SSH_OPTS $BOARD_USER@$BOARD_IP "cd /tmp && g++ -o test_npu_jitter test_npu_jitter.cpp -I/home/toybrick/RK3399Pro_npu/rknn-api/librknn_api/Linux/include -L$RKNN_LIB_DIR -lrknn_api -lrt -lpthread 2>&1"

    log_info "运行抖动测试 (5分钟)..."
    ssh $SSH_OPTS $BOARD_USER@$BOARD_IP "export LD_LIBRARY_PATH=$RKNN_LIB_DIR:\$LD_LIBRARY_PATH && timeout 310 /tmp/test_npu_jitter" 2>&1
}

# 运行运行中的 pipeline 统计
run_pipeline_stats() {
    log_info "=== 运行 Pipeline 统计 ==="

    ssh $SSH_OPTS $BOARD_USER@$BOARD_IP << 'REMOTE_EOF'
# 检查 edge-ai-camera 是否在运行
if pgrep -f "edge-ai-camera" > /dev/null; then
    echo "[INFO] edge-ai-camera is running"
    echo "[INFO] Checking for inference latency logs..."
    journalctl -u edge-ai-camera --since "5 minutes ago" 2>/dev/null | grep -E "inference|Frame|latency|avg" | tail -20
else
    echo "[WARN] edge-ai-camera is not running"
    echo "[INFO] Start it with: systemctl start edge-ai-camera"
fi
REMOTE_EOF
}

# 主菜单
show_menu() {
    echo ""
    echo "╔═══════════════════════════════════════════════════════════╗"
    echo "║       RK3399Pro 边缘 AI 平台性能测试                       ║"
    echo "╠═══════════════════════════════════════════════════════════╣"
    echo "║  1. NPU 推理延迟测量 (5分钟)                               ║"
    echo "║  2. 推理抖动测试 - 长时间 (5分钟)                          ║"
    echo "║  3. 视频编码丢帧率 (需要修改代码)                          ║"
    echo "║  4. RTSP 推流延迟 (需要 PC 端配合)                         ║"
    echo "║  5. 系统启动时间测量 (即时)                                ║"
    echo "║  6. 镜像体积分析 (即时)                                    ║"
    echo "║  7. cyclictest 中断延迟 (需要 root)                        ║"
    echo "║  8. 检查 Pipeline 运行状态 (即时)                          ║"
    echo "║  all. 运行所有即时测试 (1,5,6,7,8)                         ║"
    echo "║  q. 退出                                                   ║"
    echo "╚═══════════════════════════════════════════════════════════╝"
}

# 主函数
main() {
    if [ "$1" = "" ]; then
        show_menu
        read -p "请选择测试项目: " choice
    else
        choice="$1"
    fi

    case $choice in
        1) check_ssh && run_exp1_npu_latency ;;
        2) check_ssh && run_exp2_jitter ;;
        5) check_ssh && run_exp5_boot_time ;;
        6) check_ssh && run_exp6_image_size ;;
        7) check_ssh && run_exp7_cyclictest ;;
        8) check_ssh && run_pipeline_stats ;;
        all)
            check_ssh
            run_exp1_npu_latency
            run_exp5_boot_time
            run_exp6_image_size
            run_exp7_cyclictest
            run_pipeline_stats
            ;;
        q|Q) echo "退出"; exit 0 ;;
        *) log_error "无效选择: $choice"; exit 1 ;;
    esac
}

main "$@"
