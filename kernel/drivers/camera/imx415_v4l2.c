/* SPDX-License-Identifier: GPL-2.0+ */
/*
 * IMX415 V4L2 Sub-device Driver for RK3399Pro
 *
 * Sony IMX415 1/2.8" CMOS 图像传感器驱动
 * 接口: I2C (寄存器读写) + MIPI CSI-2 4-lane
 * 输出: 1920×1080 @30fps RAW10
 *
 * 内核框架: V4L2 Sub-device (v4l2_subdev_ops)
 * I2C 通信: regmap (批量寄存器读写)
 * 设备树匹配: of_match_table
 *
 * 参考: drivers/media/i2c/imx219.c, imx290.c
 */

#include <linux/clk.h>
#include <linux/delay.h>
#include <linux/gpio/consumer.h>
#include <linux/i2c.h>
#include <linux/module.h>
#include <linux/of_device.h>
#include <linux/pm_runtime.h>
#include <linux/regmap.h>
#include <linux/regulator/consumer.h>
#include <media/v4l2-ctrls.h>
#include <media/v4l2-device.h>
#include <media/v4l2-fwnode.h>
#include <media/v4l2-subdev.h>

/* ── IMX415 寄存器地址定义 ─────────────────────────────── */
#define IMX415_REG_MODE_SELECT      0x3000  /* 工作模式选择 */
#define IMX415_REG_EXPOSURE_L       0x3002  /* 曝光时间低字节 */
#define IMX415_REG_EXPOSURE_H       0x3003  /* 曝光时间高字节 */
#define IMX415_REG_GAIN_L           0x3004  /* 模拟增益低字节 */
#define IMX415_REG_GAIN_H           0x3005  /* 模拟增益高字节 */
#define IMX415_REG_VMAX_L           0x3006  /* 垂直帧长低字节 */
#define IMX415_REG_VMAX_H           0x3007  /* 垂直帧长高字节 */
#define IMX415_REG_HMAX_L           0x3008  /* 水平帧长低字节 */
#define IMX415_REG_HMAX_H           0x3009  /* 水平帧长高字节 */
#define IMX415_REG_STANDBY          0x3001  /* 待机控制 */
#define IMX415_REG_CHIP_ID          0x300A  /* 芯片ID (只读) */
#define IMX415_REG_TEST_PATTERN     0x300B  /* 测试图案 */
#define IMX415_REG_FLIP             0x300C  /* 镜像/翻转 */

#define IMX415_CHIP_ID              0x0415  /* IMX415 芯片ID值 */

/* 默认分辨率: 1920×1080 @30fps */
#define IMX415_DEFAULT_WIDTH        1920
#define IMX415_DEFAULT_HEIGHT       1080
#define IMX415_DEFAULT_FPS          30

/* ── 驱动私有数据结构 ─────────────────────────────────── */
struct imx415 {
    struct i2c_client *client;
    struct regmap *regmap;

    struct v4l2_subdev sd;
    struct v4l2_ctrl_handler ctrl_handler;
    struct media_pad pad;

    /* V4L2 controls */
    struct v4l2_ctrl *exposure_ctrl;
    struct v4l2_ctrl *gain_ctrl;
    struct v4l2_ctrl *test_pattern_ctrl;
    struct v4l2_ctrl *hflip_ctrl;
    struct v4l2_ctrl *vflip_ctrl;

    /* 硬件资源 */
    struct clk *xvclk;
    struct gpio_desc *reset_gpio;
    struct gpio_desc *powerdown_gpio;
    struct regulator *vcc_supply;
    struct regulator *vcc_1v2_supply;

    /* 当前配置 */
    struct v4l2_mbus_framefmt fmt;
    int fps;
    bool streaming;
};

/* ── 寄存器读写辅助函数 ───────────────────────────────── */
static inline struct imx415 *to_imx415(struct v4l2_subdev *sd)
{
    return container_of(sd, struct imx415, sd);
}

/* regmap 配置: I2C 16-bit 寄存器地址, 8-bit 数据 */
static const struct regmap_config imx415_regmap_config = {
    .reg_bits = 16,
    .val_bits = 8,
    .max_register = 0x3FFF,
    .cache_type = REGCACHE_NONE,
};

/*
 * imx415_write_reg — 写单个寄存器
 * @imx415: 驱动实例
 * @reg:    16-bit 寄存器地址
 * @val:    8-bit 值
 */
