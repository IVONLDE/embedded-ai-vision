"""
MQTT Bridge — PC 端 MQTT 订阅服务

订阅板子端上报的检测结果、心跳、OTA 状态，
通过 Qt 信号通知 UI 更新。

用法:
    bridge = MqttBridge(broker_host="192.168.117.161", broker_port=1883)
    bridge.detection_received.connect(on_detection)
    bridge.health_received.connect(on_health)
    bridge.start()
"""

from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass
from typing import Optional, Callable

try:
    import paho.mqtt.client as mqtt
    HAS_MQTT = True
except ImportError:
    HAS_MQTT = False


@dataclass
class DetectionData:
    """检测结果"""
    device_id: str = ""
    frame_index: int = 0
    timestamp_us: int = 0
    detections: list = None  # [{"x1","y1","x2","y2","conf","class_id","track_id"}]

    @classmethod
    def from_json(cls, payload: str) -> "DetectionData":
        try:
            d = json.loads(payload)
            return cls(
                device_id=d.get("device_id", ""),
                frame_index=d.get("frame_index", 0),
                timestamp_us=d.get("timestamp_us", 0),
                detections=d.get("detections", []),
            )
        except (json.JSONDecodeError, TypeError):
            return cls()


@dataclass
class HealthData:
    """心跳数据"""
    device_id: str = ""
    status: str = "unknown"
    frame_index: int = 0
    timestamp: int = 0

    @classmethod
    def from_json(cls, payload: str) -> "HealthData":
        try:
            d = json.loads(payload)
            return cls(
                device_id=d.get("device_id", ""),
                status=d.get("status", "unknown"),
                frame_index=d.get("frame_index", 0),
                timestamp=d.get("timestamp", 0),
            )
        except (json.JSONDecodeError, TypeError):
            return cls()


class MqttBridge:
    """
    PC 端 MQTT 订阅桥接

    连接板子端 MQTT Broker (直连或 SSH 隧道)，
    订阅 edge/# topic，通过回调通知上层。
    """

    def __init__(self, broker_host: str = "127.0.0.1",
                 broker_port: int = 1883,
                 on_detection: Callable[[DetectionData], None] = None,
                 on_health: Callable[[HealthData], None] = None,
                 on_ota_status: Callable[[dict], None] = None):
        if not HAS_MQTT:
            raise ImportError("paho-mqtt 未安装: pip install paho-mqtt")

        self._broker_host = broker_host
        self._broker_port = broker_port
        self._on_detection = on_detection
        self._on_health = on_health
        self._on_ota_status = on_ota_status
        self._client: Optional[mqtt.Client] = None
        self._connected = False

    @property
    def connected(self) -> bool:
        return self._connected

    def start(self) -> bool:
        """启动 MQTT 客户端"""
        self._client = mqtt.Client(callback_api_version=mqtt.CallbackAPIVersion.VERSION2)
        self._client.on_connect = self._on_connect
        self._client.on_message = self._on_message
        self._client.on_disconnect = self._on_disconnect

        try:
            self._client.connect(self._broker_host, self._broker_port, keepalive=60)
            self._client.loop_start()
            return True
        except Exception as e:
            print(f"[MqttBridge] 连接失败: {e}")
            return False

    def stop(self):
        """停止 MQTT 客户端"""
        if self._client:
            self._client.loop_stop()
            self._client.disconnect()
            self._client = None
            self._connected = False

    def _on_connect(self, client, userdata, flags, rc, properties=None):
        if rc == 0:
            self._connected = True
            # 订阅所有 edge/ 下的 topic
            client.subscribe("edge/#")
            print("[MqttBridge] 已连接, 订阅 edge/#")
        else:
            print(f"[MqttBridge] 连接失败, rc={rc}")

    def _on_disconnect(self, client, userdata, flags, rc, properties=None):
        self._connected = False
        print("[MqttBridge] 断开连接")

    def _on_message(self, client, userdata, msg):
        topic = msg.topic
        try:
            payload = msg.payload.decode("utf-8")
        except UnicodeDecodeError:
            return

        # 路由到对应回调
        if topic.endswith("/detections"):
            if self._on_detection:
                data = DetectionData.from_json(payload)
                self._on_detection(data)

        elif topic.endswith("/health"):
            if self._on_health:
                data = HealthData.from_json(payload)
                self._on_health(data)

        elif topic.endswith("/ota_status"):
            if self._on_ota_status:
                try:
                    self._on_ota_status(json.loads(payload))
                except json.JSONDecodeError:
                    pass
