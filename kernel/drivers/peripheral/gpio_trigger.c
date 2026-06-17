/* SPDX-License-Identifier: GPL-2.0+ */
/*
 * GPIO Trigger Driver for RK3399Pro Edge AI Camera
 *
 * 功能: 将 GPIO 中断封装为字符设备, 用户空间通过 /dev/gpio_trigger
 *       等待 GPIO 事件 (按键按下/传感器触发/外部报警信号)
 *
 * 内核框架: 字符设备 (cdev) + GPIO 中断 (gpio_to_irq)
 * 中断处理: 顶半部 (hardirq) → tasklet 底半部 → 唤醒 poll/read
 * 用户接口: /dev/gpio_trigger (read/poll) + /sys/class/edge-sensor/
 *
 * 设备树绑定:
 *   compatible = "edge-ai,gpio-trigger";
 *   在根节点下作为独立设备节点
 *
 * 参考: drivers/input/keyboard/gpio_keys.c
 *       Documentation/driver-api/gpio/driver.rst
 */

#include <linux/cdev.h>
#include <linux/device.h>
#include <linux/fs.h>
#include <linux/gpio.h>
#include <linux/gpio/consumer.h>
#include <linux/init.h>
#include <linux/interrupt.h>
#include <linux/kernel.h>
#include <linux/module.h>
#include <linux/of.h>
#include <linux/of_gpio.h>
#include <linux/platform_device.h>
#include <linux/poll.h>
#include <linux/slab.h>
#include <linux/uaccess.h>
#include <linux/wait.h>
#include <linux/workqueue.h>

#define DRIVER_NAME     "gpio_trigger"
#define DEVICE_NAME     "gpio_trigger"
#define CLASS_NAME      "edge-sensor"

/* 最大支持的 GPIO 数量 */
#define MAX_GPIO_TRIGGERS   8

/* ioctl 命令 */
#define GPIO_TRIGGER_IOC_MAGIC   'G'
#define GPIO_TRIGGER_IOC_GET_COUNT   _IOR(GPIO_TRIGGER_IOC_MAGIC, 1, int)
#define GPIO_TRIGGER_IOC_CLEAR_COUNT _IO(GPIO_TRIGGER_IOC_MAGIC, 2)
#define GPIO_TRIGGER_IOC_GET_DEBOUNCE _IOR(GPIO_TRIGGER_IOC_MAGIC, 3, int)
#define GPIO_TRIGGER_IOC_SET_DEBOUNCE _IOW(GPIO_TRIGGER_IOC_MAGIC, 4, int)

/* ── 单个 GPIO 触发器 ──────────────────────────────────── */
struct gpio_trigger_pin {
    int index;                  /* 序号 */
    struct gpio_desc *desc;     /* GPIO descriptor */
    int irq;                    /* 中断号 */
    const char *label;          /* 标签 (设备树) */
    u32 debounce_ms;            /* 去抖时间 (ms) */

    /* 统计 */
    atomic_t irq_count;         /* 中断计数 */
    ktime_t last_irq_time;      /* 上次中断时间 (去抖用) */

    /* 反向指针 — 中断 handler 需要访问父 dev */
    struct gpio_trigger_dev *parent;
};

/* ── 驱动私有数据 ──────────────────────────────────────── */
struct gpio_trigger_dev {
    struct platform_device *pdev;
    struct device *dev;

    /* 字符设备 */
    dev_t devt;
    struct cdev cdev;
    struct class *class;
    struct device *chardev;

    /* GPIO 触发器数组 */
    struct gpio_trigger_pin pins[MAX_GPIO_TRIGGERS];
    int num_pins;

    /* 事件队列 — 记录触发的 GPIO 序号 */
    int event_queue[64];
    int event_head;
    int event_tail;
    int event_count;
    spinlock_t event_lock;

    /* 等待队列 */
    wait_queue_head_t event_wait;

    /* 全局统计 */
    atomic_t total_triggers;

