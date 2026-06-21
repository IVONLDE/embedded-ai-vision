"""
MQTT Bridge — PC 端 MQTT 订阅服务

订阅板子端上报的检测结果、心跳、OTA 状态，
通过 Qt 信号通知 UI 更新。

支持指数退避自动重连。

用法:
    bridge = MqttBridge(broker_host="debian10.local", broker_port=1883)
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

    支持指数退避自动重连:
      - 初始延迟 5 秒
      - 最大延迟 60 秒
      - 每次重连失败延迟翻倍
      - 连接成功时重置延迟
    """

    # 指数退避参数
    _INITIAL_RECONNECT_DELAY = 5   # 初始 5 秒
    _MAX_RECONNECT_DELAY = 60      # 最大 60 秒

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

        # 重连状态
        self._reconnect_delay = self._INITIAL_RECONNECT_DELAY
        self._reconnect_timer: Optional[threading.Timer] = None
        self._intentional_disconnect = False  # 是否主动断开 (stop() 调用)

    @property
    def connected(self) -> bool:
        return self._connected

    @property
    def broker_host(self) -> str:
        return self._broker_host

    @property
    def broker_port(self) -> int:
        return self._broker_port

    def start(self) -> bool:
        """启动 MQTT 客户端"""
        self._intentional_disconnect = False
        self._reconnect_delay = self._INITIAL_RECONNECT_DELAY
        return self._connect()

    def stop(self):
        """停止 MQTT 客户端"""
        self._intentional_disconnect = True
        self._cancel_reconnect()
        if self._client:
            self._client.loop_stop()
            self._client.disconnect()
            self._client = None
            self._connected = False

    def reconfigure(self, broker_host: str, broker_port: int) -> bool:
        """重新配置 Broker 地址并重连"""
        self.stop()
        self._broker_host = broker_host
        self._broker_port = broker_port
        return self.start()

    def publish(self, topic: str, payload: str, qos: int = 1) -> bool:
        """发布 MQTT 消息 (用于远程命令下发)"""
        if not self._client or not self._connected:
            print(f"[MqttBridge] 发布失败: 未连接")
            return False
        try:
            result = self._client.publish(topic, payload, qos=qos)
            if result.rc == mqtt.MQTT_ERR_SUCCESS:
                print(f"[MqttBridge] 已发布: {topic} ← {payload[:80]}")
                return True
            else:
                print(f"[MqttBridge] 发布失败: rc={result.rc}")
                return False
        except Exception as e:
            print(f"[MqttBridge] 发布异常: {e}")
            return False

    # ── 内部连接方法 ───────────────────────────────────────

    def _connect(self) -> bool:
        """创建客户端并连接"""
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
            self._schedule_reconnect()
            return False

    # ── 回调 ───────────────────────────────────────────────

    def _on_connect(self, client, userdata, flags, rc, properties=None):
        if rc == 0:
            self._connected = True
            # 连接成功, 重置重连延迟
            self._reconnect_delay = self._INITIAL_RECONNECT_DELAY
            # 订阅所有 edge/ 下的 topic
            client.subscribe("edge/#")
            print("[MqttBridge] 已连接, 订阅 edge/#")
        else:
            print(f"[MqttBridge] 连接失败, rc={rc}")
            self._schedule_reconnect()

    def _on_disconnect(self, client, userdata, flags, rc, properties=None):
        self._connected = False
        if self._intentional_disconnect:
            print("[MqttBridge] 主动断开连接")
            return
        # 非正常断开, 触发自动重连
        if rc != 0:
            print(f"[MqttBridge] 异常断开 (rc={rc}), 将自动重连...")
            self._schedule_reconnect()
        else:
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

    # ── 指数退避重连 ───────────────────────────────────────

    def _schedule_reconnect(self):
        """安排下一次重连 (延迟递增)"""
        if self._intentional_disconnect:
            return
        self._cancel_reconnect()

        delay = self._reconnect_delay
        print(f"[MqttBridge] {delay}秒后重连...")

        self._reconnect_timer = threading.Timer(delay, self._reconnect)
        self._reconnect_timer.daemon = True
        self._reconnect_timer.start()

        # 指数退避: 下次延迟翻倍, 不超过最大值
        self._reconnect_delay = min(self._reconnect_delay * 2,
                                     self._MAX_RECONNECT_DELAY)

    def _cancel_reconnect(self):
        """取消待执行的重连定时器"""
        if self._reconnect_timer is not None:
            self._reconnect_timer.cancel()
            self._reconnect_timer = None

    def _reconnect(self):
        """执行重连"""
        if self._intentional_disconnect:
            return
        print(f"[MqttBridge] 正在重连 {self._broker_host}:{self._broker_port}...")
        try:
            # 先清理旧客户端
            if self._client:
                try:
                    self._client.loop_stop()
                    self._client.disconnect()
                except Exception:
                    pass
            self._connect()
        except Exception as e:
            print(f"[MqttBridge] 重连失败: {e}")
            self._schedule_reconnect()
