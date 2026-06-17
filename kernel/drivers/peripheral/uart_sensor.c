/* SPDX-License-Identifier: GPL-2.0+ */
/*
 * UART Sensor Character Device Driver for RK3399Pro
 *
 * 功能: 将 UART 外设封装为字符设备, 用户空间通过 /dev/uart_sensor
 *       读取传感器数据 (GPS NMEA / 环境传感器自定义协议)
 *
 * 内核框架: 字符设备 (cdev) + 串口核心层 (tty/serdev)
 * 中断处理: UART RX 中断 → 环形缓冲区 → 唤醒阻塞的 read()
 * 用户接口: /dev/uart_sensor (read/write/ioctl) + /sys/class/edge-sensor/
 *
 * 设备树绑定:
 *   compatible = "edge-ai,uart-sensor";
 *   在目标 UART 节点 (如 &uart4) 下作为子节点
 *
 * 参考: drivers/tty/serial/8250/8250_core.c
 *       Documentation/driver-api/serial/serial-rs485.rst
 */

#include <linux/cdev.h>
#include <linux/device.h>
#include <linux/fs.h>
#include <linux/init.h>
#include <linux/interrupt.h>
#include <linux/io.h>
#include <linux/kernel.h>
#include <linux/module.h>
#include <linux/of.h>
#include <linux/platform_device.h>
#include <linux/poll.h>
#include <linux/sched.h>
#include <linux/serdev.h>
#include <linux/slab.h>
#include <linux/uaccess.h>
#include <linux/wait.h>
#include <linux/workqueue.h>

#define DRIVER_NAME     "uart_sensor"
#define DEVICE_NAME     "uart_sensor"
#define CLASS_NAME      "edge-sensor"

/* 默认环形缓冲区大小: 4KB */
#define DEFAULT_RX_BUF_SIZE     4096
#define MAX_RX_BUF_SIZE         65536

/* ioctl 命令 */
#define UART_SENSOR_IOC_MAGIC   'U'
#define UART_SENSOR_IOC_GET_BAUD    _IOR(UART_SENSOR_IOC_MAGIC, 1, int)
#define UART_SENSOR_IOC_SET_BAUD    _IOW(UART_SENSOR_IOC_MAGIC, 2, int)
#define UART_SENSOR_IOC_FLUSH_RX    _IO(UART_SENSOR_IOC_MAGIC, 3)
#define UART_SENSOR_IOC_GET_RX_CNT  _IOR(UART_SENSOR_IOC_MAGIC, 4, int)

/* ── 环形缓冲区 ────────────────────────────────────────── */
struct ring_buffer {
    u8 *buf;
    int size;
    int head;   /* 写入位置 */
    int tail;   /* 读取位置 */
    int count;  /* 当前数据量 */
    spinlock_t lock;
};

static void ring_buffer_init(struct ring_buffer *rb, int size)
{
    rb->buf = kzalloc(size, GFP_KERNEL);
    rb->size = size;
    rb->head = 0;
    rb->tail = 0;
    rb->count = 0;
    spin_lock_init(&rb->lock);
}

static void ring_buffer_free(struct ring_buffer *rb)
{
    kfree(rb->buf);
    rb->buf = NULL;
}

/* 写入一个字节到环形缓冲区 (在中断上下文中调用) */
static int ring_buffer_put(struct ring_buffer *rb, u8 data)
{
    unsigned long flags;
    int ret = 0;

    spin_lock_irqsave(&rb->lock, flags);

    if (rb->count >= rb->size) {
        /* 缓冲区满, 丢弃最旧的数据 */
        rb->tail = (rb->tail + 1) % rb->size;
        rb->count--;
        ret = -ENOSPC;
    }

    rb->buf[rb->head] = data;
    rb->head = (rb->head + 1) % rb->size;
    rb->count++;

    spin_unlock_irqrestore(&rb->lock, flags);
    return ret;
}

/* 从环形缓冲区读取一个字节 (在用户上下文中调用) */
static int ring_buffer_get(struct ring_buffer *rb, u8 *data)
{
    unsigned long flags;
    int ret = 0;

    spin_lock_irqsave(&rb->lock, flags);

    if (rb->count == 0) {
        ret = -EAGAIN;
        goto out;
    }

    *data = rb->buf[rb->tail];
    rb->tail = (rb->tail + 1) % rb->size;
    rb->count--;

out:
    spin_unlock_irqrestore(&rb->lock, flags);
    return ret;
}

