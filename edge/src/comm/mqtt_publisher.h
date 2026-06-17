/* SPDX-License-Identifier: MIT */
/*
 * MQTT Publisher — Header
 */

#ifndef MQTT_PUBLISHER_H
#define MQTT_PUBLISHER_H

#include <string>
#include <vector>
#include <functional>
#include "detect_box.h"

/*
 * MqttPublisher — MQTT 检测结果上报
 *
 * 基于 libmosquitto, 支持 QoS 0/1/2。
 * 提供 Protobuf/JSON 两种序列化方式。
 *
 * 使用方式:
 *   MqttPublisher mqtt;
 *   mqtt.connect("192.168.1.100", 1883, "device-id", 60);
 *   mqtt.publish_detections("edge/device/detections", boxes, frame_idx, ts);
 *   mqtt.publish_health("edge/device/health", frame_idx);
 *   mqtt.disconnect();
 */
class MqttPublisher {
public:
    MqttPublisher();
    ~MqttPublisher();

    bool connect(const std::string &host, int port,
                 const std::string &client_id, int keepalive);
    void disconnect();

    bool publish_detections(const std::string &topic,
                            const std::vector<DetectBox> &boxes,
                            int frame_index, int64_t timestamp_us);

    bool publish_health(const std::string &topic, int frame_index);

    bool is_connected() const { return _connected; }

    /* 指令回调: 接收 PC 端远程指令 */
    using CommandCallback = std::function<void(const char *topic,
                                               const char *payload, int len)>;
    void set_command_callback(CommandCallback cb) {
        _cmd_callback = cb;
    }

private:
    void handle_command(const char *topic, const char *payload, int len);

private:
    struct mosquitto *_mosq;
    bool _connected;

    std::string _host;
    int _port;
    std::string _client_id;
    std::string _cmd_topic;
    int _last_published_mid = 0;

    CommandCallback _cmd_callback;
};

#endif /* MQTT_PUBLISHER_H */
