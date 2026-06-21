cmake_minimum_required(VERSION 3.13)
project(edge-ai-camera VERSION 1.0.0 LANGUAGES CXX)

# C++17 标准
set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_POSITION_INDEPENDENT_CODE ON)
find_package(PkgConfig REQUIRED)

# 交叉编译 (AArch64)
# 用法: cmake -DCMAKE_TOOLCHAIN_FILE=../cmake/aarch64-toolchain.cmake ..
set(CMAKE_TOOLCHAIN_FILE "" CACHE FILEPATH "Cross-compilation toolchain file")

# ── 依赖查找 ──────────────────────────────────────────────

# yaml-cpp (YAML 配置解析)
find_package(yaml-cpp QUIET)
if(NOT yaml-cpp_FOUND)
    pkg_check_modules(YAMLCPP yaml-cpp)
endif()

# Eigen3 (线性代数: 卡尔曼滤波器 + 匈牙利算法)
find_package(Eigen3 QUIET)
if(NOT Eigen3_FOUND)
    pkg_check_modules(EIGEN3 eigen3)
    if(EIGEN3_FOUND)
        set(Eigen3_INCLUDE_DIRS ${EIGEN3_INCLUDE_DIRS})
    endif()
endif()

# OpenCV (图像预处理)
find_package(OpenCV QUIET COMPONENTS core imgproc videoio)
if(NOT OpenCV_FOUND)
    pkg_check_modules(OpenCV opencv4)
endif()

# libmosquitto (MQTT 客户端)
pkg_check_modules(MOSQUITTO mosquitto)

# GStreamer (视频编码 + RTSP 推流)
pkg_check_modules(GST REQUIRED gstreamer-1.0)
pkg_check_modules(GST_APP REQUIRED gstreamer-app-1.0)
pkg_check_modules(GST_RTSP REQUIRED gstreamer-rtsp-1.0)
pkg_check_modules(GST_RTSP_SERVER REQUIRED gstreamer-rtsp-server-1.0)
pkg_check_modules(GST_VIDEO REQUIRED gstreamer-video-1.0)

# systemd (systemd notify/watchdog)
pkg_check_modules(LIBSYSTEMD libsystemd)

# OpenSSL (SHA256 校验, OTA)
find_package(OpenSSL QUIET)

# gRPC + Protobuf: 优先 find_package, 降级到 pkg-config
find_package(Protobuf QUIET)
find_package(gRPC QUIET CONFIG)
if(NOT gRPC_FOUND)
    pkg_check_modules(GRPCPP QUIET grpc++)
    pkg_check_modules(PROTOBUF_PC QUIET protobuf)
    if(GRPCPP_FOUND AND PROTOBUF_PC_FOUND)
        set(gRPC_FOUND TRUE)
        set(PROTOBUF_FOUND TRUE)
        message(STATUS "gRPC found via pkg-config")
    endif()
endif()

# pthread (线程 + CPU 亲和性)
find_package(Threads REQUIRED)

# ── RKNN API (从 3rdparty 目录) ──────────────────────────
set(RKNN_INCLUDE_DIR "${CMAKE_SOURCE_DIR}/3rdparty/librknn_api/include"
    CACHE PATH "RKNN API include directory")
set(RKNN_LIB_DIR "${CMAKE_SOURCE_DIR}/3rdparty/librknn_api/aarch64"
    CACHE PATH "RKNN API library directory")

# 检查 RKNN 头文件是否存在
if(EXISTS "${RKNN_INCLUDE_DIR}/rknn_api.h")
    message(STATUS "RKNN API header found: ${RKNN_INCLUDE_DIR}/rknn_api.h")
else()
    message(WARNING "RKNN API header NOT found at ${RKNN_INCLUDE_DIR}/rknn_api.h")
    message(WARNING "  Place rknn_api.h from Rockchip SDK in edge/3rdparty/librknn_api/include/")
    message(WARNING "  Build will proceed but rknn1_engine will not compile.")
endif()

# ── Proto 文件编译 (gRPC stub 生成) ─────────────────────────
set(PROTO_DIR "${CMAKE_SOURCE_DIR}/proto")
set(PROTO_OUT_DIR "${CMAKE_SOURCE_DIR}/src/comm/generated")

