/* SPDX-License-Identifier: GPL-2.0+ */
/*
 * SPI Sensor Character Device Driver for RK3399Pro
 *
 * 功能: 将 SPI 总线封装为字符设备, 用户空间通过 /dev/spi_sensor
 *       与 SPI 传感器通信 (温湿度/ADC 等)
 *
 * 内核框架: 字符设备 (cdev) + SPI 子系统 (spi_driver)
 * 传输模式: 全双工同步传输 (spi_sync)
 * 用户接口: /dev/spi_sensor (read/write/ioctl/poll) + /sys/class/edge-sensor/
 *
 * 设备树绑定:
 *   compatible = "edge-ai,spi-sensor";
 *   作为 SPI 控制器的子节点 (如 &spi0)
 *
 * 参考: drivers/spi/spidev.c
 *       Documentation/driver-api/spi.rst
 */

#include <linux/cdev.h>
#include <linux/device.h>
#include <linux/err.h>
#include <linux/fs.h>
#include <linux/init.h>
#include <linux/kernel.h>
#include <linux/module.h>
#include <linux/mutex.h>
#include <linux/of.h>
#include <linux/of_device.h>
#include <linux/poll.h>
#include <linux/slab.h>
#include <linux/spi/spi.h>
#include <linux/uaccess.h>

#include "spi_sensor.h"

#define DRIVER_NAME     "spi_sensor"
#define DEVICE_NAME     "spi_sensor"
#define CLASS_NAME      "edge-sensor"

/* ── 驱动私有数据 ──────────────────────────────────────── */
struct spi_sensor_dev {
    struct spi_device *spi;     /* SPI 设备 */
    struct device *dev;         /* 设备指针 */

    /* 字符设备 */
    dev_t devt;
    struct cdev cdev;
    struct class *class;
    struct device *chardev;

    /* 同步互斥: 保护 SPI 传输 (同一时间只有一个传输) */
    struct mutex lock;

    /* 统计信息 */
    unsigned long tx_bytes;
    unsigned long rx_bytes;
    unsigned long errors;
    unsigned long transfers;

    /* 当前配置 */
    unsigned int speed_hz;
    unsigned int mode;
    unsigned int bits_per_word;
};

/* 全局 class 指针 (多个 SPI 设备共享) */
static struct class *spi_sensor_class;

/* ── SPI 传输核心函数 ─────────────────────────────────────── */

/*
 * spi_sensor_transfer — 执行一次 SPI 全双工传输
 *
 * @ssd: 驱动私有数据
 * @tx_buf: 发送缓冲区 (可为 NULL 表示只读)
 * @rx_buf: 接收缓冲区 (可为 NULL 表示只写)
 * @len: 传输字节数
 *
 * 返回: 0 成功, 负值错误码
 */
static int spi_sensor_transfer(struct spi_sensor_dev *ssd,
                                const u8 *tx_buf, u8 *rx_buf, size_t len)
{
    struct spi_transfer t = {
        .tx_buf = tx_buf,
        .rx_buf = rx_buf,
        .len = len,
        .speed_hz = ssd->speed_hz,
        .bits_per_word = ssd->bits_per_word,
    };
    struct spi_message m;
    int ret;

    spi_message_init(&m);
    spi_message_add_tail(&t, &m);

    ret = spi_sync(ssd->spi, &m);
    if (ret < 0) {
        ssd->errors++;
        return ret;
    }

    ssd->tx_bytes += len;
    ssd->rx_bytes += len;
    ssd->transfers++;

    return 0;
}

/* ── 字符设备文件操作 ──────────────────────────────────── */

/*
 * spi_sensor_open — 打开设备
 */
static int spi_sensor_open(struct inode *inode, struct file *filp)
{
    struct spi_sensor_dev *ssd;

    ssd = container_of(inode->i_cdev, struct spi_sensor_dev, cdev);
    filp->private_data = ssd;

    dev_dbg(ssd->dev, "Device opened\n");
    return 0;
}

/*
 * spi_sensor_release — 关闭设备
 */
static int spi_sensor_release(struct inode *inode, struct file *filp)
{
    struct spi_sensor_dev *ssd = filp->private_data;

    dev_dbg(ssd->dev, "Device closed\n");
    return 0;
}

