################################################################################
# edge-ai-app
################################################################################

EDGE_AI_APP_VERSION = 1.0.0
EDGE_AI_APP_SITE = $(BR2_EXTERNAL)/../edge
EDGE_AI_APP_SITE_METHOD = local
EDGE_AI_APP_INSTALL_STAGING = NO
EDGE_AI_APP_INSTALL_TARGET = YES

EDGE_AI_APP_DEPENDENCIES = opencv4 mosquitto yaml-cpp eigen

define EDGE_AI_APP_CONFIGURE_CMDS
    mkdir -p $(@D)/build
    (cd $(@D)/build && \
     $(TARGET_MAKE_ENV) $(CMAKE) .. \
       -DCMAKE_TOOLCHAIN_FILE=$(HOST_DIR)/share/buildroot/toolchainfile.cmake \
       -DCMAKE_BUILD_TYPE=Release \
       -DCMAKE_INSTALL_PREFIX=/usr \
       -DRKNN_LIB_DIR=$(STAGING_DIR)/usr/lib \
       -DRKNN_INCLUDE_DIR=$(STAGING_DIR)/usr/include/rknn \
       -DRGA_LIB_DIR=$(STAGING_DIR)/usr/lib \
       -DRGA_INCLUDE_DIR=$(STAGING_DIR)/usr/include/rga)
endef

define EDGE_AI_APP_BUILD_CMDS
    $(TARGET_MAKE_ENV) $(MAKE) -C $(@D)/build
endef

define EDGE_AI_APP_INSTALL_TARGET_CMDS
    $(INSTALL) -D -m 0755 $(@D)/build/edge-ai-camera $(TARGET_DIR)/usr/bin/edge-ai-camera
    $(INSTALL) -D -m 0644 $(@D)/config/pipeline.yaml $(TARGET_DIR)/opt/edge-ai/config/pipeline.yaml
    $(INSTALL) -D -m 0644 $(@D)/config/edge-ai-camera.service $(TARGET_DIR)/usr/lib/systemd/system/edge-ai-camera.service
    mkdir -p $(TARGET_DIR)/opt/edge-ai/models
    mkdir -p $(TARGET_DIR)/opt/edge-ai/lib
    # 安装 RKNN 运行时库
    $(INSTALL) -D -m 0755 $(@D)/3rdparty/librknn_api/aarch64/librknn_api.so $(TARGET_DIR)/opt/edge-ai/lib/librknn_api.so
endef

# 开机自启动
define EDGE_AI_APP_LINUX_CONFIG_FIXUPS
    $(call KCONFIG_ENABLE_OPT,CONFIG_EDGE_AI_APP)
endef

$(eval $(cmake-package))