static int imx415_write_reg(struct imx415 *imx415, u16 reg, u8 val)
{
    int ret;

    ret = regmap_write(imx415->regmap, reg, val);
    if (ret)
        dev_err(&imx415->client->dev,
                "Failed to write reg 0x%04x: %d\n", reg, ret);
    return ret;
}

/*
 * imx415_read_reg — 读单个寄存器
 */
static int imx415_read_reg(struct imx415 *imx415, u16 reg, u8 *val)
{
    int ret;
    unsigned int tmp;

    ret = regmap_read(imx415->regmap, reg, &tmp);
    if (ret) {
        dev_err(&imx415->client->dev,
                "Failed to read reg 0x%04x: %d\n", reg, ret);
        return ret;
    }
    *val = (u8)tmp;
    return 0;
}

/*
 * imx415_write_array — 批量写寄存器表
 * @regs: 寄存器表 (以 {0xFFFF, 0xFF} 结束)
 *
 * 用于初始化时写入大量配置寄存器
 */
static int imx415_write_array(struct imx415 *imx415,
                              const struct reg_sequence *regs, int num)
{
    int ret;

    ret = regmap_multi_reg_write(imx415->regmap, regs, num);
    if (ret)
        dev_err(&imx415->client->dev,
                "Failed to write register array: %d\n", ret);
    return ret;
}

/* ── 硬件上电/下电时序 ────────────────────────────────── */
/*
 * imx415_power_on — 摄像头传感器上电
 *
 * 时序要求 (IMX415 datasheet):
 *   1. VCC 2.8V 上电
 *   2. VCC 1.2V 上电
 *   3. 外部时钟 24MHz 启动
 *   4. RESET 拉高 (释放复位)
 *   5. PWDN 拉低 (退出省电)
 *   6. 等待 10ms 稳定
 */
static int imx415_power_on(struct imx415 *imx415)
{
    int ret;

    ret = regulator_enable(imx415->vcc_supply);
    if (ret) {
        dev_err(&imx415->client->dev,
                "Failed to enable VCC: %d\n", ret);
        return ret;
    }
    usleep_range(1000, 2000);

    ret = regulator_enable(imx415->vcc_1v2_supply);
    if (ret) {
        dev_err(&imx415->client->dev,
                "Failed to enable VCC_1V2: %d\n", ret);
        regulator_disable(imx415->vcc_supply);
        return ret;
    }
    usleep_range(1000, 2000);

    ret = clk_prepare_enable(imx415->xvclk);
    if (ret) {
        dev_err(&imx415->client->dev,
                "Failed to enable clock: %d\n", ret);
        goto err_clk;
    }
    usleep_range(1000, 2000);

    /* 释放复位 */
    gpiod_set_value_cansleep(imx415->reset_gpio, 1);
    usleep_range(1000, 2000);

    /* 退出省电模式 */
    gpiod_set_value_cansleep(imx415->powerdown_gpio, 0);
    usleep_range(10000, 12000);  /* 等待传感器稳定 */

    return 0;

err_clk:
    regulator_disable(imx415->vcc_1v2_supply);
    regulator_disable(imx415->vcc_supply);
    return ret;
}

/*
 * imx415_power_off — 摄像头传感器下电
 */
static void imx415_power_off(struct imx415 *imx415)
{
    gpiod_set_value_cansleep(imx415->powerdown_gpio, 1);
    usleep_range(1000, 2000);

    gpiod_set_value_cansleep(imx415->reset_gpio, 0);
    usleep_range(1000, 2000);

    clk_disable_unprepare(imx415->xvclk);

    regulator_disable(imx415->vcc_1v2_supply);
    regulator_disable(imx415->vcc_supply);
}

/* ── IMX415 初始化寄存器序列 ──────────────────────────── */
/*
 * IMX415 上电后需要写入一系列寄存器来配置:
 *   - 工作模式 (1920×1080, 30fps, RAW10)
 *   - MIPI 输出格式 (4-lane, 连续时钟)
 *   - 曝光/增益默认值
 *   - 时钟分频
 *
 * 注: 以下寄存器序列基于 IMX415 datasheet 的推荐配置,
 *     实际使用时需根据硬件调试调整。
 */