/*
 * spi_sensor_read — 执行 SPI 只读传输
 *
 * 写 dummy bytes (0xFF), 读数据到用户空间
 * 常见于读取 ADC/Sensor 寄存器
 */
static ssize_t spi_sensor_read(struct file *filp, char __user *buf,
                                size_t count, loff_t *f_pos)
{
    struct spi_sensor_dev *ssd = filp->private_data;
    u8 *tx_buf, *rx_buf;
    int ret;

    if (count == 0)
        return 0;

    if (count > SPI_SENSOR_MAX_XFER_LEN)
        count = SPI_SENSOR_MAX_XFER_LEN;

    /* 分配临时缓冲区 (不能用栈上大数组) */
    tx_buf = kzalloc(count, GFP_KERNEL);
    rx_buf = kzalloc(count, GFP_KERNEL);
    if (!tx_buf || !rx_buf) {
        ret = -ENOMEM;
        goto err_free;
    }

    /* 发送 dummy bytes (0xFF) 并接收数据 */
    memset(tx_buf, 0xFF, count);

    mutex_lock(&ssd->lock);
    ret = spi_sensor_transfer(ssd, tx_buf, rx_buf, count);
    mutex_unlock(&ssd->lock);

    if (ret < 0)
        goto err_free;

    /* 拷贝到用户空间 */
    if (copy_to_user(buf, rx_buf, count)) {
        ret = -EFAULT;
        goto err_free;
    }

    kfree(tx_buf);
    kfree(rx_buf);
    return count;

err_free:
    kfree(tx_buf);
    kfree(rx_buf);
    return ret;
}

/*
 * spi_sensor_write — 执行 SPI 只写传输
 *
 * 将用户数据通过 SPI 发送
 */
static ssize_t spi_sensor_write(struct file *filp, const char __user *buf,
                                 size_t count, loff_t *f_pos)
{
    struct spi_sensor_dev *ssd = filp->private_data;
    u8 *tx_buf;
    int ret;

    if (count == 0)
        return 0;

    if (count > SPI_SENSOR_MAX_XFER_LEN)
        count = SPI_SENSOR_MAX_XFER_LEN;

    tx_buf = kmalloc(count, GFP_KERNEL);
    if (!tx_buf)
        return -ENOMEM;

    if (copy_from_user(tx_buf, buf, count)) {
        kfree(tx_buf);
        return -EFAULT;
    }

    mutex_lock(&ssd->lock);
    ret = spi_sensor_transfer(ssd, tx_buf, NULL, count);
    mutex_unlock(&ssd->lock);

    kfree(tx_buf);

    if (ret < 0)
        return ret;

    return count;
}

/*
 * spi_sensor_poll — 支持 select/poll/epoll
 *
 * SPI 设备始终可写, 可读依赖具体情况
 */
static __poll_t spi_sensor_poll(struct file *filp, poll_table *wait)
{
    __poll_t mask = 0;

    /* SPI 始终可读写 */
    mask |= EPOLLIN | EPOLLRDNORM;
    mask |= EPOLLOUT | EPOLLWRNORM;

    return mask;
}

/*
 * spi_sensor_ioctl — 设备控制
 *
 * 支持:
 *   - SET_SPEED: 设置 SPI 时钟频率
 *   - SET_MODE: 设置 SPI 模式 (0/1/2/3)
 *   - SET_BITS: 设置字长 (8/16/32)
 *   - TRANSFER: 全双工传输
 *   - GET_STATS: 获取统计信息
 */