/* ── 驱动私有数据 ──────────────────────────────────────── */
struct uart_sensor_dev {
    struct platform_device *pdev;
    struct device *dev;

    /* 字符设备 */
    dev_t devt;
    struct cdev cdev;
    struct class *class;
    struct device *chardev;

    /* 串口设备 */
    struct serdev_device *serdev;

    /* 环形缓冲区 */
    struct ring_buffer rx_ring;

    /* 等待队列 — read() 阻塞等待数据 */
    wait_queue_head_t read_wait;

    /* 统计 */
    atomic_t rx_bytes_total;
    atomic_t rx_overruns;

    /* 配置 */
    int baudrate;
    int data_bits;
    int stop_bits;
    const char *parity;
};

/* ── UART 接收回调 (serdev 框架, 中断上下文) ──────────── */
/*
 * uart_sensor_receive_buf — serdev 接收回调
 *
 * 由串口核心层在 RX 中断中调用。
 * 将接收到的数据写入环形缓冲区, 然后唤醒等待的 read()。
 *
 * 注意: 此函数在中断上下文中执行, 不能睡眠!
 */
static int uart_sensor_receive_buf(struct serdev_device *serdev,
                                   const u8 *data, size_t count)
{
    struct uart_sensor_dev *usd = serdev_device_get_drvdata(serdev);
    int i, ret;

    for (i = 0; i < count; i++) {
        ret = ring_buffer_put(&usd->rx_ring, data[i]);
        if (ret == -ENOSPC)
            atomic_inc(&usd->rx_overruns);
    }

    atomic_add(count, &usd->rx_bytes_total);

    /* 唤醒阻塞在 read() 上的进程 */
    wake_up_interruptible(&usd->read_wait);

    return count;
}

/* serdev 操作表 */
static const struct serdev_device_ops uart_sensor_serdev_ops = {
    .receive_buf = uart_sensor_receive_buf,
};

/* ── 字符设备文件操作 ──────────────────────────────────── */

/*
 * uart_sensor_open — 打开设备
 */
static int uart_sensor_open(struct inode *inode, struct file *filp)
{
    struct uart_sensor_dev *usd =
        container_of(inode->i_cdev, struct uart_sensor_dev, cdev);

    filp->private_data = usd;

    dev_dbg(usd->dev, "Device opened\n");
    return 0;
}

/*
 * uart_sensor_release — 关闭设备
 */
static int uart_sensor_release(struct inode *inode, struct file *filp)
{
    struct uart_sensor_dev *usd = filp->private_data;

    dev_dbg(usd->dev, "Device closed\n");
    return 0;
}

/*
 * uart_sensor_read — 从环形缓冲区读取传感器数据
 *
 * 如果缓冲区为空, 阻塞等待 (interruptible)
 * 返回读取的字节数, 或 -ERESTARTSYS (被信号中断)
 */
static ssize_t uart_sensor_read(struct file *filp, char __user *buf,
                                size_t count, loff_t *f_pos)
{
    struct uart_sensor_dev *usd = filp->private_data;
    u8 *tmp_buf;
    ssize_t ret = 0;
    int i, byte_ret;

    if (count == 0)
        return 0;

    /* 分配临时缓冲区 */
    tmp_buf = kmalloc(min(count, (size_t)usd->rx_ring.size), GFP_KERNEL);
    if (!tmp_buf)
        return -ENOMEM;

    /* 阻塞等待数据 */
    ret = wait_event_interruptible(
        usd->read_wait,
        usd->rx_ring.count > 0 || !serdev_device_get_drvdata(usd->serdev));

    if (ret) {
        kfree(tmp_buf);
        return ret;  /* -ERESTARTSYS */
    }

    /* 从环形缓冲区读取 */
    for (i = 0; i < count; i++) {
        byte_ret = ring_buffer_get(&usd->rx_ring, &tmp_buf[i]);
        if (byte_ret == -EAGAIN)
            break;
    }

    if (i == 0) {
        kfree(tmp_buf);
        return 0;
    }

    /* 拷贝到用户空间 */
    ret = copy_to_user(buf, tmp_buf, i);
    kfree(tmp_buf);

    if (ret)
        return -EFAULT;

    return i;
}

