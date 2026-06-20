# RK3399Pro NPU Driver — Makefile
# 此驱动作为参考实现，编译到 Rockchip BSP 内核中使用。
#
# 完整实现位于 Rockchip BSP 内核:
#   https://github.com/rockchip-linux/kernel.git (develop-4.19)
#   路径: drivers/rknpu/

obj-$(CONFIG_EDGE_AI_NPU) += rknpu.o
rknpu-objs := rknpu_drv.o

# 当使用 Rockchip BSP 内核的完整驱动时, 替换为:
# obj-$(CONFIG_RKNPU) += rknpu.o
# rknpu-objs := rknpu_drv.o rknpu_ioctl.o rknpu_mem.o rknpu_power.o rknpu_debugfs.o