static long spi_sensor_ioctl(struct file *filp, unsigned int cmd,
                              unsigned long arg)
{
    struct spi_sensor_dev *ssd = filp->private_data;
    int ret = 0;
    unsigned long speed;
    int mode, bits;
    struct spi_sensor_xfer xfer;
    struct spi_sensor_stats stats;
    u8 *tx_buf = NULL, *rx_buf = NULL;

    switch (cmd) {
    case SPI_SENSOR_IOC_SET_SPEED:
        if (copy_from_user(&speed, (unsigned long __user *)arg,
                           sizeof(unsigned long)))
            return -EFAULT;

        mutex_lock(&ssd->lock);
        ssd->speed_hz = speed;
        ssd->spi->max_speed_hz = speed;
        ret = spi_setup(ssd->spi);
        mutex_unlock(&ssd->lock);

        if (ret)
            dev_err(ssd->dev, "Failed to set speed %lu: %d\n", speed, ret);
        else
            dev_info(ssd->dev, "Speed set to %lu Hz\n", speed);
        break;

    case SPI_SENSOR_IOC_SET_MODE:
        if (copy_from_user(&mode, (int __user *)arg, sizeof(int)))
            return -EFAULT;

        if (mode < 0 || mode > 3) {
            dev_err(ssd->dev, "Invalid SPI mode %d\n", mode);
            return -EINVAL;
        }

        mutex_lock(&ssd->lock);
        ssd->mode = mode;
        /* 清除原有 CPOL/CPHA 位, 设置新模式 */
        ssd->spi->mode &= ~(SPI_CPOL | SPI_CPHA);
        ssd->spi->mode |= (mode & SPI_MODE_X_MASK);
        ret = spi_setup(ssd->spi);
        mutex_unlock(&ssd->lock);

        if (ret)
            dev_err(ssd->dev, "Failed to set mode %d: %d\n", mode, ret);
        else
            dev_info(ssd->dev, "Mode set to %d\n", mode);
        break;

    case SPI_SENSOR_IOC_SET_BITS:
        if (copy_from_user(&bits, (int __user *)arg, sizeof(int)))
            return -EFAULT;

        if (bits != 8 && bits != 16 && bits != 32) {
            dev_err(ssd->dev, "Invalid bits per word %d\n", bits);
            return -EINVAL;
        }

        mutex_lock(&ssd->lock);
        ssd->bits_per_word = bits;
        ssd->spi->bits_per_word = bits;
        ret = spi_setup(ssd->spi);
        mutex_unlock(&ssd->lock);

        if (ret)
            dev_err(ssd->dev, "Failed to set bits %d: %d\n", bits, ret);
        else
            dev_info(ssd->dev, "Bits per word set to %d\n", bits);
        break;

    case SPI_SENSOR_IOC_TRANSFER:
        if (copy_from_user(&xfer, (struct spi_sensor_xfer __user *)arg,
                           sizeof(xfer)))
            return -EFAULT;

        if (xfer.len == 0)
            return 0;

        if (xfer.len > SPI_SENSOR_MAX_XFER_LEN)
            return -EINVAL;

        /* 分配临时缓冲区 */
        tx_buf = kzalloc(xfer.len, GFP_KERNEL);
        rx_buf = kzalloc(xfer.len, GFP_KERNEL);
        if (!tx_buf || !rx_buf) {
            ret = -ENOMEM;
            goto xfer_err;
        }

        /* 从用户空间复制发送数据 */
        if (xfer.tx_buf) {
            if (copy_from_user(tx_buf, (void __user *)xfer.tx_buf, xfer.len)) {
                ret = -EFAULT;
                goto xfer_err;
            }
        }

        /* 执行 SPI 传输 */
        mutex_lock(&ssd->lock);
        ret = spi_sensor_transfer(ssd, tx_buf, rx_buf, xfer.len);
        mutex_unlock(&ssd->lock);

        if (ret < 0)
            goto xfer_err;

        /* 复制接收数据到用户空间 */
        if (xfer.rx_buf) {
            if (copy_to_user((void __user *)xfer.rx_buf, rx_buf, xfer.len)) {
                ret = -EFAULT;
                goto xfer_err;
            }
        }

        kfree(tx_buf);
        kfree(rx_buf);
        break;

xfer_err:
        kfree(tx_buf);
        kfree(rx_buf);
        return ret;

    case SPI_SENSOR_IOC_GET_STATS:
        mutex_lock(&ssd->lock);
        stats.tx_bytes = ssd->tx_bytes;
        stats.rx_bytes = ssd->rx_bytes;
        stats.errors = ssd->errors;
        stats.transfers = ssd->transfers;
        mutex_unlock(&ssd->lock);

        if (copy_to_user((struct spi_sensor_stats __user *)arg,
                         &stats, sizeof(stats)))
            return -EFAULT;
        break;

    default:
        return -ENOTTY;
    }

    return ret;
}

