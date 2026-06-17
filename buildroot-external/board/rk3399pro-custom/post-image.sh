#!/bin/sh
# Post-image script: 生成 SD 卡镜像
BOARD_DIR="$(dirname "$0")"
BUILD_DIR="${BUILD_DIR:-output/build}"
IMAGES_DIR="${BINARIES_DIR:-output/images}"

# 复制内核和设备树到 boot 分区
cp -f "${IMAGES_DIR}/Image" "${IMAGES_DIR}/rk3399pro-edge-ai-camera.dtb" "${BINARIES_DIR}"

echo "=== Generating boot.vfat ==="
MKFS_VFAT="${HOST_DIR}/sbin/mkfs.vfat"
if [ ! -x "${MKFS_VFAT}" ]; then
    MKFS_VFAT="${HOST_DIR}/usr/sbin/mkfs.vfat"
fi
dd if=/dev/zero of="${BINARIES_DIR}/boot.vfat" bs=1M count=128
${MKFS_VFAT} "${BINARIES_DIR}/boot.vfat"

# 将 kernel + dtb 写入 boot 分区
mcopy -i "${BINARIES_DIR}/boot.vfat" "${IMAGES_DIR}/Image" ::Image
mcopy -i "${BINARIES_DIR}/boot.vfat" "${IMAGES_DIR}/rk3399pro-edge-ai-camera.dtb" ::rk3399pro-edge-ai-camera.dtb

# 在数据分区上创建 overlay 目录
mkdir -p "${BINARIES_DIR}/data_overlay/opt/edge-ai/models"
mkdir -p "${BINARIES_DIR}/data_overlay/opt/edge-ai/config"
mkdir -p "${BINARIES_DIR}/data_overlay/var/log/edge-ai"
touch "${BINARIES_DIR}/data_overlay/.empty"

echo "=== Generating SD card image ==="
support/scripts/genimage.sh -c "${BOARD_DIR}/genimage.cfg"

echo "=== Done ==="
echo "Image: ${IMAGES_DIR}/sdcard.img"
echo "Write to SD card: sudo dd if=${IMAGES_DIR}/sdcard.img of=/dev/sdX bs=1M status=progress"