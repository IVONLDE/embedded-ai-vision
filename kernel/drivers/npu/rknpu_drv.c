/* SPDX-License-Identifier: GPL-2.0 */
/*
 * RK3399Pro NPU Kernel Driver — Core Implementation Reference
 *
 * 这是 Rockchip BSP 内核 NPU 驱动的简化参考实现。
 * 完整实现请使用 Rockchip BSP 内核中的 drivers/rknpu/ 目录。
 *
 * 参考: https://github.com/rockchip-linux/kernel (develop-4.19 分支)
 */

#include "rknpu_drv.h"

#include <linux/dma-mapping.h>
#include <linux/interrupt.h>
#include <linux/io.h>
#include <linux/kernel.h>
#include <linux/module.h>
#include <linux/of.h>
#include <linux/of_irq.h>
#include <linux/platform_device.h>
#include <linux/pm_runtime.h>
#include <linux/slab.h>
#include <linux/uaccess.h>

/* ── 模块信息 ──────────────────────────────────────────── */
MODULE_AUTHOR("Edge AI Vision Project");
MODULE_DESCRIPTION("RK3399Pro NPU Driver (RK1808 IP Core)");
MODULE_LICENSE("GPL v2");
MODULE_VERSION("1.0");

/* ── 硬件寄存器读写 ────────────────────────────────────── */
static inline u32 rknpu_read(struct rknpu_device *dev, u32 offset)
{
    return readl_relaxed(dev->reg_base + offset);
}

static inline void rknpu_write(struct rknpu_device *dev, u32 offset, u32 val)
{
    writel_relaxed(val, dev->reg_base + offset);
}

/* ── NPU 电源管理 ──────────────────────────────────────── */
static int rknpu_power_on(struct rknpu_device *dev)
{
    int ret;

    dev_dbg(dev->dev, "Powering on NPU\n");

    /* 启用时钟 */
    ret = clk_prepare_enable(dev->aclk_npu);
    if (ret) {
        dev_err(dev->dev, "Failed to enable aclk_npu: %d\n", ret);
        return ret;
    }

    ret = clk_prepare_enable(dev->hclk_npu);
    if (ret) {
        dev_err(dev->dev, "Failed to enable hclk_npu: %d\n", ret);
        clk_disable_unprepare(dev->aclk_npu);
        return ret;
    }

    ret = clk_prepare_enable(dev->sclk_npu);
    if (ret) {
        dev_err(dev->dev, "Failed to enable sclk_npu: %d\n", ret);
        clk_disable_unprepare(dev->hclk_npu);
        clk_disable_unprepare(dev->aclk_npu);
        return ret;
    }

    /* 设置默认频率 800MHz */
    clk_set_rate(dev->sclk_npu, 800000000);

    /* 取消复位 */
    rknpu_write(dev, RKNPU_REG_CONTROL,
                rknpu_read(dev, RKNPU_REG_CONTROL) & ~RKNPU_CTRL_RESET);

    /* 取消时钟门控 */
    rknpu_write(dev, RKNPU_REG_CONTROL,
                rknpu_read(dev, RKNPU_REG_CONTROL) & ~RKNPU_CTRL_CLK_GATE);

    /* 使能 NPU */
    rknpu_write(dev, RKNPU_REG_CONTROL,
                rknpu_read(dev, RKNPU_REG_CONTROL) | RKNPU_CTRL_ENABLE);

    dev->cur_freq_mhz = clk_get_rate(dev->sclk_npu) / 1000000;

    return 0;
}

static void rknpu_power_off(struct rknpu_device *dev)
{
    dev_dbg(dev->dev, "Powering off NPU\n");

    /* 禁用 NPU */
    rknpu_write(dev, RKNPU_REG_CONTROL,
                rknpu_read(dev, RKNPU_REG_CONTROL) & ~RKNPU_CTRL_ENABLE);

    /* 时钟门控 */
    rknpu_write(dev, RKNPU_REG_CONTROL,
                rknpu_read(dev, RKNPU_REG_CONTROL) | RKNPU_CTRL_CLK_GATE);

    clk_disable_unprepare(dev->sclk_npu);
    clk_disable_unprepare(dev->hclk_npu);
    clk_disable_unprepare(dev->aclk_npu);
}

/* ── 中断处理 ──────────────────────────────────────────── */
/*
 * NPU 推理完成后触发中断，唤醒等待在 wait_queue 上的用户进程。
 * rknn_run() 在 ioctl 中阻塞等待此中断。
 */
static irqreturn_t rknpu_irq_handler(int irq, void *data)
{
    struct rknpu_device *dev = (struct rknpu_device *)data;

    /* 清除中断 */
    rknpu_write(dev, RKNPU_REG_INT_CLEAR, 0x1);

    /* 通知等待者推理完成 */
    atomic_set(&dev->cmd_complete, 1);
    wake_up_interruptible(&dev->cmd_wq);

    return IRQ_HANDLED;
}