static const struct file_operations spi_sensor_fops = {
    .owner = THIS_MODULE,
    .open = spi_sensor_open,
    .release = spi_sensor_release,
    .read = spi_sensor_read,
    .write = spi_sensor_write,
    .poll = spi_sensor_poll,
    .unlocked_ioctl = spi_sensor_ioctl,
};

/* ── sysfs 属性 ─────────────────────────────────────────── */
/*
 * 导出传感器状态到 /sys/class/edge-sensor/spi_sensor/
 *
 * 属性:
 *   tx_bytes_total   — 累计发送字节数
 *   rx_bytes_total   — 累计接收字节数
 *   errors           — 传输错误次数
 *   transfers        — 传输总次数
 *   speed_hz         — 当前时钟频率 (可读写)
 *   mode             — 当前 SPI 模式 (可读写)
 *   bits_per_word    — 当前字长 (可读写)
 */

static ssize_t tx_bytes_total_show(struct device *dev,
                                    struct device_attribute *attr, char *buf)
{
    struct spi_sensor_dev *ssd = dev_get_drvdata(dev);
    return sprintf(buf, "%lu\n", ssd->tx_bytes);
}

static ssize_t rx_bytes_total_show(struct device *dev,
                                    struct device_attribute *attr, char *buf)
{
    struct spi_sensor_dev *ssd = dev_get_drvdata(dev);
    return sprintf(buf, "%lu\n", ssd->rx_bytes);
}

static ssize_t errors_show(struct device *dev,
                           struct device_attribute *attr, char *buf)
{
    struct spi_sensor_dev *ssd = dev_get_drvdata(dev);
    return sprintf(buf, "%lu\n", ssd->errors);
}

static ssize_t transfers_show(struct device *dev,
                              struct device_attribute *attr, char *buf)
{
    struct spi_sensor_dev *ssd = dev_get_drvdata(dev);
    return sprintf(buf, "%lu\n", ssd->transfers);
}

static ssize_t speed_hz_show(struct device *dev,
                             struct device_attribute *attr, char *buf)
{
    struct spi_sensor_dev *ssd = dev_get_drvdata(dev);
    return sprintf(buf, "%u\n", ssd->speed_hz);
}

static ssize_t speed_hz_store(struct device *dev,
                              struct device_attribute *attr,
                              const char *buf, size_t count)
{
    struct spi_sensor_dev *ssd = dev_get_drvdata(dev);
    unsigned long speed;
    int ret;

    ret = kstrtoul(buf, 10, &speed);
    if (ret)
        return ret;

    mutex_lock(&ssd->lock);
    ssd->speed_hz = speed;
    ssd->spi->max_speed_hz = speed;
    ret = spi_setup(ssd->spi);
    mutex_unlock(&ssd->lock);

    if (ret)
        return ret;

    return count;
}

static ssize_t mode_show(struct device *dev,
                         struct device_attribute *attr, char *buf)
{
    struct spi_sensor_dev *ssd = dev_get_drvdata(dev);
    return sprintf(buf, "%u\n", ssd->mode);
}

static ssize_t mode_store(struct device *dev,
                          struct device_attribute *attr,
                          const char *buf, size_t count)
{
    struct spi_sensor_dev *ssd = dev_get_drvdata(dev);
    unsigned int mode;
    int ret;

    ret = kstrtouint(buf, 10, &mode);
    if (ret)
        return ret;

    if (mode > 3)
        return -EINVAL;

    mutex_lock(&ssd->lock);
    ssd->mode = mode;
    ssd->spi->mode &= ~(SPI_CPOL | SPI_CPHA);
    ssd->spi->mode |= (mode & SPI_MODE_X_MASK);
    ret = spi_setup(ssd->spi);
    mutex_unlock(&ssd->lock);

    if (ret)
        return ret;

    return count;
}

