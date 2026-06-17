# AArch64 交叉编译工具链文件
# 用法: cmake -DCMAKE_TOOLCHAIN_FILE=cmake/aarch64-toolchain.cmake ..

set(CMAKE_SYSTEM_NAME Linux)
set(CMAKE_SYSTEM_PROCESSOR aarch64)

# 交叉编译器前缀 (根据你的 Buildroot/SDK 路径调整)
set(CROSS_PREFIX "" CACHE STRING "AArch64 cross-compiler prefix (e.g. aarch64-none-linux-gnu-)")

if(NOT CROSS_PREFIX)
    find_program(AARCH64_GCC aarch64-none-linux-gnu-gcc PATHS
        /usr/bin
        /opt/toolchains/aarch64-none-linux-gnu/bin
        /opt/buildroot/output/host/bin
        ENV PATH
    )
    find_program(AARCH64_GXX aarch64-none-linux-gnu-g++ PATHS
        /usr/bin
        /opt/toolchains/aarch64-none-linux-gnu/bin
        /opt/buildroot/output/host/bin
        ENV PATH
    )

    if(NOT AARCH64_GCC OR NOT AARCH64_GXX)
        message(WARNING "AArch64 cross-compiler not found. Set CROSS_PREFIX or install toolchain.")
        message(WARNING "  Install: sudo apt install gcc-aarch64-linux-gnu g++-aarch64-linux-gnu")
        set(CMAKE_C_COMPILER   aarch64-linux-gnu-gcc)
        set(CMAKE_CXX_COMPILER aarch64-linux-gnu-g++)
    else()
        get_filename_component(TOOL_DIR ${AARCH64_GCC} DIRECTORY)
        get_filename_component(TOOL_PREFIX ${AARCH64_GCC} NAME_WE)
        string(REGEX REPLACE "-gcc$" "-" TOOL_PREFIX ${TOOL_PREFIX})
        set(CMAKE_C_COMPILER   ${TOOL_DIR}/${TOOL_PREFIX}gcc)
        set(CMAKE_CXX_COMPILER ${TOOL_DIR}/${TOOL_PREFIX}g++)
    endif()
else()
    set(CMAKE_C_COMPILER   ${CROSS_PREFIX}gcc)
    set(CMAKE_CXX_COMPILER ${CROSS_PREFIX}g++)
endif()

# Buildroot 编译时需要 sysroot
if(DEFINED ENV{BUILDROOT_SYSROOT})
    set(CMAKE_SYSROOT $ENV{BUILDROOT_SYSROOT})
    set(CMAKE_FIND_ROOT_PATH $ENV{BUILDROOT_SYSROOT})
endif()

# 交叉编译模式
set(CMAKE_FIND_ROOT_PATH_MODE_PROGRAM NEVER)
set(CMAKE_FIND_ROOT_PATH_MODE_LIBRARY ONLY)
set(CMAKE_FIND_ROOT_PATH_MODE_INCLUDE ONLY)
set(CMAKE_FIND_ROOT_PATH_MODE_PACKAGE ONLY)

# 编译选项
set(CMAKE_C_FLAGS   "-mcpu=cortex-a72.cortex-a53 -mtune=cortex-a72.cortex-a53 -march=armv8-a+crc+simd" CACHE STRING "")
set(CMAKE_CXX_FLAGS "-mcpu=cortex-a72.cortex-a53 -mtune=cortex-a72.cortex-a53 -march=armv8-a+crc+simd" CACHE STRING "")

message(STATUS "Cross-compiling for AArch64 (RK3399Pro)")
message(STATUS "  C Compiler:   ${CMAKE_C_COMPILER}")
message(STATUS "  C++ Compiler: ${CMAKE_CXX_COMPILER}")