/*
 * uart_sensor_write — 向传感器发送指令
 *
 * 通过 serdev 发送数据 (例如配置传感器参数)
 */
static ssize_t uart_sensor_write(struct file *filp, const char __user *buf,
                                 size_t count, loff_t *f_pos)
{
    struct uart_sensor_dev *usd = filp->private_data;
    u8 *tmp_buf;
    int ret;

    if (count == 0)
        return 0;

    tmp_buf = kmalloc(count, GFP_KERNEL);
    if (!tmp_buf)
        return -ENOMEM;

    ret = copy_from_user(tmp_buf, buf, count);
    if (ret) {
        kfree(tmp_buf);
        return -EFAULT;
    }

    ret = serdev_device_write_buf(usd->serdev, tmp_buf, count);
    kfree(tmp_buf);

    if (ret < 0)
        return ret;

    return count;
}

/*
 * uart_sensor_poll — 支持 select/poll/epoll
 */
static __poll_t uart_sensor_poll(struct file *filp, poll_table *wait)
{
    struct uart_sensor_dev *usd = filp->private_data;
    __poll_t mask = 0;

    poll_wait(filp, &usd->read_wait, wait);

    if (usd->rx_ring.count > 0)
        mask |= EPOLLIN | EPOLLRDNORM;  /* 可读 */

    /* 始终可写 */
    mask |= EPOLLOUT | EPOLLWRNORM;

    return mask;
}

/*
 * uart_sensor_ioctl — 设备控制
 */
static long uart_sensor_ioctl(struct file *filp, unsigned int cmd,
                              unsigned long arg)
{
    struct uart_sensor_dev *usd = filp->private_data;
    int val, ret;

    switch (cmd) {
    case UART_SENSOR_IOC_GET_BAUD:
        val = usd->baudrate;
        ret = put_user(val, (int __user *)arg);
        break;

    case UART_SENSOR_IOC_SET_BAUD:
        ret = get_user(val, (int __user *)arg);
        if (ret)
            return ret;
        usd->baudrate = val;
        /* 实际设置波特率需要操作 UART 硬件寄存器,
         * 这里简化处理, 实际项目通过 serdev 接口设置 */
        dev_info(usd->dev, "Baudrate set to %d\n", val);
        ret = 0;
        break;

    case UART_SENSOR_IOC_FLUSH_RX: {
        unsigned long flags;
        spin_lock_irqsave(&usd->rx_ring.lock, flags);
        usd->rx_ring.head = 0;
        usd->rx_ring.tail = 0;
        usd->rx_ring.count = 0;
        spin_unlock_irqrestore(&usd->rx_ring.lock, flags);
        ret = 0;
        break;
    }

    case UART_SENSOR_IOC_GET_RX_CNT:
        val = usd->rx_ring.count;
        ret = put_user(val, (int __user *)arg);
        break;

    default:
        ret = -ENOTTY;
        break;
    }

    return ret;
}

static const struct file_operations uart_sensor_fops = {
    .owner = THIS_MODULE,
    .open = uart_sensor_open,
    .release = uart_sensor_release,
    .read = uart_sensor_read,
    .write = uart_sensor_write,
    .poll = uart_sensor_poll,
    .unlocked_ioctl = uart_sensor_ioctl,
};

/* ── sysfs 属性 ─────────────────────────────────────────── */
/*
 * 导出传感器状态到 /sys/class/edge-sensor/uart_sensor/
 *
 * 属性:
 *   rx_bytes_total  — 累计接收字节数
 *   rx_overruns     — 缓冲区溢出次数
 *   rx_count        — 当前缓冲区数据量
 *   baudrate        — 当前波特率
 */

static ssize_t rx_bytes_total_show(struct device *dev,
                                   struct device_attribute *attr, char *buf)
{
    struct uart_sensor_dev *usd = dev_get_drvdata(dev);
    return sprintf(buf, "%d\n", atomic_read(&usd->rx_bytes_total));
}