static ssize_t bits_per_word_show(struct device *dev,
                                  struct device_attribute *attr, char *buf)
{
    struct spi_sensor_dev *ssd = dev_get_drvdata(dev);
    return sprintf(buf, "%u\n", ssd->bits_per_word);
}

static ssize_t bits_per_word_store(struct device *dev,
                                   struct device_attribute *attr,
                                   const char *buf, size_t count)
{
    struct spi_sensor_dev *ssd = dev_get_drvdata(dev);
    unsigned int bits;
    int ret;

    ret = kstrtouint(buf, 10, &bits);
    if (ret)
        return ret;

    if (bits != 8 && bits != 16 && bits != 32)
        return -EINVAL;

    mutex_lock(&ssd->lock);
    ssd->bits_per_word = bits;
    ssd->spi->bits_per_word = bits;
    ret = spi_setup(ssd->spi);
    mutex_unlock(&ssd->lock);

    if (ret)
        return ret;

    return count;
}

/* 定义 sysfs 属性 */
static DEVICE_ATTR_RO(tx_bytes_total);
static DEVICE_ATTR_RO(rx_bytes_total);
static DEVICE_ATTR_RO(errors);
static DEVICE_ATTR_RO(transfers);
static DEVICE_ATTR_RW(speed_hz);
static DEVICE_ATTR_RW(mode);
static DEVICE_ATTR_RW(bits_per_word);

static struct attribute *spi_sensor_attrs[] = {
    &dev_attr_tx_bytes_total.attr,
    &dev_attr_rx_bytes_total.attr,
    &dev_attr_errors.attr,
    &dev_attr_transfers.attr,
    &dev_attr_speed_hz.attr,
    &dev_attr_mode.attr,
    &dev_attr_bits_per_word.attr,
    NULL,
};
ATTRIBUTE_GROUPS(spi_sensor);

/* ── SPI 驱动 probe/remove ──────────────────────────────── */

/*
 * spi_sensor_parse_dt — 解析设备树配置
 */
static int spi_sensor_parse_dt(struct spi_sensor_dev *ssd)
{
    struct device *dev = ssd->dev;
    struct device_node *np = dev->of_node;
    u32 val;

    /* SPI 时钟频率 */
    if (of_property_read_u32(np, "spi-max-frequency", &val))
        ssd->speed_hz = DEFAULT_SPI_SPEED;
    else
        ssd->speed_hz = val;

    /* SPI 模式 (从设备树 spi-cpol/spi-cpha 解析) */
    ssd->mode = (ssd->spi->mode & SPI_MODE_X_MASK);

    /* 字长 */
    if (of_property_read_u32(np, "spi-bits-per-word", &val))
        ssd->bits_per_word = DEFAULT_SPI_BITS;
    else
        ssd->bits_per_word = val;

    dev_info(dev, "Config: %u Hz, Mode %u, %u bits/word\n",
             ssd->speed_hz, ssd->mode, ssd->bits_per_word);

    return 0;
}

/*
 * spi_sensor_probe — SPI 设备匹配后调用
 *
 * 流程:
 *   1. 分配驱动私有数据
 *   2. 解析设备树配置
 *   3. 初始化 SPI 参数
 *   4. 创建字符设备 (/dev/spi_sensor)
 *   5. 创建 sysfs 属性
 */