if(PROTOBUF_FOUND AND gRPC_FOUND)
    message(STATUS "gRPC and Protobuf found, enabling proto compilation")

    # 确保输出目录存在
    file(MAKE_DIRECTORY ${PROTO_OUT_DIR})

    # Proto 源文件
    set(PROTO_FILES
        "${PROTO_DIR}/edge_service.proto"
        "${PROTO_DIR}/detection.proto"
    )

    # 生成的 C++ 文件
    set(PROTO_SRCS)
    set(PROTO_HDRS)
    set(GRPC_SRCS)
    set(GRPC_HDRS)

    foreach(PROTO_FILE ${PROTO_FILES})
        get_filename_component(PROTO_NAME ${PROTO_FILE} NAME_WE)

        list(APPEND PROTO_SRCS "${PROTO_OUT_DIR}/${PROTO_NAME}.pb.cc")
        list(APPEND PROTO_HDRS "${PROTO_OUT_DIR}/${PROTO_NAME}.pb.h")
        list(APPEND GRPC_SRCS "${PROTO_OUT_DIR}/${PROTO_NAME}.grpc.pb.cc")
        list(APPEND GRPC_HDRS "${PROTO_OUT_DIR}/${PROTO_NAME}.grpc.pb.h")
    endforeach()

    # 确定 protoc 和 grpc_cpp_plugin 路径
    if(Protobuf_PROTOC_EXECUTABLE)
        set(PROTOC_EXE ${Protobuf_PROTOC_EXECUTABLE})
    else()
        set(PROTOC_EXE "/usr/bin/protoc")
    endif()

    # grpc_cpp_plugin 路径
    find_program(GRPC_CPP_PLUGIN grpc_cpp_plugin PATHS /usr/bin)
    if(NOT GRPC_CPP_PLUGIN)
        message(FATAL_ERROR "grpc_cpp_plugin not found")
    endif()

    # 自定义命令: 生成 protobuf + gRPC stub
    add_custom_command(
        OUTPUT ${PROTO_SRCS} ${PROTO_HDRS} ${GRPC_SRCS} ${GRPC_HDRS}
        COMMAND ${PROTOC_EXE}
            --proto_path=${PROTO_DIR}
            --cpp_out=${PROTO_OUT_DIR}
            --grpc_out=${PROTO_OUT_DIR}
            --plugin=protoc-gen-grpc=${GRPC_CPP_PLUGIN}
            ${PROTO_FILES}
        DEPENDS ${PROTO_FILES}
        COMMENT "Generating C++ protobuf/gRPC stubs from proto files"
        VERBATIM
    )

    # 生成的源文件库
    add_library(edge-ai-proto STATIC ${PROTO_SRCS} ${GRPC_SRCS})
    target_include_directories(edge-ai-proto PUBLIC ${PROTO_OUT_DIR} ${PROTOBUF_PC_INCLUDE_DIRS})
    target_link_libraries(edge-ai-proto PUBLIC ${PROTOBUF_PC_LIBRARIES} ${GRPCPP_LIBRARIES} grpc++)

    set(PROTO_GENERATED TRUE)
else()
    message(STATUS "gRPC or Protobuf not found, proto compilation disabled")
    set(PROTO_GENERATED FALSE)
endif()

# ── 头文件路径 ────────────────────────────────────────────
include_directories(
    ${CMAKE_SOURCE_DIR}/../src
    ${RKNN_INCLUDE_DIR}
    ${EIGEN3_INCLUDE_DIRS}
    ${Eigen3_INCLUDE_DIRS}
    ${OpenCV_INCLUDE_DIRS}
    ${MOSQUITTO_INCLUDE_DIRS}
    ${YAMLCPP_INCLUDE_DIRS}
    ${LIBSYSTEMD_INCLUDE_DIRS}
    ${GST_INCLUDE_DIRS}
    ${GST_APP_INCLUDE_DIRS}
    ${GST_RTSP_INCLUDE_DIRS}
    ${GST_RTSP_SERVER_INCLUDE_DIRS}
    ${GST_VIDEO_INCLUDE_DIRS}
    ${PROTO_OUT_DIR}
)

# ── 库搜索路径 ────────────────────────────────────────────
link_directories(
    ${RKNN_LIB_DIR}
    ${MOSQUITTO_LIBRARY_DIRS}
    ${YAMLCPP_LIBRARY_DIRS}
    ${LIBSYSTEMD_LIBRARY_DIRS}
    ${GST_LIBRARY_DIRS}
    ${GST_APP_LIBRARY_DIRS}
    ${GST_RTSP_LIBRARY_DIRS}
    ${GST_RTSP_SERVER_LIBRARY_DIRS}
    ${GST_VIDEO_LIBRARY_DIRS}
)

