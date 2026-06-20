/* SPDX-License-Identifier: MIT */
/*
 * MQTT Publisher — 检测结果上报 + 指令接收
 *
 * 基于 libmosquitto, 支持 QoS 0/1/2。
 * 指令通过 CommandCallback 转发到业务层 (ota_manager),
 * 本模块只负责通信, 不包含业务逻辑。
 */

#ifndef MQTT_PUBLISHER_H
#define MQTT_PUBLISHER_H

#include <string>
#include <vector>
#include <functional>
#include "detect_box.h"

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

    /* 发布 OTA 状态上报 */
    bool publish_ota_status(const std::string &topic,
                            const std::string &status_json);

    bool is_connected() const { return _connected; }

    /* 指令回调: 接收 PC 端远程指令, 转发到 ota_manager */
    using CommandCallback = std::function<void(const char *topic,
                                               const char *payload, int len)>;
    void set_command_callback(CommandCallback cb) {
        _cmd_callback = cb;
    }

    void handle_command(const char *topic, const char *payload, int len);

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