static int spi_sensor_probe(struct spi_device *spi)
{
    struct spi_sensor_dev *ssd;
    struct device *dev = &spi->dev;
    int ret;

    ssd = devm_kzalloc(dev, sizeof(*ssd), GFP_KERNEL);
    if (!ssd)
        return -ENOMEM;

    ssd->spi = spi;
    ssd->dev = dev;
    spi_set_drvdata(spi, ssd);

    /* 解析设备树 */
    ret = spi_sensor_parse_dt(ssd);
    if (ret)
        return ret;

    /* 初始化 SPI 参数 */
    spi->max_speed_hz = ssd->speed_hz;
    spi->bits_per_word = ssd->bits_per_word;
    ret = spi_setup(spi);
    if (ret) {
        dev_err(dev, "Failed to setup SPI: %d\n", ret);
        return ret;
    }

    mutex_init(&ssd->lock);

    /* 创建 device class (只需创建一次, 多设备共享) */
    if (!spi_sensor_class) {
        spi_sensor_class = class_create(THIS_MODULE, CLASS_NAME);
        if (IS_ERR(spi_sensor_class)) {
            ret = PTR_ERR(spi_sensor_class);
            dev_err(dev, "Failed to create class: %d\n", ret);
            return ret;
        }
        spi_sensor_class->dev_groups = spi_sensor_groups;
    }

    /* 分配字符设备号 */
    ret = alloc_chrdev_region(&ssd->devt, 0, 1, DEVICE_NAME);
    if (ret) {
        dev_err(dev, "Failed to alloc chrdev: %d\n", ret);
        goto err_class;
    }

    /* 初始化字符设备 */
    cdev_init(&ssd->cdev, &spi_sensor_fops);
    ssd->cdev.owner = THIS_MODULE;

    ret = cdev_add(&ssd->cdev, ssd->devt, 1);
    if (ret) {
        dev_err(dev, "Failed to add cdev: %d\n", ret);
        goto err_chrdev;
    }

    /* 创建设备节点 /dev/spi_sensor */
    ssd->chardev = device_create(spi_sensor_class, dev, ssd->devt,
                                  ssd, DEVICE_NAME);
    if (IS_ERR(ssd->chardev)) {
        ret = PTR_ERR(ssd->chardev);
        dev_err(dev, "Failed to create device: %d\n", ret);
        goto err_cdev;
    }

    dev_info(dev, "SPI sensor driver probed (%s at %u Hz)\n",
             DEVICE_NAME, ssd->speed_hz);
    return 0;

err_cdev:
    cdev_del(&ssd->cdev);
err_chrdev:
    unregister_chrdev_region(ssd->devt, 1);
err_class:
    /* class 由最后一个 remove 或 module_exit 销毁 */
    return ret;
}

/*
 * spi_sensor_remove — SPI 设备移除
 *
 * 四层逆序释放:
 *   1. 删除 sysfs 设备节点
 *   2. 删除 cdev
 *   3. 释放 chrdev 区域
 *   4. 销毁 class (由 module_exit 统一处理)
 */
static int spi_sensor_remove(struct spi_device *spi)
{
    struct spi_sensor_dev *ssd = spi_get_drvdata(spi);

    device_destroy(spi_sensor_class, ssd->devt);
    cdev_del(&ssd->cdev);
    unregister_chrdev_region(ssd->devt, 1);

    dev_info(&spi->dev, "SPI sensor driver removed\n");
    return 0;
}

/* ── 设备树匹配表 ──────────────────────────────────────── */
static const struct of_device_id spi_sensor_of_match[] = {
    { .compatible = "edge-ai,spi-sensor" },
    { /* sentinel */ }
};
MODULE_DEVICE_TABLE(of, spi_sensor_of_match);

/* ── SPI 驱动结构 ──────────────────────────────────────── */
static struct spi_driver spi_sensor_driver = {
    .driver = {
        .name = DRIVER_NAME,
        .of_match_table = spi_sensor_of_match,
        .owner = THIS_MODULE,
    },
    .probe = spi_sensor_probe,
    .remove = spi_sensor_remove,
};

/*
 * spi_sensor_init — 模块初始化
 */
static int __init spi_sensor_init(void)
{
    int ret;

    ret = spi_register_driver(&spi_sensor_driver);
    if (ret) {
        pr_err("Failed to register SPI driver: %d\n", ret);
        return ret;
    }

    pr_info("SPI sensor driver registered\n");
    return 0;
}

/*
 * spi_sensor_exit — 模块卸载
 */
static void __exit spi_sensor_exit(void)
{
    spi_unregister_driver(&spi_sensor_driver);

    if (spi_sensor_class) {
        class_destroy(spi_sensor_class);
        spi_sensor_class = NULL;
    }

    pr_info("SPI sensor driver unregistered\n");
}

module_init(spi_sensor_init);
module_exit(spi_sensor_exit);

MODULE_DESCRIPTION("SPI Sensor Character Device Driver for Edge AI");
MODULE_AUTHOR("Edge AI Vision Project");
MODULE_LICENSE("GPL");
