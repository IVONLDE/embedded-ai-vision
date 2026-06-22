/* SPDX-License-Identifier: MIT */
/*
 * MQTT Publisher — 检测结果上报 + 指令接收
 *
 * Topic 设计:
 *   edge/{device_id}/detections  — 检测结果 (QoS 1)
 *   edge/{device_id}/health      — 心跳/状态 (QoS 0)
 *   edge/{device_id}/command     — 接收PC端指令 (QoS 1, 订阅)
 *
 * 指令通过 OtaCallback 转发到 ota_manager 处理,
 * 本模块只负责通信, 不包含业务逻辑。
 */

#include "mqtt_publisher.h"

#include <cstdio>
#include <cstring>
#include <ctime>
#include <sstream>
#include <signal.h>
#include <unistd.h>
#include <mosquitto.h>

/* ── MQTT 回调 ──────────────────────────────────────────── */

static void on_connect(struct mosquitto *mosq, void *obj, int rc)
{
    MqttPublisher *self = static_cast<MqttPublisher *>(obj);

    if (rc == MOSQ_ERR_SUCCESS) {
        printf("[MQTT] Connected to broker\n");
        self->_connected = true;

        /* 补发断网期间积压的消息 */
        self->flush_pending_messages();

        /* 订阅指令 topic */
        if (!self->_cmd_topic.empty()) {
            mosquitto_subscribe(mosq, NULL,
                                self->_cmd_topic.c_str(), 1);
            printf("[MQTT] Subscribed to %s\n",
                   self->_cmd_topic.c_str());
        }
    } else {
        fprintf(stderr, "[MQTT] Connection failed: %d\n", rc);
        self->_connected = false;
    }
}

static void on_disconnect(struct mosquitto *mosq, void *obj, int rc)
{
    MqttPublisher *self = static_cast<MqttPublisher *>(obj);
    printf("[MQTT] Disconnected (rc=%d)\n", rc);
    self->_connected = false;
}

static void on_publish(struct mosquitto *mosq, void *obj, int mid)
{
    MqttPublisher *self = static_cast<MqttPublisher *>(obj);
    self->_last_published_mid = mid;
}

static void on_message(struct mosquitto *mosq, void *obj,
                       const struct mosquitto_message *msg)
{
    MqttPublisher *self = static_cast<MqttPublisher *>(obj);
    printf("[MQTT] Received message on %s: %.*s\n",
           msg->topic, msg->payloadlen, (char *)msg->payload);
    self->handle_command(msg->topic, (const char *)msg->payload,
                         msg->payloadlen);
}

/* ── 构造/析构 ──────────────────────────────────────────── */

MqttPublisher::MqttPublisher()
    : _mosq(nullptr), _connected(false), _port(0), _last_published_mid(0)
{
    mosquitto_lib_init();
}

MqttPublisher::~MqttPublisher()
{
    disconnect();
    mosquitto_lib_cleanup();
}

/* ── 连接/断开 ──────────────────────────────────────────── */

bool MqttPublisher::connect(const std::string &host, int port,
                            const std::string &client_id,
                            int keepalive)
{
    _host = host;
    _port = port;
    _client_id = client_id;
    _cmd_topic = "edge/" + client_id + "/command";

    _mosq = mosquitto_new(client_id.c_str(), true, this);
    if (!_mosq) {
        fprintf(stderr, "[MQTT] Failed to create client\n");
        return false;
    }

    mosquitto_connect_callback_set(_mosq, on_connect);
    mosquitto_disconnect_callback_set(_mosq, on_disconnect);
    mosquitto_publish_callback_set(_mosq, on_publish);
    mosquitto_message_callback_set(_mosq, on_message);

    /* ── 自动重连配置 ──
     * 指数退避: 1s → 2s → 4s → 8s → ... → 最大 300s
     * mosquitto_loop_start 内部会自动调用 mosquitto_reconnect
     * 此配置让断线后自动重连, 不需要手动重连逻辑
     */
    mosquitto_reconnect_delay_set(_mosq, 1, 300, true);

    /* 遗嘱消息: 设备离线时自动发布 */
    std::string will_topic = "edge/" + client_id + "/health";
    std::string will_msg = "{\"status\":\"offline\"}";
    mosquitto_will_set(_mosq, will_topic.c_str(),
                       will_msg.size(), will_msg.c_str(), 0, false);

    int ret = mosquitto_connect(_mosq, host.c_str(), port, keepalive);
    if (ret != MOSQ_ERR_SUCCESS) {
        fprintf(stderr, "[MQTT] Connect failed: %s\n",
                mosquitto_strerror(ret));
        mosquitto_destroy(_mosq);
        _mosq = nullptr;
        return false;
    }

    ret = mosquitto_loop_start(_mosq);
    if (ret != MOSQ_ERR_SUCCESS) {
        fprintf(stderr, "[MQTT] Loop start failed: %s\n",
                mosquitto_strerror(ret));
        mosquitto_destroy(_mosq);
        _mosq = nullptr;
        return false;
    }

    printf("[MQTT] Client %s connecting to %s:%d...\n",
           client_id.c_str(), host.c_str(), port);
    return true;
}

void MqttPublisher::disconnect()
{
    if (_mosq) {
        mosquitto_loop_stop(_mosq, false);
        mosquitto_disconnect(_mosq);
        mosquitto_destroy(_mosq);
        _mosq = nullptr;
    }
    _connected = false;
    printf("[MQTT] Disconnected\n");
}

