#!/bin/bash
# Build Script — Edge AI Camera (RK3399Pro)
#
# 用法:
#   ./scripts/build_all.sh           # 完整构建 (本地 aarch64 编译)
#   ./scripts/build_all.sh x86       # x86 语法检查构建
#   ./scripts/build_all.sh sdk       # 使用 Buildroot SDK 交叉编译
#
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
BUILD_DIR="${PROJECT_ROOT}/build"
BUILD_TYPE="${1:-aarch64}"

echo "╔══════════════════════════════════════════════╗"
echo "║  Edge AI Camera — Build Script             ║"
echo "║  Target: ${BUILD_TYPE}                      ║"
echo "╚══════════════════════════════════════════════╝"

# 创建构建目录
mkdir -p "${BUILD_DIR}/${BUILD_TYPE}"
cd "${BUILD_DIR}/${BUILD_TYPE}"

case "${BUILD_TYPE}" in
    x86)
        echo "[1/2] Configuring for x86 syntax check..."
        cmake "${PROJECT_ROOT}" \
            -DCMAKE_BUILD_TYPE=Debug \
            -DRKNN_INCLUDE_DIR="${PROJECT_ROOT}/3rdparty/librknn_api/include"

        echo "[2/2] Building..."
        cmake --build . -j$(nproc)
        echo ""
        echo "Build complete (x86 syntax check only, NOT executable on x86)"
        ;;

    aarch64)
        echo "[1/2] Configuring for AArch64..."
        cmake "${PROJECT_ROOT}" \
            -DCMAKE_TOOLCHAIN_FILE="${PROJECT_ROOT}/cmake/aarch64-toolchain.cmake" \
            -DCMAKE_BUILD_TYPE=Release \
            -DRKNN_INCLUDE_DIR="${PROJECT_ROOT}/3rdparty/librknn_api/include"

        echo "[2/2] Building..."
        cmake --build . -j$(nproc)
        echo ""
        echo "Build complete — binary: ${BUILD_DIR}/aarch64/edge-ai-camera"
        ;;

    sdk)
        if [ -z "${BUILDROOT_SDK}" ]; then
            echo "Error: BUILDROOT_SDK environment variable not set."
            echo "  Set it to your Buildroot SDK path:"
            echo "  export BUILDROOT_SDK=/path/to/buildroot/output/host/aarch64-buildroot-linux-gnu/sysroot"
            exit 1
        fi

        echo "[1/2] Configuring with Buildroot SDK..."
        cmake "${PROJECT_ROOT}" \
            -DCMAKE_TOOLCHAIN_FILE="${PROJECT_ROOT}/cmake/aarch64-toolchain.cmake" \
            -DCMAKE_SYSROOT="${BUILDROOT_SDK}" \
            -DCMAKE_BUILD_TYPE=Release \
            -DCROSS_PREFIX=aarch64-buildroot-linux-gnu-

        echo "[2/2] Building..."
        cmake --build . -j$(nproc)
        echo ""
        echo "Build complete with Buildroot SDK"
        ;;

    *)
        echo "Usage: $0 {x86|aarch64|sdk}"
        echo "  x86       — Syntax check build on PC (no NPU)"
        echo "  aarch64   — Cross-compile for RK3399Pro"
        echo "  sdk       — Cross-compile with Buildroot SDK"
        exit 1
        ;;
esac