# Third-Party Libraries for RK3399Pro Edge AI

此目录包含从 Rockchip SDK 提取的第三方库，用于 RK3399Pro 平台的交叉编译。

## 目录结构

```
3rdparty/
├── librknn_api/          # RKNN1 NPU 推理运行时库
│   ├── include/
│   │   └── rknn_api.h    # RKNN1 C API 头文件 (已提供)
│   └── aarch64/
│       └── librknn_api.so # RKNN1 动态库 (需手动获取)
└── rga/                   # Rockchip Graphics Acceleration (RGA)
    ├── include/
    │   ├── rga.h          # RGA API 头文件 (需手动获取)
    │   └── RockchipRga.h  # RGA C++ 封装 (需手动获取)
    └── lib/
        └── librga.so      # RGA 动态库 (需手动获取)
```

## 获取方式

### 1. librknn_api.so (必需)

RKNN1 推理运行时库，边缘端推理的核心依赖。此库提供 `rknn_init`、`rknn_run`、`rknn_outputs_get` 等 API。

**获取方式 A: 从 Toybrick RK3399Pro 开发板提取**
```bash
# 在 Toybrick 开发板上
scp root@<toybrick-ip>:/usr/lib/librknn_api.so edge/3rdparty/librknn_api/aarch64/
```

**获取方式 B: 从 RKNN-Toolkit1 Python 包提取**
```bash
# 在 x86 PC 上安装 RKNN-Toolkit1 (需 Linux)
pip install rknn-toolkit==1.7.3
find / -name "librknn_api.so" 2>/dev/null | grep aarch64
cp <找到的路径>/librknn_api.so edge/3rdparty/librknn_api/aarch64/
```

**获取方式 C: 从 Rockchip GitHub 编译**
```bash
git clone https://github.com/rockchip-linux/rknn-toolkit.git
cd rknn-toolkit/rknn-runtime
# 使用 aarch64 交叉编译工具链
mkdir build && cd build
cmake .. -DCMAKE_TOOLCHAIN_FILE=<path-to-aarch64-toolchain>.cmake
make
```

### 2. librga.so (可选)

RGA (Rockchip Graphics Acceleration) 硬件加速库，用于图像缩放/裁剪/颜色转换/旋转。
RK3399Pro 的 RGA 可以卸载 CPU 的图像预处理工作，降低 NPU 推理延迟。

**获取方式:**
```bash
# 从 Toybrick 开发板提取
scp root@<toybrick-ip>:/usr/lib/librga.so edge/3rdparty/rga/lib/
scp root@<toybrick-ip>:/usr/include/rga/rga.h edge/3rdparty/rga/include/
scp root@<toybrick-ip>:/usr/include/rga/RockchipRga.h edge/3rdparty/rga/include/
```

**RGA 硬件能力 (RK3399Pro):**
| 功能 | 支持格式 |
|------|---------|
| 缩放 | 1/16 ~ 16x, 双线性 |
| 裁剪 | 任意矩形 |
| 旋转 | 0°/90°/180°/270°, 镜像 |
| 颜色转换 | RGB→YUV, YUV→RGB, NV12→RGB |
| 混合 | Alpha blending (2 layers) |

**注意:** 当前边缘端代码不使用 RGA 加速，图像预处理在 CPU 上用 OpenCV 完成。
RGA 集成是未来优化方向。

### 3. rknn_api.h (已提供)

此头文件是 Rockchip RKNN-Toolkit1 SDK 中 `rknn_api.h` 的复制版本。
包含了完整的 RKNN1 C API 声明，用于在 x86 PC 上做语法检查和静态分析。
真实交叉编译时也可直接使用此头文件。