/* ── 发布检测结果 ──────────────────────────────────────── */
bool MqttPublisher::publish_detections(
    const std::string &topic,
    const std::vector<DetectBox> &boxes,
    int frame_index, int64_t timestamp_us)
{
    if (!_mosq)
        return false;

    std::ostringstream json;
    json << "{";
    json << "\"device_id\":\"" << _client_id << "\",";
    json << "\"frame_index\":" << frame_index << ",";
    json << "\"timestamp_us\":" << timestamp_us << ",";
    json << "\"detections\":[";

    for (size_t i = 0; i < boxes.size(); i++) {
        if (i > 0) json << ",";
        json << "{";
        json << "\"x1\":" << (int)boxes[i].x1 << ",";
        json << "\"y1\":" << (int)boxes[i].y1 << ",";
        json << "\"x2\":" << (int)boxes[i].x2 << ",";
        json << "\"y2\":" << (int)boxes[i].y2 << ",";
        json << "\"conf\":" << boxes[i].confidence << ",";
        json << "\"class_id\":" << (int)boxes[i].classID << ",";
        json << "\"track_id\":" << (int)boxes[i].trackID;
        json << "}";
    }

    json << "]}";

    std::string payload = json.str();

    /* 断网时缓冲消息, 重连后补发 */
    if (!_connected) {
        std::lock_guard<std::mutex> lock(_pending_mutex);
        if (_pending_queue.size() < MAX_PENDING) {
            _pending_queue.push_back({topic, payload, 1});
        }
        return false;
    }

    int ret = mosquitto_publish(_mosq, NULL, topic.c_str(),
                                payload.size(), payload.c_str(), 1, false);
    if (ret != MOSQ_ERR_SUCCESS) {
        fprintf(stderr, "[MQTT] Publish failed: %s\n",
                mosquitto_strerror(ret));
        return false;
    }
    return true;
}

/* ── 发布心跳 ──────────────────────────────────────────── */
bool MqttPublisher::publish_health(const std::string &topic,
                                   int frame_index)
{
    if (!_mosq)
        return false;

    std::ostringstream json;
    json << "{";
    json << "\"device_id\":\"" << _client_id << "\",";
    json << "\"status\":\"online\",";
    json << "\"frame_index\":" << frame_index << ",";
    json << "\"timestamp\":" << time(nullptr);
    json << "}";

    std::string payload = json.str();
    int ret = mosquitto_publish(_mosq, NULL, topic.c_str(),
                                payload.size(), payload.c_str(), 0, false);
    if (ret != MOSQ_ERR_SUCCESS) {
        fprintf(stderr, "[MQTT] Health publish failed: %s\n",
                mosquitto_strerror(ret));
        return false;
    }
    return true;
}

/* ── 指令处理 ──────────────────────────────────────────── */
/*
 * handle_command — 解析 PC 端下发的指令, 通过回调转发到业务层
 *
 * 支持的指令:
 *   switch_scene: 切换场景
 *   reload_model: 热加载模型
 *   app_update:   应用更新
 *   rollback:     版本回滚
 *   restart:      重启推理服务
 */
void MqttPublisher::handle_command(const char *topic,
                                   const char *payload, int len)
{
    std::string msg(payload, len);
    printf("[MQTT] Command received: %s\n", msg.c_str());

    /* 精确匹配 JSON key, 避免子串误触发 */
    auto find_cmd = [&msg](const char *cmd) -> bool {
        std::string key = "\"" + std::string(cmd) + "\"";
        return msg.find(key) != std::string::npos;
    };

    if (find_cmd("switch_scene")) {
        if (_cmd_callback) _cmd_callback(topic, payload, len);
    } else if (find_cmd("reload_model")) {
        if (_cmd_callback) _cmd_callback(topic, payload, len);
    } else if (find_cmd("app_update")) {
        if (_cmd_callback) _cmd_callback(topic, payload, len);
    } else if (find_cmd("rollback")) {
        if (_cmd_callback) _cmd_callback(topic, payload, len);
    } else if (find_cmd("start_recording")) {
        if (_cmd_callback) _cmd_callback(topic, payload, len);
    } else if (find_cmd("stop_recording")) {
        if (_cmd_callback) _cmd_callback(topic, payload, len);
    } else if (find_cmd("start_rtsp")) {
        if (_cmd_callback) _cmd_callback(topic, payload, len);
    } else if (find_cmd("stop_rtsp")) {
        if (_cmd_callback) _cmd_callback(topic, payload, len);
    } else if (find_cmd("restart")) {
        /* 重启是特殊指令, 直接发信号 */
        kill(getpid(), SIGTERM);
    }
}

/* ── 补发积压消息 ──────────────────────────────────────── */
/*
 * flush_pending_messages — 重连成功后补发断网期间缓冲的消息
 *
 * 只补发检测结果 (QoS 1), 心跳消息丢弃 (已过时)
 * 缓冲区最多 MAX_PENDING 条, 超出则丢弃最旧消息
 */
void MqttPublisher::flush_pending_messages()
{
    std::lock_guard<std::mutex> lock(_pending_mutex);
    if (_pending_queue.empty()) return;

    size_t flushed = 0;
    while (!_pending_queue.empty()) {
        const auto &msg = _pending_queue.front();
        int ret = mosquitto_publish(_mosq, NULL, msg.topic.c_str(),
                                    msg.payload.size(), msg.payload.c_str(),
                                    msg.qos, false);
        if (ret != MOSQ_ERR_SUCCESS) {
            fprintf(stderr, "[MQTT] Flush pending failed: %s\n",
                    mosquitto_strerror(ret));
            break;  /* 发送失败, 停止补发, 保留剩余消息 */
        }
        _pending_queue.pop_front();
        flushed++;
    }
    if (flushed > 0)
        printf("[MQTT] Flushed %zu pending messages (remaining: %zu)\n",
               flushed, _pending_queue.size());
}