static const struct reg_sequence imx415_init_regs[] = {
    /* 软件复位 */
    {0x3000, 0x01},
    /* 等待复位完成 */
    /* 工作模式: 1920×1080, 全像素扫描 */
    {0x3000, 0x00},
    {0x3001, 0x00},  /* 退出待机 */

    /* MIPI 配置: 4-lane, RAW10, 连续时钟 */
    {0x3100, 0x04},  /* 4-lane */
    {0x3101, 0x0A},  /* RAW10 */

    /* 帧率配置: 30fps */
    {0x3006, 0x38},  /* VMAX L */
    {0x3007, 0x04},  /* VMAX H */
    {0x3008, 0x80},  /* HMAX L */
    {0x3009, 0x07},  /* HMAX H */

    /* 默认曝光: 10ms */
    {0x3002, 0x10},
    {0x3003, 0x00},

    /* 默认增益: 1x (0dB) */
    {0x3004, 0x00},
    {0x3005, 0x00},

    /* 不翻转/不镜像 */
    {0x300C, 0x00},

    /* 关闭测试图案 */
    {0x300B, 0x00},

    /* 序列结束标记 */
};

/* ── V4L2 Sub-device 核心操作 ──────────────────────────── */

/*
 * imx415_s_stream — 启动/停止视频流
 * @enable: 1=开始采集, 0=停止
 *
 * 这是 V4L2 框架调用最频繁的函数之一。
 * 启动时: 写入初始化寄存器 → 退出待机
 * 停止时: 进入待机
 */
static int imx415_s_stream(struct v4l2_subdev *sd, int enable)
{
    struct imx415 *imx415 = to_imx415(sd);
    int ret;

    if (imx415->streaming == enable)
        return 0;

    if (enable) {
        /* 上电 + 初始化寄存器 */
        ret = imx415_power_on(imx415);
        if (ret)
            return ret;

        ret = imx415_write_array(imx415, imx415_init_regs,
                                 ARRAY_SIZE(imx415_init_regs));
        if (ret) {
            imx415_power_off(imx415);
            return ret;
        }

        /* 退出待机, 开始输出图像 */
        ret = imx415_write_reg(imx415, IMX415_REG_STANDBY, 0x00);
        if (ret) {
            imx415_power_off(imx415);
            return ret;
        }

        dev_info(&imx415->client->dev, "Stream started\n");
    } else {
        /* 进入待机 */
        imx415_write_reg(imx415, IMX415_REG_STANDBY, 0x01);
        imx415_power_off(imx415);
        dev_info(&imx415->client->dev, "Stream stopped\n");
    }

    imx415->streaming = enable;
    return 0;
}

/*
 * imx415_get_fmt — 获取当前格式
 */
static int imx415_get_fmt(struct v4l2_subdev *sd,
                          struct v4l2_subdev_state *state,
                          struct v4l2_subdev_format *format)
{
    struct imx415 *imx415 = to_imx415(sd);

    if (format->which == V4L2_SUBDEV_FORMAT_TRY)
        return v4l2_subdev_get_try_format(sd, state, format->pad);

    format->format = imx415->fmt;
    return 0;
}

/*
 * imx415_set_fmt — 设置输出格式
 *
 * IMX415 只支持 RAW10 格式, 分辨率固定 1920×1080
 * 不支持缩放/裁剪
 */
static int imx415_set_fmt(struct v4l2_subdev *sd,
                          struct v4l2_subdev_state *state,
                          struct v4l2_subdev_format *format)
{
    struct imx415 *imx415 = to_imx415(sd);
    struct v4l2_mbus_framefmt *fmt = &format->format;

    /* 只支持固定格式 */
    fmt->code = MEDIA_BUS_FMT_SRGGB10_1X10;
    fmt->width = IMX415_DEFAULT_WIDTH;
    fmt->height = IMX415_DEFAULT_HEIGHT;
    fmt->field = V4L2_FIELD_NONE;
    fmt->colorspace = V4L2_COLORSPACE_RAW;

    if (format->which == V4L2_SUBDEV_FORMAT_TRY) {
        *v4l2_subdev_get_try_format(sd, state, format->pad) = *fmt;
        return 0;
    }

    imx415->fmt = *fmt;
    return 0;
}

/*
 * imx415_enum_mbus_code — 枚举支持的 media bus 格式
 */