/* ── 文件操作 ──────────────────────────────────────────── */
static int rknpu_open(struct inode *inode, struct file *filp)
{
    struct rknpu_device *dev = container_of(filp->private_data,
                                            struct rknpu_device, miscdev);
    filp->private_data = dev;

    dev_dbg(dev->dev, "Device opened\n");
    return 0;
}

static int rknpu_release(struct inode *inode, struct file *filp)
{
    struct rknpu_device *dev = (struct rknpu_device *)filp->private_data;

    dev_dbg(dev->dev, "Device released\n");
    return 0;
}

static long rknpu_ioctl(struct file *filp, unsigned int cmd, unsigned long arg)
{
    struct rknpu_device *dev = (struct rknpu_device *)filp->private_data;
    int ret = 0;

    mutex_lock(&dev->lock);

    switch (cmd) {
    case RKNPU_IOC_INIT: {
        struct rknpu_init_arg init_arg;

        if (copy_from_user(&init_arg, (void __user *)arg, sizeof(init_arg))) {
            ret = -EFAULT;
            break;
        }

        dev_dbg(dev->dev, "NPU_INIT: model_size=%u\n", init_arg.model_size);

        /* 确保 NPU 上电 */
        ret = pm_runtime_get_sync(dev->dev);
        if (ret < 0) {
            dev_err(dev->dev, "Failed to power on NPU: %d\n", ret);
            pm_runtime_put_noidle(dev->dev);
            break;
        }

        break;
    }
    case RKNPU_IOC_RUN: {
        struct rknpu_run_arg run_arg;

        if (copy_from_user(&run_arg, (void __user *)arg, sizeof(run_arg))) {
            ret = -EFAULT;
            break;
        }

        /* 等待 NPU 空闲 */
        if (rknpu_read(dev, RKNPU_REG_STATUS) & RKNPU_STATUS_BUSY) {
            ret = -EBUSY;
            break;
        }

        /* 触发推理 (硬件寄存器写入由 librknn_api 完成) */

        /* 等待推理完成中断 */
        atomic_set(&dev->cmd_complete, 0);
        ret = wait_event_interruptible_timeout(
            dev->cmd_wq,
            atomic_read(&dev->cmd_complete) != 0,
            msecs_to_jiffies(run_arg.timeout_ms));

        if (ret == 0) {
            dev_err(dev->dev, "NPU inference timed out\n");
            ret = -ETIMEDOUT;
        } else if (ret > 0) {
            ret = 0;  /* 成功 */
        }
        /* ret < 0: 信号中断 */

        dev->total_inferences++;
        break;
    }
    case RKNPU_IOC_DESTROY: {
        pm_runtime_mark_last_busy(dev->dev);
        pm_runtime_put_autosuspend(dev->dev);
        break;
    }
    case RKNPU_IOC_GET_INFO: {
        struct rknpu_info info;

        memset(&info, 0, sizeof(info));
        snprintf(info.version, sizeof(info.version), "RK1808 r1p0");
        info.max_freq_mhz = 800;
        info.cur_freq_mhz = dev->cur_freq_mhz;
        info.sram_size_kb = 256;
        info.total_inferences = dev->total_inferences;
        info.total_cycles = dev->total_cycles;

        if (copy_to_user((void __user *)arg, &info, sizeof(info))) {
            ret = -EFAULT;
            break;
        }
        break;
    }
    default:
        ret = -ENOTTY;  /* 不支持的 ioctl */
        break;
    }

    mutex_unlock(&dev->lock);
    return ret;
}

static const struct file_operations rknpu_fops = {
    .owner          = THIS_MODULE,
    .open           = rknpu_open,
    .release        = rknpu_release,
    .unlocked_ioctl = rknpu_ioctl,
};