    /* tasklet 底半部 — 中断事件调度 */
    struct tasklet_struct tasklet;
    int tasklet_data;
};

/* ── GPIO 中断处理 ─────────────────────────────────────── */
/*
 * gpio_trigger_tasklet_func — tasklet 底半部
 *
 * 在中断上下文之外执行 (但仍是原子上下文, 不能睡眠):
 *   1. 记录事件到队列
 *   2. 唤醒等待的 poll/read
 *
 * 为什么用 tasklet:
 *   - 顶半部 (hardirq) 只做最小工作 (确认中断源)
 *   - tasklet 做实际的事件记录和唤醒
 *   - 避免在 hardirq 中调用可能阻塞的函数
 */
static void gpio_trigger_tasklet_func(struct tasklet_struct *t)
{
    struct gpio_trigger_dev *gtd =
        container_of(t, struct gpio_trigger_dev, tasklet);
    unsigned long flags;

    spin_lock_irqsave(&gtd->event_lock, flags);

    /* 将 tasklet_data 中记录的 GPIO 序号写入事件队列 */
    if (gtd->event_count < ARRAY_SIZE(gtd->event_queue)) {
        gtd->event_queue[gtd->event_head] = gtd->tasklet_data;
        gtd->event_head = (gtd->event_head + 1) %
                          ARRAY_SIZE(gtd->event_queue);
        gtd->event_count++;
    }

    spin_unlock_irqrestore(&gtd->event_lock, flags);

    atomic_inc(&gtd->total_triggers);

    /* 唤醒阻塞的 read/poll */
    wake_up_interruptible(&gtd->event_wait);
}

/*
 * gpio_trigger_irq_handler — GPIO 中断顶半部 (hardirq)
 *
 * 在 hardirq 上下文中执行, 必须快速返回:
 *   1. 确认中断来源 (读取 GPIO 值)
 *   2. 去抖检查
 *   3. 调度 tasklet 做实际处理
 *
 * 返回 IRQ_HANDLED 或 IRQ_NONE (不是我们的中断)
 */
static irqreturn_t gpio_trigger_irq_handler(int irq, void *dev_id)
{
    struct gpio_trigger_pin *pin = dev_id;
    struct gpio_trigger_dev *gtd = pin->parent;  /* 通过反向指针获取父 dev */
    ktime_t now;
    s64 delta_ms;

    /* 去抖: 如果距离上次中断太近, 忽略 */
    now = ktime_get();
    delta_ms = ktime_ms_delta(now, pin->last_irq_time);
    if (delta_ms < pin->debounce_ms)
        return IRQ_HANDLED;  /* 去抖过滤, 但仍确认中断 */

    pin->last_irq_time = now;
    atomic_inc(&pin->irq_count);

    /* 记录触发引脚序号, 调度 tasklet */
    gtd->tasklet_data = pin->index;
    tasklet_schedule(&gtd->tasklet);

    return IRQ_HANDLED;
}

/* ── 字符设备文件操作 ──────────────────────────────────── */

static int gpio_trigger_open(struct inode *inode, struct file *filp)
{
    struct gpio_trigger_dev *gtd =
        container_of(inode->i_cdev, struct gpio_trigger_dev, cdev);

    filp->private_data = gtd;
    dev_dbg(gtd->dev, "GPIO trigger device opened\n");
    return 0;
}

static int gpio_trigger_release(struct inode *inode, struct file *filp)
{
    struct gpio_trigger_dev *gtd = filp->private_data;

    dev_dbg(gtd->dev, "GPIO trigger device closed\n");
    return 0;
}

/*
 * gpio_trigger_read — 读取触发事件
 *
 * 返回触发的 GPIO 序号 (int)。
 * 如果无事件, 阻塞等待。
 */
