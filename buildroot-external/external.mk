# Buildroot External Tree — Makefile
# 嵌入式 AI 边缘摄像头系统
# 平台: RK3399Pro

include $(sort $(wildcard $(BR2_EXTERNAL)/package/*/*.mk))
