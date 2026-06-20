################################################################################
# rknn-driver — RK3399Pro NPU Kernel Driver Package
################################################################################
#
# RK3399Pro NPU (RK1808 IP Core) 内核驱动:
#   - rknpu.ko — NPU 杂项设备驱动 (/dev/rknpu)
#   - galcore.ko — GPU/NPU 通用抽象层 (某些内核版本需要)
#
# 驱动源码来源:
#   Rockchip BSP Linux Kernel (develop-4.19 分支)
#   https://github.com/rockchip-linux/kernel.git
#
# 内核配置依赖 (通过 linux.fragment 设置):
#   CONFIG_RKNPU=y
#   CONFIG_RKNPU_MMU=y
#   CONFIG_ION=y
#   CONFIG_CMA=y
#   CONFIG_DMA_CMA=y
#   CONFIG_DMA_SHARED_BUFFER=y
#
# 用户空间运行时依赖:
#   librknn_api.so — RKNN1 C API 动态库 (由 edge-ai-app 安装到 /opt/edge-ai/lib/)
#
# 注意:
#   NPU 驱动随 Rockchip BSP 内核一同编译为内置模块 (y) 而非独立模块 (m),
#   因为 NPU 是 RK3399Pro 的基本功能, 开机即用。
#   此 Buildroot 包主要用于:
#     1. 提供用户空间运行时库 librknn_api.so 的安装
#     2. 确保内核配置中 NPU 相关选项被正确启用
#
################################################################################

RKNN_DRIVER_VERSION = 1.7.3
RKNN_DRIVER_SITE = $(BR2_EXTERNAL)/../edge/3rdparty/librknn_api
RKNN_DRIVER_SITE_METHOD = local
RKNN_DRIVER_INSTALL_STAGING = YES
RKNN_DRIVER_INSTALL_TARGET = YES

# ── 用户空间运行时库安装 ──────────────────────────────────────
#
# librknn_api.so 需要从 Rockchip RKNN-Toolkit1 SDK 中提取:
#
# 获取方式 1: 从 Toybrick RK3399Pro 开发板提取
#   scp toybrick@<ip>:/usr/lib/librknn_api.so edge/3rdparty/librknn_api/aarch64/
#
# 获取方式 2: 从 RKNN-Toolkit1 Python wheel 提取
#   pip install rknn-toolkit==1.7.3
#   find / -name "librknn_api.so" 2>/dev/null
#   cp librknn_api.so edge/3rdparty/librknn_api/aarch64/
#
# 获取方式 3: 从 Rockchip SDK 编译
#   git clone https://github.com/rockchip-linux/rknn-toolkit.git
#   cd rknn-toolkit/rknn-runtime
#   mkdir build && cd build
#   cmake .. -DCMAKE_TOOLCHAIN_FILE=<aarch64-toolchain>.cmake
#   make

define RKNN_DRIVER_INSTALL_STAGING_CMDS
	# 安装 RKNN API 头文件到 staging
	mkdir -p $(STAGING_DIR)/usr/include/rknn
	$(INSTALL) -D -m 0644 $(@D)/include/rknn_api.h \
		$(STAGING_DIR)/usr/include/rknn/rknn_api.h

	# 安装 RKNN API 库文件到 staging (如果存在)
	if [ -f $(@D)/aarch64/librknn_api.so ]; then \
		$(INSTALL) -D -m 0755 $(@D)/aarch64/librknn_api.so \
			$(STAGING_DIR)/usr/lib/librknn_api.so; \
	else \
		echo "WARNING: librknn_api.so not found at $(@D)/aarch64/"; \
		echo "  Please copy librknn_api.so from Rockchip SDK or Toybrick board."; \
		echo "  See buildroot-external/package/rknn-driver/rknn-driver.mk for instructions."; \
	fi
endef

define RKNN_DRIVER_INSTALL_TARGET_CMDS
	# 安装 RKNN API 库文件到目标文件系统
	if [ -f $(@D)/aarch64/librknn_api.so ]; then \
		mkdir -p $(TARGET_DIR)/opt/edge-ai/lib; \
		$(INSTALL) -D -m 0755 $(@D)/aarch64/librknn_api.so \
			$(TARGET_DIR)/opt/edge-ai/lib/librknn_api.so; \
	else \
		echo "WARNING: librknn_api.so not found, skipping target install."; \
		echo "  The edge-ai-app will fail to run without librknn_api.so."; \
	fi

	# 创建 NPU 设备节点 (如果内核使用 devtmpfs 则自动创建)
	mkdir -p $(TARGET_DIR)/dev
	# 注意: /dev/rknpu 由内核 devtmpfs 自动创建, 此处仅为 fallback
endef

# 内核配置修正: 确保 NPU 相关选项全部启用
define RKNN_DRIVER_LINUX_CONFIG_FIXUPS
	$(call KCONFIG_ENABLE_OPT,CONFIG_RKNPU)
	$(call KCONFIG_ENABLE_OPT,CONFIG_RKNPU_MMU)
	$(call KCONFIG_ENABLE_OPT,CONFIG_ION)
	$(call KCONFIG_ENABLE_OPT,CONFIG_DMA_SHARED_BUFFER)
endef

$(eval $(generic-package))