static ssize_t rx_overruns_show(struct device *dev,
                                struct device_attribute *attr, char *buf)
{
    struct uart_sensor_dev *usd = dev_get_drvdata(dev);
    return sprintf(buf, "%d\n", atomic_read(&usd->rx_overruns));
}

static ssize_t rx_count_show(struct device *dev,
                             struct device_attribute *attr, char *buf)
{
    struct uart_sensor_dev *usd = dev_get_drvdata(dev);
    return sprintf(buf, "%d\n", usd->rx_ring.count);
}

static ssize_t baudrate_show(struct device *dev,
                             struct device_attribute *attr, char *buf)
{
    struct uart_sensor_dev *usd = dev_get_drvdata(dev);
    return sprintf(buf, "%d\n", usd->baudrate);
}

static DEVICE_ATTR_RO(rx_bytes_total);
static DEVICE_ATTR_RO(rx_overruns);
static DEVICE_ATTR_RO(rx_count);
static DEVICE_ATTR_RO(baudrate);

static struct attribute *uart_sensor_attrs[] = {
    &dev_attr_rx_bytes_total.attr,
    &dev_attr_rx_overruns.attr,
    &dev_attr_rx_count.attr,
    &dev_attr_baudrate.attr,
    NULL,
};
ATTRIBUTE_GROUPS(uart_sensor);

/* ── Platform 驱动 probe/remove ────────────────────────── */

/*
 * uart_sensor_parse_dt — 解析设备树配置
 */
static int uart_sensor_parse_dt(struct uart_sensor_dev *usd)
{
    struct device *dev = usd->dev;
    struct device_node *np = dev->of_node;
    u32 val;

    if (of_property_read_u32(np, "baudrate", &val))
        usd->baudrate = 115200;  /* 默认 */
    else
        usd->baudrate = val;

    if (of_property_read_u32(np, "data-bits", &val))
        usd->data_bits = 8;
    else
        usd->data_bits = val;

    if (of_property_read_u32(np, "stop-bits", &val))
        usd->stop_bits = 1;
    else
        usd->stop_bits = val;

    if (of_property_read_string(np, "parity", &usd->parity))
        usd->parity = "none";

    dev_info(dev, "Config: %d baud, %d%c%d\n",
             usd->baudrate, usd->data_bits,
             usd->parity ? usd->parity[0] : 'N', usd->stop_bits);

    return 0;
}

/*
 * uart_sensor_probe — 平台设备匹配后调用
 *
 * 流程:
 *   1. 解析设备树配置
 *   2. 初始化环形缓冲区
 *   3. 初始化等待队列
 *   4. 获取父节点 UART 的 serdev 设备
 *   5. 设置 serdev 操作回调
 *   6. 创建字符设备 (/dev/uart_sensor)
 *   7. 创建 sysfs 属性
 */
