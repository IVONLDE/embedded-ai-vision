cmake_minimum_required(VERSION 3.10)
project(gst-rknn-plugins VERSION 1.0.0 LANGUAGES C)

# 查找 GStreamer
find_package(PkgConfig REQUIRED)
pkg_check_modules(GST REQUIRED
    gstreamer-1.0
    gstreamer-video-1.0
    gstreamer-base-1.0
)

# 查找 RKNN API
set(RKNN_INCLUDE_DIR "${CMAKE_SOURCE_DIR}/../edge/3rdparty/librknn_api/include"
    CACHE PATH "RKNN API include directory")
set(RKNN_LIB_DIR "${CMAKE_SOURCE_DIR}/../edge/3rdparty/librknn_api/aarch64"
    CACHE PATH "RKNN API library directory")

# 查找 OpenCV (用于图像预处理)
find_package(OpenCV QUIET)

include_directories(
    ${GST_INCLUDE_DIRS}
    ${RKNN_INCLUDE_DIR}
    ${OpenCV_INCLUDE_DIRS}
)

link_directories(
    ${GST_LIBRARY_DIRS}
    ${RKNN_LIB_DIR}
)

# ── rknninference 插件 ───────────────────────────────────
add_library(gstrknninference SHARED
    plugin/gstrknninference.c
)

target_link_libraries(gstrknninference
    ${GST_LIBRARIES}
    rknn_api
    ${OpenCV_LIBS}
)

target_compile_options(gstrknninference PRIVATE
    -Wall -Wextra -O2
    $<$<CONFIG:Debug>:-g -O0>
)

# ── rknndraw 插件 ────────────────────────────────────────
add_library(gstrknndraw SHARED
    plugin/gstrknndraw.c
)

target_link_libraries(gstrknndraw
    ${GST_LIBRARIES}
)

target_compile_options(gstrknndraw PRIVATE
    -Wall -Wextra -O2
    $<$<CONFIG:Debug>:-g -O0>
)

# ── 安装 ─────────────────────────────────────────────────
install(TARGETS gstrknninference gstrknndraw
    DESTINATION lib/gstreamer-1.0
)

message(STATUS "GStreamer RKNN plugins configured")
message(STATUS "  GST include: ${GST_INCLUDE_DIRS}")
message(STATUS "  RKNN include: ${RKNN_INCLUDE_DIR}")
message(STATUS "  RKNN lib:     ${RKNN_LIB_DIR}")