/* ── 平台驱动: probe ───────────────────────────────────── */
static int rknpu_probe(struct platform_device *pdev)
{
    struct rknpu_device *dev;
    struct resource *res;
    int ret;

    dev_dbg(&pdev->dev, "Probing NPU driver\n");

    dev = devm_kzalloc(&pdev->dev, sizeof(*dev), GFP_KERNEL);
    if (!dev)
        return -ENOMEM;

    dev->pdev = pdev;
    dev->dev = &pdev->dev;

    mutex_init(&dev->lock);
    init_waitqueue_head(&dev->cmd_wq);
    atomic_set(&dev->cmd_complete, 0);

    /* 获取寄存器资源 */
    res = platform_get_resource(pdev, IORESOURCE_MEM, 0);
    if (!res) {
        dev_err(&pdev->dev, "Failed to get memory resource\n");
        return -ENODEV;
    }

    dev->reg_size = resource_size(res);
    dev->reg_base = devm_ioremap_resource(&pdev->dev, res);
    if (IS_ERR(dev->reg_base))
        return PTR_ERR(dev->reg_base);

    /* 获取中断 */
    dev->irq = platform_get_irq(pdev, 0);
    if (dev->irq < 0) {
        dev_err(&pdev->dev, "Failed to get IRQ\n");
        return dev->irq;
    }

    ret = devm_request_irq(&pdev->dev, dev->irq, rknpu_irq_handler,
                            IRQF_SHARED, "rknpu", dev);
    if (ret) {
        dev_err(&pdev->dev, "Failed to request IRQ %d: %d\n", dev->irq, ret);
        return ret;
    }

    /* 获取时钟 */
    dev->aclk_npu = devm_clk_get(&pdev->dev, "aclk_npu");
    if (IS_ERR(dev->aclk_npu)) {
        dev_err(&pdev->dev, "Failed to get aclk_npu\n");
        return PTR_ERR(dev->aclk_npu);
    }

    dev->hclk_npu = devm_clk_get(&pdev->dev, "hclk_npu");
    if (IS_ERR(dev->hclk_npu)) {
        dev_err(&pdev->dev, "Failed to get hclk_npu\n");
        return PTR_ERR(dev->hclk_npu);
    }

    dev->sclk_npu = devm_clk_get(&pdev->dev, "sclk_npu");
    if (IS_ERR(dev->sclk_npu)) {
        dev_err(&pdev->dev, "Failed to get sclk_npu\n");
        return PTR_ERR(dev->sclk_npu);
    }

    /* 注册 misc 设备 */
    dev->miscdev.minor = MISC_DYNAMIC_MINOR;
    dev->miscdev.name = RKNPU_DEVICE_NAME;
    dev->miscdev.fops = &rknpu_fops;
    dev->miscdev.parent = &pdev->dev;

    ret = misc_register(&dev->miscdev);
    if (ret) {
        dev_err(&pdev->dev, "Failed to register misc device: %d\n", ret);
        return ret;
    }

    /* 电源管理 */
    pm_runtime_enable(&pdev->dev);
    pm_runtime_set_autosuspend_delay(&pdev->dev, 200);  /* 200ms 空闲后自动休眠 */
    pm_runtime_use_autosuspend(&pdev->dev);

    platform_set_drvdata(pdev, dev);

    dev_info(&pdev->dev, "RK3399Pro NPU driver loaded (RK1808 IP Core)\n");
    dev_info(&pdev->dev, "  Device: /dev/%s\n", RKNPU_DEVICE_NAME);
    dev_info(&pdev->dev, "  SRAM: 256KB\n");
    dev_info(&pdev->dev, "  Max Clock: 800MHz\n");
    dev_info(&pdev->dev, "  INT8 TOPS: 3.0\n");

    return 0;
}

/* ── 平台驱动: remove ──────────────────────────────────── */
static int rknpu_remove(struct platform_device *pdev)
{
    struct rknpu_device *dev = platform_get_drvdata(pdev);

    pm_runtime_disable(&pdev->dev);
    misc_deregister(&dev->miscdev);
    mutex_destroy(&dev->lock);

    dev_info(&pdev->dev, "RK3399Pro NPU driver removed\n");
    return 0;
}

/* ── 电源管理: suspend/resume ──────────────────────────── */
static int __maybe_unused rknpu_suspend(struct device *dev)
{
    struct rknpu_device *rknpu = dev_get_drvdata(dev);

    dev_dbg(dev, "NPU suspend\n");
    rknpu_power_off(rknpu);

    return 0;
}

static int __maybe_unused rknpu_resume(struct device *dev)
{
    struct rknpu_device *rknpu = dev_get_drvdata(dev);
    int ret;

    dev_dbg(dev, "NPU resume\n");
    ret = rknpu_power_on(rknpu);
    if (ret)
        dev_err(dev, "Failed to resume NPU: %d\n", ret);

    return ret;
}

static const struct dev_pm_ops rknpu_pm_ops = {
    SET_SYSTEM_SLEEP_PM_OPS(rknpu_suspend, rknpu_resume)
};

/* ── 设备树匹配表 ──────────────────────────────────────── */
static const struct of_device_id rknpu_of_match[] = {
    { .compatible = "rockchip,rk3399pro-npu" },
    { .compatible = "rockchip,rk3399pro-rknpu" },
    { /* sentinel */ }
};
MODULE_DEVICE_TABLE(of, rknpu_of_match);

/* ── 平台驱动定义 ──────────────────────────────────────── */
static struct platform_driver rknpu_driver = {
    .probe  = rknpu_probe,
    .remove = rknpu_remove,
    .driver = {
        .name   = RKNPU_DRIVER_NAME,
        .of_match_table = rknpu_of_match,
        .pm     = &rknpu_pm_ops,
    },
};

module_platform_driver(rknpu_driver);
