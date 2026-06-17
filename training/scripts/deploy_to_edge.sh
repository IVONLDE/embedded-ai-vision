#!/bin/bash
# Deploy model to edge device
#
# 用法:
#   ./deploy_to_edge.sh <device_ip> <model_path> [scene_name]
#
# 示例:
#   # 推送车辆检测模型
#   ./deploy_to_edge.sh 192.168.1.50 yolov5n.rknn vehicle
#
#   # 推送人脸检测模型
#   ./deploy_to_edge.sh 192.168.1.50 face_detection.rknn face
#
#   # 只推送模型, 不切换场景
#   ./deploy_to_edge.sh 192.168.1.50 new_model.rknn

set -e

DEVICE_IP="${1:?Usage: $0 <device_ip> <model_path> [scene_name]}"
MODEL_PATH="${2:?Usage: $0 <device_ip> <model_path> [scene_name]}"
SCENE_NAME="${3:-}"

DEVICE_USER="root"
DEVICE_MODEL_DIR="/opt/edge-ai/models"
DEVICE_MODEL_NAME="current.rknn"

echo "=== Edge AI Model Deployment ==="
echo "Device:  ${DEVICE_IP}"
echo "Model:   ${MODEL_PATH}"
echo "Scene:   ${SCENE_NAME:-'(no scene switch)'}"
echo ""

# 1. 检查模型文件
if [ ! -f "${MODEL_PATH}" ]; then
    echo "Error: Model file not found: ${MODEL_PATH}"
    exit 1
fi

echo "Model size: $(du -h ${MODEL_PATH} | cut -f1)"

# 2. SSH 拷贝模型到设备
echo ""
echo "[1/3] Copying model to device..."
ssh ${DEVICE_USER}@${DEVICE_IP} "mkdir -p ${DEVICE_MODEL_DIR}"
scp ${MODEL_PATH} ${DEVICE_USER}@${DEVICE_IP}:${DEVICE_MODEL_DIR}/${DEVICE_MODEL_NAME}
echo "Model copied to ${DEVICE_IP}:${DEVICE_MODEL_DIR}/${DEVICE_MODEL_NAME}"

# 3. 备份旧模型
echo ""
echo "[2/3] Backing up old model..."
ssh ${DEVICE_USER}@${DEVICE_IP} "\
    if [ -f ${DEVICE_MODEL_DIR}/current.rknn ]; then \
        cp ${DEVICE_MODEL_DIR}/current.rknn \
           ${DEVICE_MODEL_DIR}/current.rknn.bak.$(date +%Y%m%d_%H%M%S); \
        echo 'Backup created'; \
    else \
        echo 'No existing model to backup'; \
    fi"

# 4. 通知设备热加载 / 切换场景
echo ""
echo "[3/3] Notifying device..."

if [ -n "${SCENE_NAME}" ]; then
    # 通过 gRPC 切换场景
    echo "Switching scene to '${SCENE_NAME}' via gRPC..."
    # TODO: 实现 gRPC 客户端
    # grpc_cli call ${DEVICE_IP}:50051 EdgeService.SwitchScene \
    #     "{\"scene_name\": \"${SCENE_NAME}\"}"
    echo "(gRPC client not yet implemented — restarting service instead)"
    ssh ${DEVICE_USER}@${DEVICE_IP} "systemctl restart edge-ai-camera"
else
    # 只通知模型热加载
    echo "Triggering model hot-reload..."
    ssh ${DEVICE_USER}@${DEVICE_IP} "systemctl reload edge-ai-camera"
fi

# 5. 验证
echo ""
echo "=== Deployment Complete ==="
echo "Checking device status..."
sleep 2
ssh ${DEVICE_USER}@${DEVICE_IP} "\
    echo 'Service status:'; \
    systemctl is-active edge-ai-camera; \
    echo ''; \
    echo 'Last 3 log lines:'; \
    journalctl -u edge-ai-camera -n 3 --no-pager"

echo ""
echo "To monitor detection results:"
echo "  mosquitto_sub -h ${DEVICE_IP} -t 'edge/+/detections' -v"