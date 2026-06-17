/* SPDX-License-Identifier: GPL-2.0+ */
/*
 * IMX415 V4L2 Sub-device Driver — 内部头文件
 */

#ifndef _IMX415_V4L2_H_
#define _IMX415_V4L2_H_

#include <linux/types.h>

/* IMX415 寄存器地址 */
#define IMX415_REG_MODE_SELECT      0x3000
#define IMX415_REG_STANDBY          0x3001
#define IMX415_REG_EXPOSURE_L       0x3002
#define IMX415_REG_EXPOSURE_H       0x3003
#define IMX415_REG_GAIN_L           0x3004
#define IMX415_REG_GAIN_H           0x3005
#define IMX415_REG_VMAX_L           0x3006
#define IMX415_REG_VMAX_H           0x3007
#define IMX415_REG_HMAX_L           0x3008
#define IMX415_REG_HMAX_H           0x3009
#define IMX415_REG_CHIP_ID          0x300A
#define IMX415_REG_TEST_PATTERN     0x300B
#define IMX415_REG_FLIP             0x300C

#define IMX415_CHIP_ID              0x0415

/* 默认分辨率 */
#define IMX415_DEFAULT_WIDTH        1920
#define IMX415_DEFAULT_HEIGHT       1080
#define IMX415_DEFAULT_FPS          30

#endif /* _IMX415_V4L2_H_ */