static ssize_t gpio_trigger_read(struct file *filp, char __user *buf,
                                 size_t count, loff_t *f_pos)
{
    struct gpio_trigger_dev *gtd = filp->private_data;
    unsigned long flags;
    int event, ret;

    if (count < sizeof(int))
        return -EINVAL;

    /* 阻塞等待事件 */
    ret = wait_event_interruptible(
        gtd->event_wait,
        gtd->event_count > 0);

    if (ret)
        return ret;  /* -ERESTARTSYS */

    spin_lock_irqsave(&gtd->event_lock, flags);

    if (gtd->event_count == 0) {
        spin_unlock_irqrestore(&gtd->event_lock, flags);
        return 0;
    }

    event = gtd->event_queue[gtd->event_tail];
    gtd->event_tail = (gtd->event_tail + 1) %
                      ARRAY_SIZE(gtd->event_queue);
    gtd->event_count--;

    spin_unlock_irqrestore(&gtd->event_lock, flags);

    ret = copy_to_user(buf, &event, sizeof(int));
    if (ret)
        return -EFAULT;

    return sizeof(int);
}

/*
 * gpio_trigger_poll — 支持 select/poll/epoll
 */
static __poll_t gpio_trigger_poll(struct file *filp, poll_table *wait)
{
    struct gpio_trigger_dev *gtd = filp->private_data;
    __poll_t mask = 0;

    poll_wait(filp, &gtd->event_wait, wait);

    if (gtd->event_count > 0)
        mask |= EPOLLIN | EPOLLRDNORM;

    return mask;
}

static long gpio_trigger_ioctl(struct file *filp, unsigned int cmd,
                               unsigned long arg)
{
    struct gpio_trigger_dev *gtd = filp->private_data;
    unsigned long flags;
    int val, ret;

    switch (cmd) {
    case GPIO_TRIGGER_IOC_GET_COUNT:
        val = atomic_read(&gtd->total_triggers);
        ret = put_user(val, (int __user *)arg);
        break;

    case GPIO_TRIGGER_IOC_CLEAR_COUNT:
        atomic_set(&gtd->total_triggers, 0);
        spin_lock_irqsave(&gtd->event_lock, flags);
        gtd->event_head = 0;
        gtd->event_tail = 0;
        gtd->event_count = 0;
        spin_unlock_irqrestore(&gtd->event_lock, flags);
        ret = 0;
        break;

    case GPIO_TRIGGER_IOC_GET_DEBOUNCE:
        /* 返回第一个 pin 的去抖值 */
        if (gtd->num_pins > 0)
            val = gtd->pins[0].debounce_ms;
        else
            val = 0;
        ret = put_user(val, (int __user *)arg);
        break;

    case GPIO_TRIGGER_IOC_SET_DEBOUNCE:
        ret = get_user(val, (int __user *)arg);
        if (ret)
            return ret;
        /* 设置所有 pin 的去抖值 */
        for (int i = 0; i < gtd->num_pins; i++)
            gtd->pins[i].debounce_ms = val;
        ret = 0;
        break;

    default:
        ret = -ENOTTY;
        break;
    }

    return ret;
}

static const struct file_operations gpio_trigger_fops = {
    .owner = THIS_MODULE,
    .open = gpio_trigger_open,
    .release = gpio_trigger_release,
    .read = gpio_trigger_read,
    .poll = gpio_trigger_poll,
    .unlocked_ioctl = gpio_trigger_ioctl,
};

/* ── sysfs 属性 ─────────────────────────────────────────── */
static ssize_t total_triggers_show(struct device *dev,
                                   struct device_attribute *attr,
                                   char *buf)
{
    struct gpio_trigger_dev *gtd = dev_get_drvdata(dev);
    return sprintf(buf, "%d\n", atomic_read(&gtd->total_triggers));
}
static DEVICE_ATTR_RO(total_triggers);

static ssize_t num_pins_show(struct device *dev,
                             struct device_attribute *attr, char *buf)
{
    struct gpio_trigger_dev *gtd = dev_get_drvdata(dev);
    return sprintf(buf, "%d\n", gtd->num_pins);
}
static DEVICE_ATTR_RO(num_pins);