static int imx415_enum_mbus_code(struct v4l2_subdev *sd,
                                 struct v4l2_subdev_state *state,
                                 struct v4l2_subdev_mbus_code_enum *code)
{
    if (code->index > 0)
        return -EINVAL;

    code->code = MEDIA_BUS_FMT_SRGGB10_1X10;
    return 0;
}

/*
 * imx415_enum_frame_size — 枚举支持的分辨率
 */
static int imx415_enum_frame_size(struct v4l2_subdev *sd,
                                  struct v4l2_subdev_state *state,
                                  struct v4l2_subdev_frame_size_enum *fse)
{
    if (fse->index > 0)
        return -EINVAL;

    fse->min_width = IMX415_DEFAULT_WIDTH;
    fse->max_width = IMX415_DEFAULT_WIDTH;
    fse->min_height = IMX415_DEFAULT_HEIGHT;
    fse->max_height = IMX415_DEFAULT_HEIGHT;

    return 0;
}

/* ── V4L2 Control 操作 ─────────────────────────────────── */
/*
 * imx415_s_ctrl — 设置 V4L2 control
 *
 * 支持的 controls:
 *   - V4L2_CID_EXPOSURE: 曝光时间 (行数)
 *   - V4L2_CID_GAIN:     模拟增益
 *   - V4L2_CID_TEST_PATTERN: 测试图案
 *   - V4L2_CID_HFLIP/VFLIP: 水平/垂直翻转
 */
static int imx415_s_ctrl(struct v4l2_ctrl *ctrl)
{
    struct imx415 *imx415 =
        container_of(ctrl->handler, struct imx415, ctrl_handler);
    int ret = 0;

    switch (ctrl->id) {
    case V4L2_CID_EXPOSURE:
        ret = imx415_write_reg(imx415, IMX415_REG_EXPOSURE_L,
                               ctrl->val & 0xFF);
        if (!ret)
            ret = imx415_write_reg(imx415, IMX415_REG_EXPOSURE_H,
                                   (ctrl->val >> 8) & 0xFF);
        break;

    case V4L2_CID_GAIN:
        ret = imx415_write_reg(imx415, IMX415_REG_GAIN_L,
                               ctrl->val & 0xFF);
        if (!ret)
            ret = imx415_write_reg(imx415, IMX415_REG_GAIN_H,
                                   (ctrl->val >> 8) & 0xFF);
        break;

    case V4L2_CID_TEST_PATTERN:
        ret = imx415_write_reg(imx415, IMX415_REG_TEST_PATTERN,
                               ctrl->val);
        break;

    case V4L2_CID_HFLIP:
    case V4L2_CID_VFLIP: {
        u8 flip_val = 0;
        if (imx415->hflip_ctrl->val)
            flip_val |= 0x01;
        if (imx415->vflip_ctrl->val)
            flip_val |= 0x02;
        ret = imx415_write_reg(imx415, IMX415_REG_FLIP, flip_val);
        break;
    }

    default:
        ret = -EINVAL;
        break;
    }

    return ret;
}

static const struct v4l2_ctrl_ops imx415_ctrl_ops = {
    .s_ctrl = imx415_s_ctrl,
};

/* ── V4L2 Sub-device 操作表 ─────────────────────────────── */
static const struct v4l2_subdev_core_ops imx415_core_ops = {
    .subscribe_event = v4l2_ctrl_subdev_subscribe_event,
    .unsubscribe_event = v4l2_event_subdev_unsubscribe,
};

static const struct v4l2_subdev_video_ops imx415_video_ops = {
    .s_stream = imx415_s_stream,
};

static const struct v4l2_subdev_pad_ops imx415_pad_ops = {
    .get_fmt = imx415_get_fmt,
    .set_fmt = imx415_set_fmt,
    .enum_mbus_code = imx415_enum_mbus_code,
    .enum_frame_size = imx415_enum_frame_size,
};

static const struct v4l2_subdev_ops imx415_subdev_ops = {
    .core = &imx415_core_ops,
    .video = &imx415_video_ops,
    .pad = &imx415_pad_ops,
};

/* ── I2C 驱动 probe/remove ──────────────────────────────── */

/*
 * imx415_identify — 读取芯片ID验证硬件
 *
 * 通过 I2C 读取 CHIP_ID 寄存器 (0x300A),
 * 验证是否为 IMX415 (0x0415)
 */
