#! /bin/bash
# Optimized toybrick-server.sh - 启动时间优化版
# 优化项:
#   1. 移除无用的 resize2fs (分区已扩展完毕)
#   2. 移除无用的 chmod galcore (设备不存在)
#   3. 并行化 chmodrkdev/alsaconf
#   4. rkisp_3A_server 放后台不阻塞

function get_board_model()
{
        if [ ! -f /boot/toybrick-release ]; then
                echo TB-UNKNOWN
        else
                model=$(cat /boot/toybrick-release | grep Model | awk '{print $2}')
                echo ${model}
        fi
}

function get_cpu_model()
{
        case $1 in
        TB-RK3399Pro* | TB-96AI | EAIDK-610)
                echo RK3399
                ;;
        TB-RK1808* | TB-96AIOT)
                echo RK1808
                ;;
        *)
                echo Unkown
                ;;
        esac
}

function chmodrkdev()
{
        # 忽略不存在的设备
        chmod 0666 /dev/rkvdec 2>/dev/null
        chmod 0666 /dev/vpu_service 2>/dev/null
        chmod 0666 /dev/mali0 2>/dev/null
        chmod 0666 /dev/rga 2>/dev/null
        chmod 0666 /dev/dri/card0 2>/dev/null
        chmod 0666 /dev/ttyS0 2>/dev/null
        chmod 0666 /dev/ttyS4 2>/dev/null
        chmod 0644 /dev/vendor_storage 2>/dev/null
}

function alsaconf()
{
        case $1 in
        TB-RK3399ProD* | TB-RK3399ProP* | TB-RK3399ProX* | TB-96AI)
                cp /usr/share/alsa/alsa-rk809.conf /usr/share/alsa/alsa.conf
                ;;
        EAIDK610)
                rt5651.sh
                cp /usr/share/alsa/alsa-rt5651.conf /usr/share/alsa/alsa.conf
                ;;
        EAIDK310)
                cp /usr/share/alsa/alsa-rk3328.conf /usr/share/alsa/alsa.conf
                ;;
        *)
                ;;
        esac
}

function iptables_stick()
{
        IPTABLES=iptables-legacy
        case $1 in
        TB-RK3399ProD* | TB-RK3399ProP* | TB-RK3399ProX*)
                sysctl -w net.ipv4.ip_forward=1
                ${IPTABLES} -F
                ${IPTABLES} -t nat -F
                ${IPTABLES} -t nat -A POSTROUTING -o eth0 -j MASQUERADE
                ;;
        *)
                ;;
        esac
}

function toybrickd_start()
{
        toybrickd start -lb $1
}

function toybrickd_stop()
{
        toybrickd stop -b $1
}

case "$1" in
start)
        board=$(get_board_model)

        # 并行化初始化 (不阻塞主流程)
        chmodrkdev &
        alsaconf ${board} &
        iptables_stick ${board} &

        # 启动主服务 (adb + NPU)
        toybrickd_start ${board}
        ret=$?

        if [ $ret -eq 0 ]; then
                led_ctrl.sh ${board} on
        else
                led_ctrl.sh ${board} off
        fi

        # rkisp 3A 服务后台启动 (不阻塞)
        rkisp_3A_server --mmedia /dev/media0 >/dev/null 2>&1 &
        rkisp_3A_server --mmedia /dev/media1 >/dev/null 2>&1 &

        # 用户自定义脚本
        if [ -f /usr/local/bin/tb.local.after ]; then
                /usr/local/bin/tb.local.after
        fi
        if [ -d /var/factoryTest ]; then
                /var/factoryTest/autorun.sh ${board}
        fi
        if [ -f /home/toybrick/.autorun.sh ]; then
                sudo -u toybrick /home/toybrick/.autorun.sh ${board} &
        fi
        ;;
stop)
        board=$(get_board_model)
        toybrickd_stop ${board}
        led_ctrl.sh ${board} off
        ;;
off)
        board=$(get_board_model)
        toybrickd_stop ${board}
        led_ctrl.sh ${board} off
        ;;
*)
        ;;
esac
