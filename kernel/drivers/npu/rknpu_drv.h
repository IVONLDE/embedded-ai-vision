/* SPDX-License-Identifier: GPL-2.0 */
/*
 * RK3399Pro NPU Kernel Driver — Reference Implementation
 *
 * 此文件是基于 Rockchip BSP 内核 NPU 驱动的文档化参考实现。
 *
 * 实际编译时使用 Rockchip BSP 内核 (develop-4.19 分支) 中的完整驱动:
 *   drivers/rknpu/       — NPU 杂项设备驱动
 *   drivers/staging/rknpu/ — 或此路径 (取决于内核版本)
 *
 * 获取方式:
 *   git clone https://github.com/rockchip-linux/kernel.git -b develop-4.19
 *
 * 相关文件:
 *   drivers/rknpu/rknpu_drv.c       — 驱动入口 (probe/remove)
 *   drivers/rknpu/rknpu_ioctl.c     — ioctl 处理
 *   drivers/rknpu/rknpu_mem.c       — DMA 内存管理
 *   drivers/rknpu/rknpu_power.c     — 电源管理
 *   drivers/rknpu/rknpu_debugfs.c   — 调试接口
 *   include/uapi/linux/rknpu.h      — 用户空间 API 头文件
 *
 * 架构概述:
 *   ┌────────────────────────────────────────┐
 *   │  /dev/rknpu (misc 设备, major=10)       │
 *   │  ioctl: NPU_INIT, NPU_RUN, NPU_DESTROY │
 *   ├────────────────────────────────────────┤
 *   │  NPU Power Domain (PD_NPU)              │
 *   │  NPU Clock (SCLK_NPU, 200-800MHz)       │
 *   │  NPU iommu (RKNPU_MMU)                  │
 *   │  CMA Memory (512MB reserved)            │
 *   └────────────────────────────────────────┘
 */

#ifndef RKNPU_DRV_H
#define RKNPU_DRV_H

#include <linux/cdev.h>
#include <linux/device.h>
#include <linux/fs.h>
#include <linux/io.h>
#include <linux/interrupt.h>
#include <linux/iommu.h>
#include <linux/miscdevice.h>
#include <linux/module.h>
#include <linux/of.h>
#include <linux/of_device.h>
#include <linux/platform_device.h>
#include <linux/pm_runtime.h>

/* ── 设备信息 ──────────────────────────────────────────── */
#define RKNPU_DRIVER_NAME    "rknpu"
#define RKNPU_DEVICE_NAME    "rknpu"
#define RKNPU_CLASS_NAME     "rknpu"

/* NPU 寄存器基址 (来自 DTS) */
#define RKNPU_REG_BASE       0xffbc0000
#define RKNPU_REG_SIZE       0x10000

/* NPU 中断号 (来自 DTS, GIC SPI 43) */
#define RKNPU_IRQ            43

/* NPU 最大支持的网络层数 */
#define RKNPU_MAX_LAYERS     256

/* ── 寄存器偏移 (简化) ──────────────────────────────────── */
#define RKNPU_REG_VERSION    0x0000  /* NPU 硬件版本 */
#define RKNPU_REG_CONTROL    0x0004  /* 控制寄存器 */
#define RKNPU_REG_STATUS     0x0008  /* 状态寄存器 */
#define RKNPU_REG_INT_MASK   0x000C  /* 中断掩码 */
#define RKNPU_REG_INT_CLEAR  0x0010  /* 中断清除 */
#define RKNPU_REG_CMD_BASE   0x0100  /* 命令队列基址 */
#define RKNPU_REG_PERF_CTRL  0x0200  /* 性能计数器控制 */
#define RKNPU_REG_PERF_VAL   0x0204  /* 性能计数器值 */
#define RKNPU_REG_FREQ_CTRL  0x0300  /* 频率控制 */
#define RKNPU_REG_PWR_CTRL   0x0304  /* 电源控制 */

/* 控制寄存器位定义 */
#define RKNPU_CTRL_ENABLE    BIT(0)   /* NPU 使能 */
#define RKNPU_CTRL_RESET     BIT(1)   /* 软复位 */
#define RKNPU_CTRL_CLK_GATE  BIT(2)   /* 时钟门控 */

/* 状态寄存器位定义 */
#define RKNPU_STATUS_BUSY    BIT(0)   /* NPU 繁忙 */
#define RKNPU_STATUS_IDLE    BIT(1)   /* NPU 空闲 */
#define RKNPU_STATUS_ERROR   BIT(2)   /* 错误状态 */