# ── 源文件 ────────────────────────────────────────────────
set(INFERENCE_SOURCES
    src/inference/rknn1_engine.cpp
    src/inference/yolov5/decode.cpp
    src/inference/deepsort/kalman_filter.cpp
    src/inference/deepsort/hungarian.cpp
    src/inference/deepsort/tracker.cpp
)

set(IO_SOURCES
    src/io/v4l2_capture.cpp
    src/io/file_input.cpp
    src/io/video_encoder.cpp
    src/io/rtsp_server.cpp
)

set(COMM_SOURCES
    src/comm/mqtt_publisher.cpp
    src/comm/grpc_server.cpp
    src/comm/ota_manager.cpp
)

set(PIPELINE_SOURCES
    src/pipeline/pipeline_config.cpp
    src/pipeline/pipeline.cpp
)

set(MAIN_SOURCES
    src/main.cpp
)

set(ALL_SOURCES
    ${MAIN_SOURCES}
    ${PIPELINE_SOURCES}
    ${INFERENCE_SOURCES}
    ${IO_SOURCES}
    ${COMM_SOURCES}
)

# ── 可执行文件 ────────────────────────────────────────────
add_executable(edge-ai-camera ${ALL_SOURCES})

# ── 链接库 ────────────────────────────────────────────────
target_link_libraries(edge-ai-camera
    PRIVATE mosquitto yaml-cpp
    PRIVATE
    Threads::Threads
    ${OpenCV_LIBS}
    ${MOSQUITTO_LIBRARIES}
    ${YAMLCPP_LIBRARIES}
    ${LIBSYSTEMD_LIBRARIES}
    ${GST_LIBRARIES}
    ${GST_APP_LIBRARIES}
    ${GST_RTSP_LIBRARIES}
    ${GST_RTSP_SERVER_LIBRARIES}
    ${GST_VIDEO_LIBRARIES}
    OpenSSL::Crypto
)

# 可选: gRPC + Proto (编译定义 + 链接生成的 stub)
if(PROTO_GENERATED)
    target_compile_definitions(edge-ai-camera PRIVATE PROTO_GENERATED)
    target_link_libraries(edge-ai-camera PRIVATE edge-ai-proto)
endif()

# 可选: RKNN (头文件存在时尝试链接)
if(EXISTS "${RKNN_INCLUDE_DIR}/rknn_api.h")
    target_link_libraries(edge-ai-camera PRIVATE rknn_api)
endif()

# ── 编译选项 ──────────────────────────────────────────────
target_compile_options(edge-ai-camera PRIVATE
    -Wall -Wextra -Wpedantic
    -O2
    $<$<CONFIG:Debug>:-g -O0>
)

# 允许某些无害的警告 (Eigen 模板展开 / OpenCV 弃用)
target_compile_options(edge-ai-camera PRIVATE
    -Wno-deprecated-declarations
    -Wno-unused-parameter
)

# ── 安装 ──────────────────────────────────────────────────
install(TARGETS edge-ai-camera
    RUNTIME DESTINATION bin
)

install(FILES
    ../config/pipeline.yaml
    DESTINATION /opt/edge-ai/config
)

install(FILES
    ../config/edge-ai-camera.service
    DESTINATION /usr/lib/systemd/system
)

# ── 构建信息 ──────────────────────────────────────────────
message(STATUS "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
message(STATUS "Edge AI Camera — Build Configuration")
message(STATUS "  C++ Standard:  ${CMAKE_CXX_STANDARD}")
message(STATUS "  Build Type:    ${CMAKE_BUILD_TYPE}")
message(STATUS "  RKNN API:      ${RKNN_INCLUDE_DIR}")
message(STATUS "  OpenCV:        ${OpenCV_FOUND}")
message(STATUS "  Eigen3:        ${Eigen3_FOUND}")
message(STATUS "  Mosquitto:     ${MOSQUITTO_FOUND}")
message(STATUS "  yaml-cpp:      ${YAMLCPP_FOUND}")
message(STATUS "  systemd:       ${LIBSYSTEMD_FOUND}")
message(STATUS "  gRPC:          ${gRPC_FOUND}")
message(STATUS "  Proto stubs:   ${PROTO_GENERATED}")
message(STATUS "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