static int uart_sensor_probe(struct platform_device *pdev)
{
    struct device *dev = &pdev->dev;
    struct device_node *parent_np;
    struct uart_sensor_dev *usd;
    int ret, rx_buf_size;

    usd = devm_kzalloc(dev, sizeof(*usd), GFP_KERNEL);
    if (!usd)
        return -ENOMEM;

    usd->pdev = pdev;
    usd->dev = dev;
    platform_set_drvdata(pdev, usd);

    /* 解析设备树 */
    ret = uart_sensor_parse_dt(usd);
    if (ret)
        return ret;

    /* 环形缓冲区大小 */
    if (of_property_read_u32(dev->of_node, "read-buffer-size",
                             &rx_buf_size))
        rx_buf_size = DEFAULT_RX_BUF_SIZE;
    if (rx_buf_size > MAX_RX_BUF_SIZE)
        rx_buf_size = MAX_RX_BUF_SIZE;

    ring_buffer_init(&usd->rx_ring, rx_buf_size);
    init_waitqueue_head(&usd->read_wait);
    atomic_set(&usd->rx_bytes_total, 0);
    atomic_set(&usd->rx_overruns, 0);

    /* 获取父节点 UART 的 serdev */
    parent_np = of_get_parent(dev->of_node);
    if (!parent_np) {
        dev_err(dev, "No parent UART node\n");
        ret = -ENODEV;
        goto err_ring;
    }

    usd->serdev = serdev_device_get_by_node(parent_np);
    of_node_put(parent_np);

    if (!usd->serdev) {
        dev_err(dev, "Failed to get serdev from parent UART\n");
        ret = -ENODEV;
        goto err_ring;
    }

    serdev_device_set_drvdata(usd->serdev, usd);
    serdev_device_set_client_ops(usd->serdev, &uart_sensor_serdev_ops);

    /* 打开串口 */
    ret = serdev_device_open(usd->serdev);
    if (ret) {
        dev_err(dev, "Failed to open serdev: %d\n", ret);
        goto err_serdev;
    }

    /* 设置波特率 */
    serdev_device_set_baudrate(usd->serdev, usd->baudrate);

    /* ── 创建字符设备 ── */
    ret = alloc_chrdev_region(&usd->devt, 0, 1, DEVICE_NAME);
    if (ret) {
        dev_err(dev, "Failed to alloc chrdev: %d\n", ret);
        goto err_serdev_open;
    }

    cdev_init(&usd->cdev, &uart_sensor_fops);
    usd->cdev.owner = THIS_MODULE;

    ret = cdev_add(&usd->cdev, usd->devt, 1);
    if (ret) {
        dev_err(dev, "Failed to add cdev: %d\n", ret);
        goto err_chrdev;
    }

    /* 创建 device class */
    usd->class = class_create(THIS_MODULE, CLASS_NAME);
    if (IS_ERR(usd->class)) {
        ret = PTR_ERR(usd->class);
        dev_err(dev, "Failed to create class: %d\n", ret);
        goto err_cdev;
    }
    usd->class->dev_groups = uart_sensor_groups;

    usd->chardev = device_create(usd->class, dev, usd->devt,
                                 usd, DEVICE_NAME);
    if (IS_ERR(usd->chardev)) {
        ret = PTR_ERR(usd->chardev);
        dev_err(dev, "Failed to create device: %d\n", ret);
        goto err_class;
    }

    dev_info(dev, "UART sensor driver probed (%s at %d baud)\n",
             DEVICE_NAME, usd->baudrate);
    return 0;

err_class:
    class_destroy(usd->class);
err_cdev:
    cdev_del(&usd->cdev);
err_chrdev:
    unregister_chrdev_region(usd->devt, 1);
err_serdev_open:
    serdev_device_close(usd->serdev);
err_serdev:
    serdev_device_put(usd->serdev);
err_ring:
    ring_buffer_free(&usd->rx_ring);
    return ret;
}

/*
 * uart_sensor_remove — 平台设备移除
 *
 * 五层逆序释放:
 *   1. 删除 sysfs 设备节点
 *   2. 删除 class
 *   3. 删除 cdev
 *   4. 释放 chrdev 区域
 *   5. 关闭 serdev
 *   6. 释放环形缓冲区
 */
static int uart_sensor_remove(struct platform_device *pdev)
{
    struct uart_sensor_dev *usd = platform_get_drvdata(pdev);

    device_destroy(usd->class, usd->devt);
    class_destroy(usd->class);
    cdev_del(&usd->cdev);
    unregister_chrdev_region(usd->devt, 1);

    serdev_device_close(usd->serdev);
    serdev_device_put(usd->serdev);

    ring_buffer_free(&usd->rx_ring);

    dev_info(&pdev->dev, "UART sensor driver removed\n");
    return 0;
}

/* ── 设备树匹配表 ──────────────────────────────────────── */
static const struct of_device_id uart_sensor_of_match[] = {
    { .compatible = "edge-ai,uart-sensor" },
    { /* sentinel */ }
};
MODULE_DEVICE_TABLE(of, uart_sensor_of_match);

/* ── Platform 驱动结构 ─────────────────────────────────── */
static struct platform_driver uart_sensor_driver = {
    .driver = {
        .name = DRIVER_NAME,
        .of_match_table = uart_sensor_of_match,
        .owner = THIS_MODULE,
    },
    .probe = uart_sensor_probe,
    .remove = uart_sensor_remove,
};

module_platform_driver(uart_sensor_driver);

MODULE_DESCRIPTION("UART Sensor Character Device Driver for Edge AI");
MODULE_AUTHOR("Edge AI Vision Project");
MODULE_LICENSE("GPL");