static int imx415_identify(struct imx415 *imx415)
{
    u8 chip_id_h, chip_id_l;
    u16 chip_id;
    int ret;

    ret = imx415_read_reg(imx415, IMX415_REG_CHIP_ID, &chip_id_h);
    if (ret)
        return ret;

    ret = imx415_read_reg(imx415, IMX415_REG_CHIP_ID + 1, &chip_id_l);
    if (ret)
        return ret;

    chip_id = (chip_id_h << 8) | chip_id_l;

    if (chip_id != IMX415_CHIP_ID) {
        dev_err(&imx415->client->dev,
                "Unexpected chip ID 0x%04x, expected 0x%04x\n",
                chip_id, IMX415_CHIP_ID);
        return -ENODEV;
    }

    dev_info(&imx415->client->dev, "IMX415 identified (ID: 0x%04x)\n",
             chip_id);
    return 0;
}

/*
 * imx415_probe — I2C 设备匹配后调用
 *
 * 流程:
 *   1. 获取硬件资源 (regulator, clock, gpio)
 *   2. 初始化 regmap (I2C 寄存器访问)
 *   3. 上电 → 读芯片ID → 下电
 *   4. 注册 V4L2 sub-device
 *   5. 创建 V4L2 controls
 *   6. 注册 media pad
 */
static int imx415_probe(struct i2c_client *client)
{
    struct device *dev = &client->dev;
    struct imx415 *imx415;
    int ret;

    imx415 = devm_kzalloc(dev, sizeof(*imx415), GFP_KERNEL);
    if (!imx415)
        return -ENOMEM;

    imx415->client = client;

    /* ── 获取硬件资源 ── */
    imx415->vcc_supply = devm_regulator_get(dev, "vcc");
    if (IS_ERR(imx415->vcc_supply)) {
        dev_err(dev, "Failed to get VCC regulator\n");
        return PTR_ERR(imx415->vcc_supply);
    }

    imx415->vcc_1v2_supply = devm_regulator_get(dev, "vcc-1v2");
    if (IS_ERR(imx415->vcc_1v2_supply)) {
        dev_err(dev, "Failed to get VCC_1V2 regulator\n");
        return PTR_ERR(imx415->vcc_1v2_supply);
    }

    imx415->xvclk = devm_clk_get(dev, "xvclk");
    if (IS_ERR(imx415->xvclk)) {
        dev_err(dev, "Failed to get xvclk\n");
        return PTR_ERR(imx415->xvclk);
    }

    /* 设置时钟频率 24MHz */
    ret = clk_set_rate(imx415->xvclk, 24000000);
    if (ret) {
        dev_err(dev, "Failed to set clock rate: %d\n", ret);
        return ret;
    }

    imx415->reset_gpio = devm_gpiod_get(dev, "reset", GPIOD_OUT_LOW);
    if (IS_ERR(imx415->reset_gpio)) {
        dev_err(dev, "Failed to get reset GPIO\n");
        return PTR_ERR(imx415->reset_gpio);
    }

    imx415->powerdown_gpio = devm_gpiod_get(dev, "powerdown",
                                            GPIOD_OUT_HIGH);
    if (IS_ERR(imx415->powerdown_gpio)) {
        dev_err(dev, "Failed to get powerdown GPIO\n");
        return PTR_ERR(imx415->powerdown_gpio);
    }

    /* ── 初始化 regmap ── */
    imx415->regmap = devm_regmap_init_i2c(client, &imx415_regmap_config);
    if (IS_ERR(imx415->regmap)) {
        dev_err(dev, "Failed to init regmap\n");
        return PTR_ERR(imx415->regmap);
    }

    /* ── 上电验证芯片 ── */
    ret = imx415_power_on(imx415);
    if (ret)
        return ret;

    ret = imx415_identify(imx415);
    imx415_power_off(imx415);

    if (ret)
        return ret;

    /* ── 初始化 V4L2 sub-device ── */
    v4l2_i2c_subdev_init(&imx415->sd, client, &imx415_subdev_ops);
    imx415->sd.flags |= V4L2_SUBDEV_FL_HAS_DEVNODE;
    imx415->sd.dev = dev;

    /* 设置默认格式 */
    imx415->fmt.code = MEDIA_BUS_FMT_SRGGB10_1X10;
    imx415->fmt.width = IMX415_DEFAULT_WIDTH;
    imx415->fmt.height = IMX415_DEFAULT_HEIGHT;
    imx415->fmt.field = V4L2_FIELD_NONE;
    imx415->fmt.colorspace = V4L2_COLORSPACE_RAW;

    /* ── 创建 V4L2 controls ── */
    v4l2_ctrl_handler_init(&imx415->ctrl_handler, 5);

    imx415->exposure_ctrl = v4l2_ctrl_new_std(
        &imx415->ctrl_handler, &imx415_ctrl_ops,
        V4L2_CID_EXPOSURE, 1, 65535, 1, 1000);

    imx415->gain_ctrl = v4l2_ctrl_new_std(
        &imx415->ctrl_handler, &imx415_ctrl_ops,
        V4L2_CID_GAIN, 0, 240, 1, 0);  /* 0~24dB, step 0.1dB */

    imx415->test_pattern_ctrl = v4l2_ctrl_new_std_menu_items(
        &imx415->ctrl_handler, &imx415_ctrl_ops,
        V4L2_CID_TEST_PATTERN,
        ARRAY_SIZE(v4l2_ctrl_test_pattern_menu) - 1,
        0, 0, v4l2_ctrl_test_pattern_menu);

    imx415->hflip_ctrl = v4l2_ctrl_new_std(
        &imx415->ctrl_handler, &imx415_ctrl_ops,
        V4L2_CID_HFLIP, 0, 1, 1, 0);

    imx415->vflip_ctrl = v4l2_ctrl_new_std(
        &imx415->ctrl_handler, &imx415_ctrl_ops,
        V4L2_CID_VFLIP, 0, 1, 1, 0);

    if (imx415->ctrl_handler.error) {
        ret = imx415->ctrl_handler.error;
        dev_err(dev, "Failed to init controls: %d\n", ret);
        goto err_ctrl;
    }

    imx415->sd.ctrl_handler = &imx415->ctrl_handler;

    /* ── 注册 media pad ── */
    imx415->pad.flags = MEDIA_PAD_FL_SOURCE;
    ret = media_entity_pads_init(&imx415->sd.entity, 1, &imx415->pad);
    if (ret) {
        dev_err(dev, "Failed to init media pads: %d\n", ret);
        goto err_media;
    }

    /* ── 注册 sub-device ── */
    ret = v4l2_async_register_subdev(&imx415->sd);
    if (ret) {
        dev_err(dev, "Failed to register subdev: %d\n", ret);
        goto err_subdev;
    }

    dev_info(dev, "IMX415 driver probed successfully\n");
    return 0;

err_subdev:
    media_entity_cleanup(&imx415->sd.entity);
err_media:
err_ctrl:
    v4l2_ctrl_handler_free(&imx415->ctrl_handler);
    return ret;
}