static struct attribute *gpio_trigger_attrs[] = {
    &dev_attr_total_triggers.attr,
    &dev_attr_num_pins.attr,
    NULL,
};
ATTRIBUTE_GROUPS(gpio_trigger);

/* ── Platform 驱动 probe/remove ────────────────────────── */

/*
 * gpio_trigger_parse_dt — 解析设备树中的 GPIO 配置
 *
 * 设备树格式:
 *   gpio-trigger {
 *       compatible = "edge-ai,gpio-trigger";
 *       trigger-gpios = <&gpio0 RK_PA2 GPIO_ACTIVE_LOW>,
 *                       <&gpio3 RK_PC1 GPIO_ACTIVE_HIGH>;
 *       trigger-labels = "capture-button", "alarm-input";
 *       debounce-ms = <50>;
 *   };
 */
static int gpio_trigger_parse_dt(struct gpio_trigger_dev *gtd)
{
    struct device *dev = gtd->dev;
    struct device_node *np = dev->of_node;
    int i, num_gpios;
    u32 debounce;

    num_gpios = gpiod_count(dev, "trigger");
    if (num_gpios <= 0) {
        dev_err(dev, "No trigger GPIOs specified in DT\n");
        return -EINVAL;
    }
    if (num_gpios > MAX_GPIO_TRIGGERS) {
        dev_warn(dev, "Limiting GPIOs from %d to %d\n",
                 num_gpios, MAX_GPIO_TRIGGERS);
        num_gpios = MAX_GPIO_TRIGGERS;
    }

    if (of_property_read_u32(np, "debounce-ms", &debounce))
        debounce = 50;  /* 默认 50ms 去抖 */

    for (i = 0; i < num_gpios; i++) {
        struct gpio_trigger_pin *pin = &gtd->pins[i];

        pin->index = i;
        pin->parent = gtd;  /* 反向指针: 中断 handler 通过 pin->parent 找到 dev */
        pin->desc = devm_gpiod_get_index(dev, "trigger", i,
                                         GPIOD_IN);
        if (IS_ERR(pin->desc)) {
            dev_err(dev, "Failed to get trigger GPIO %d\n", i);
            return PTR_ERR(pin->desc);
        }

        pin->debounce_ms = debounce;
        pin->label = of_get_property(np, "trigger-labels", NULL);
        atomic_set(&pin->irq_count, 0);
        pin->last_irq_time = 0;
    }

    gtd->num_pins = num_gpios;
    return 0;
}

/*
 * gpio_trigger_probe — 平台设备匹配后调用
 */
