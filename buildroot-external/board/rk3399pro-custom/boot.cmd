# U-Boot boot script for RK3399Pro Edge AI Camera

setenv bootargs "earlycon=uart8250,mmio32,0xff1a0000 console=ttyS2,1500000n8 root=/dev/mmcblk0p2 rootwait rw cma=512M isolcpus=4,5"

# Load kernel, device tree, and boot
fatload mmc 0:1 ${kernel_addr_r} Image
fatload mmc 0:1 ${fdt_addr_r} rk3399pro-edge-ai-camera.dtb

booti ${kernel_addr_r} - ${fdt_addr_r}