/*
 * imx415_remove — I2C 设备移除
 *
 * 逆序释放资源:
 *   1. 注销 sub-device
 *   2. 清理 media entity
 *   3. 释放 controls
 *   4. 确保下电
 */
static void imx415_remove(struct i2c_client *client)
{
    struct v4l2_subdev *sd = i2c_get_clientdata(client);
    struct imx415 *imx415 = to_imx415(sd);

    v4l2_async_unregister_subdev(sd);
    media_entity_cleanup(&sd->entity);
    v4l2_ctrl_handler_free(&imx415->ctrl_handler);

    /* 确保传感器下电 */
    if (imx415->streaming)
        imx415_power_off(imx415);

    dev_info(&client->dev, "IMX415 driver removed\n");
}

/* ── 设备树匹配表 ──────────────────────────────────────── */
static const struct of_device_id imx415_of_match[] = {
    { .compatible = "sony,imx415" },
    { /* sentinel */ }
};
MODULE_DEVICE_TABLE(of, imx415_of_match);

/* ── I2C 驱动结构 ──────────────────────────────────────── */
static struct i2c_driver imx415_i2c_driver = {
    .driver = {
        .name = "imx415",
        .of_match_table = imx415_of_match,
        .owner = THIS_MODULE,
    },
    .probe_new = imx415_probe,
    .remove = imx415_remove,
};

module_i2c_driver(imx415_i2c_driver);

MODULE_DESCRIPTION("Sony IMX415 V4L2 Camera Sensor Driver");
MODULE_AUTHOR("Edge AI Vision Project");
MODULE_LICENSE("GPL");
