/* SPDX-License-Identifier: GPL-2.0+ */
/*
 * SPI Sensor Driver — Header
 *
 * SPI 传感器字符设备驱动
 * 设备树 compatible = "edge-ai,spi-sensor"
 * 用户接口: /dev/spi_sensor (read/write/ioctl/poll)
 */

#ifndef _SPI_SENSOR_H
#define _SPI_SENSOR_H

/* ioctl 命令 (magic 'S') */
#define SPI_SENSOR_IOC_MAGIC   'S'

/* 设置 SPI 时钟频率 (Hz) */
#define SPI_SENSOR_IOC_SET_SPEED   _IOW(SPI_SENSOR_IOC_MAGIC, 1, unsigned long)
/* 设置 SPI 模式 (0/1/2/3) */
#define SPI_SENSOR_IOC_SET_MODE    _IOW(SPI_SENSOR_IOC_MAGIC, 2, int)
/* 设置字长 (8/16/32) */
#define SPI_SENSOR_IOC_SET_BITS    _IOW(SPI_SENSOR_IOC_MAGIC, 3, int)
/* 单次全双工传输: tx_buf → rx_buf */
#define SPI_SENSOR_IOC_TRANSFER    _IOWR(SPI_SENSOR_IOC_MAGIC, 4, struct spi_sensor_xfer)
/* 获取统计信息 */
#define SPI_SENSOR_IOC_GET_STATS   _IOR(SPI_SENSOR_IOC_MAGIC, 5, struct spi_sensor_stats)

/* SPI 全双工传输结构 (用于 TRANSFER ioctl) */
struct spi_sensor_xfer {
    unsigned long tx_buf;   /* 用户空间发送缓冲区指针 */
    unsigned long rx_buf;   /* 用户空间接收缓冲区指针 */
    unsigned int len;       /* 传输字节数 */
};

/* 统计信息结构 */
struct spi_sensor_stats {
    unsigned long tx_bytes;     /* 累计发送字节数 */
    unsigned long rx_bytes;     /* 累计接收字节数 */
    unsigned long errors;       /* 传输错误次数 */
    unsigned long transfers;    /* 传输总次数 */
};

/* 默认配置 */
#define DEFAULT_SPI_SPEED   1000000     /* 1MHz */
#define DEFAULT_SPI_MODE    0           /* Mode 0 (CPOL=0, CPHA=0) */
#define DEFAULT_SPI_BITS    8           /* 8-bit 字长 */

/* 单次传输最大长度 (防止 kmalloc 过大) */
#define SPI_SENSOR_MAX_XFER_LEN   4096

#endif /* _SPI_SENSOR_H */