static int gpio_trigger_probe(struct platform_device *pdev)
{
    struct device *dev = &pdev->dev;
    struct gpio_trigger_dev *gtd;
    int ret, i;

    gtd = devm_kzalloc(dev, sizeof(*gtd), GFP_KERNEL);
    if (!gtd)
        return -ENOMEM;

    gtd->pdev = pdev;
    gtd->dev = dev;
    platform_set_drvdata(pdev, gtd);

    /* 解析设备树 */
    ret = gpio_trigger_parse_dt(gtd);
    if (ret)
        return ret;

    /* 初始化事件队列 */
    spin_lock_init(&gtd->event_lock);
    gtd->event_head = 0;
    gtd->event_tail = 0;
    gtd->event_count = 0;
    init_waitqueue_head(&gtd->event_wait);
    atomic_set(&gtd->total_triggers, 0);

    /* 初始化 tasklet */
    tasklet_setup(&gtd->tasklet, gpio_trigger_tasklet_func);

    /* 注册 GPIO 中断 */
    for (i = 0; i < gtd->num_pins; i++) {
        struct gpio_trigger_pin *pin = &gtd->pins[i];

        pin->irq = gpiod_to_irq(pin->desc);
        if (pin->irq < 0) {
            dev_err(dev, "Failed to get IRQ for GPIO %d: %d\n",
                    i, pin->irq);
            ret = pin->irq;
            goto err_irq;
        }

        ret = devm_request_irq(dev, pin->irq,
                               gpio_trigger_irq_handler,
                               IRQF_TRIGGER_FALLING |
                               IRQF_TRIGGER_RISING |
                               IRQF_ONESHOT,
                               pin->label ?: DRIVER_NAME,
                               pin);
        if (ret) {
            dev_err(dev, "Failed to request IRQ %d: %d\n",
                    pin->irq, ret);
            goto err_irq;
        }

        dev_info(dev, "GPIO %d: IRQ %d, label '%s', debounce %dms\n",
                 i, pin->irq,
                 pin->label ?: "none",
                 pin->debounce_ms);
    }

    /* ── 创建字符设备 ── */
    ret = alloc_chrdev_region(&gtd->devt, 0, 1, DEVICE_NAME);
    if (ret) {
        dev_err(dev, "Failed to alloc chrdev: %d\n", ret);
        goto err_irq;
    }

    cdev_init(&gtd->cdev, &gpio_trigger_fops);
    gtd->cdev.owner = THIS_MODULE;

    ret = cdev_add(&gtd->cdev, gtd->devt, 1);
    if (ret) {
        dev_err(dev, "Failed to add cdev: %d\n", ret);
        goto err_chrdev;
    }

    gtd->class = class_create(THIS_MODULE, CLASS_NAME);
    if (IS_ERR(gtd->class)) {
        ret = PTR_ERR(gtd->class);
        dev_err(dev, "Failed to create class: %d\n", ret);
        goto err_cdev;
    }
    gtd->class->dev_groups = gpio_trigger_groups;

    gtd->chardev = device_create(gtd->class, dev, gtd->devt,
                                 gtd, DEVICE_NAME);
    if (IS_ERR(gtd->chardev)) {
        ret = PTR_ERR(gtd->chardev);
        dev_err(dev, "Failed to create device: %d\n", ret);
        goto err_class;
    }

    dev_info(dev, "GPIO trigger driver probed (%d pins)\n",
             gtd->num_pins);
    return 0;

err_class:
    class_destroy(gtd->class);
err_cdev:
    cdev_del(&gtd->cdev);
err_chrdev:
    unregister_chrdev_region(gtd->devt, 1);
err_irq:
    /* devm 管理的 IRQ 会自动释放 */
    tasklet_kill(&gtd->tasklet);
    return ret;
}

/*
 * gpio_trigger_remove — 平台设备移除
 */
static int gpio_trigger_remove(struct platform_device *pdev)
{
    struct gpio_trigger_dev *gtd = platform_get_drvdata(pdev);

    /* 杀死 tasklet, 确保没有待执行的中断处理 */
    tasklet_kill(&gtd->tasklet);

    device_destroy(gtd->class, gtd->devt);
    class_destroy(gtd->class);
    cdev_del(&gtd->cdev);
    unregister_chrdev_region(gtd->devt, 1);

    dev_info(&pdev->dev, "GPIO trigger driver removed\n");
    return 0;
}

/* ── 设备树匹配表 ──────────────────────────────────────── */
static const struct of_device_id gpio_trigger_of_match[] = {
    { .compatible = "edge-ai,gpio-trigger" },
    { /* sentinel */ }
};
MODULE_DEVICE_TABLE(of, gpio_trigger_of_match);

/* ── Platform 驱动结构 ─────────────────────────────────── */
static struct platform_driver gpio_trigger_driver = {
    .driver = {
        .name = DRIVER_NAME,
        .of_match_table = gpio_trigger_of_match,
        .owner = THIS_MODULE,
    },
    .probe = gpio_trigger_probe,
    .remove = gpio_trigger_remove,
};

module_platform_driver(gpio_trigger_driver);

MODULE_DESCRIPTION("GPIO Trigger Driver for Edge AI Camera");
MODULE_AUTHOR("Edge AI Vision Project");
MODULE_LICENSE("GPL");