/* ── NPU 驱动私有数据 ────────────────────────────────────── */
struct rknpu_device {
    struct platform_device *pdev;
    struct miscdevice miscdev;
    struct device *dev;

    /* 寄存器映射 */
    void __iomem *reg_base;
    resource_size_t reg_size;

    /* 中断 */
    int irq;
    wait_queue_head_t cmd_wq;  /* 命令完成等待队列 */
    atomic_t cmd_complete;      /* 命令完成标志 */

    /* 时钟 */
    struct clk *aclk_npu;
    struct clk *hclk_npu;
    struct clk *sclk_npu;

    /* 电源域 */
    struct notifier_block pd_nb;

    /* DMA/iommu */
    struct iommu_domain *domain;
    dma_addr_t dma_base;
    size_t dma_size;

    /* 内存池 (CMA) */
    void *cma_vaddr;
    dma_addr_t cma_paddr;

    /* 性能统计 */
    u64 total_inferences;
    u64 total_cycles;
    u32 cur_freq_mhz;

    /* 设备锁 */
    struct mutex lock;
};

/* ── ioctl 命令定义 ──────────────────────────────────────── */
#define RKNPU_IOC_MAGIC  'R'

/* 初始化 NPU 上下文 (加载模型) */
struct rknpu_init_arg {
    unsigned long model_addr;    /* 用户空间模型数据指针 */
    unsigned int  model_size;    /* 模型数据大小 */
    unsigned int  flags;         /* 初始化标志 */
    int           reserved[8];
};

/* 运行推理 */
struct rknpu_run_arg {
    unsigned long input_addr;    /* 输入数据指针 */
    unsigned int  input_size;    /* 输入数据大小 */
    unsigned long output_addr;   /* 输出数据指针 */
    unsigned int  output_size;   /* 输出数据大小 */
    int           timeout_ms;    /* 超时 (毫秒) */
    int           reserved[8];
};

#define RKNPU_IOC_INIT     _IOW(RKNPU_IOC_MAGIC, 1, struct rknpu_init_arg)
#define RKNPU_IOC_RUN      _IOWR(RKNPU_IOC_MAGIC, 2, struct rknpu_run_arg)
#define RKNPU_IOC_DESTROY  _IO(RKNPU_IOC_MAGIC, 3)
#define RKNPU_IOC_GET_INFO _IOR(RKNPU_IOC_MAGIC, 4, struct rknpu_info)

/* 设备信息 */
struct rknpu_info {
    char    version[32];     /* NPU 硬件版本 */
    u32     max_freq_mhz;    /* 最大频率 */
    u32     cur_freq_mhz;    /* 当前频率 */
    u32     sram_size_kb;    /* SRAM 大小 */
    u64     total_inferences; /* 累计推理次数 */
    u64     total_cycles;    /* 累计时钟周期 */
    int     reserved[8];
};

#endif /* RKNPU_DRV_H */

/*
 * ── 驱动加载/编译说明 ──────────────────────────────────────
 *
 * 在 Rockchip BSP 内核 (develop-4.19) 中:
 *
 * 1. 放置文件:
 *    cp kernel/drivers/npu/rknpu_drv.h   → drivers/rknpu/
 *    cp kernel/drivers/npu/rknpu_drv.c   → drivers/rknpu/
 *
 * 2. 修改 drivers/rknpu/Kconfig:
 *    config RKNPU
 *        tristate "Rockchip NPU Driver"
 *        depends on ARCH_ROCKCHIP
 *        select DMA_CMA
 *        help
 *          Rockchip Neural Processing Unit (NPU) driver.
 *
 * 3. 修改 drivers/rknpu/Makefile:
 *    obj-$(CONFIG_RKNPU) += rknpu.o
 *    rknpu-objs := rknpu_drv.o rknpu_ioctl.o rknpu_mem.o rknpu_power.o
 *
 * 4. 启用内核配置:
 *    CONFIG_RKNPU=y
 *    CONFIG_RKNPU_MMU=y
 *    CONFIG_CMA=y
 *    CONFIG_DMA_CMA=y
 *    CONFIG_CMA_SIZE_MBYTES=512
 *
 * 5. 编译内核:
 *    make ARCH=arm64 CROSS_COMPILE=aarch64-linux-gnu- Image modules
 *
 * 6. 加载模块:
 *    insmod drivers/rknpu/rknpu.ko
 *
 * 7. 验证:
 *    ls -la /dev/rknpu
 *    dmesg | grep -i rknpu
 */