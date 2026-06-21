# SPDX-License-Identifier: MIT
"""
Device Discovery Service — 使用 mDNS/Zeroconf 发现边缘设备

扫描 _edge-ai._tcp.local. 服务类型, 自动发现局域网内的边缘 AI 设备。
发现到的设备可用于快速注册到设备列表。

用法:
    from backend.services.device_discovery_service import DeviceDiscoveryService

    discovery = DeviceDiscoveryService()
    devices = discovery.scan(timeout=5)
    # => [{"name": "rk3399pro-001", "host": "192.168.1.50", "port": 50051, "properties": {...}}]
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Optional, Callable

try:
    from zeroconf import Zeroconf, ServiceBrowser, ServiceStateChange
    HAS_ZEROCONF = True
except ImportError:
    HAS_ZEROCONF = False


@dataclass
class DiscoveredDevice:
    """发现的设备"""
    name: str              # 设备名称 (如 "rk3399pro-001")
    host: str              # IP 地址
    port: int              # gRPC 端口
    properties: dict       # mDNS TXT 记录 (场景、版本等)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "host": self.host,
            "port": self.port,
            "properties": self.properties,
        }


class _DeviceListener:
    """zeroconf ServiceListener 实现 (兼容 0.149+ API)"""

    def __init__(self, on_found: Callable[[DiscoveredDevice], None] = None):
        self._on_found = on_found

    def add_service(self, zc, type_, name):
        info = zc.get_service_info(type_, name)
        if info:
            addresses = info.parsed_addresses()
            host = addresses[0] if addresses else "unknown"
            port = info.port or 50051

            properties = {}
            if info.properties:
                for key, value in info.properties.items():
                    try:
                        properties[key.decode() if isinstance(key, bytes) else key] = \
                            value.decode() if isinstance(value, bytes) else value
                    except (UnicodeDecodeError, AttributeError):
                        pass

            device = DiscoveredDevice(
                name=name.replace(f".{DeviceDiscoveryService.SERVICE_TYPE}", ""),
                host=host,
                port=port,
                properties=properties,
            )
            if self._on_found:
                self._on_found(device)

    def update_service(self, zc, type_, name):
        pass

    def remove_service(self, zc, type_, name):
        pass


class DeviceDiscoveryService:
    """
    边缘设备发现服务

    使用 Zeroconf (mDNS/Bonjour) 扫描局域网内的 _edge-ai._tcp.local. 服务。
    """

    SERVICE_TYPE = "_edge-ai._tcp.local."

    def __init__(self):
        if not HAS_ZEROCONF:
            raise ImportError("zeroconf 未安装: pip install zeroconf>=0.100.0")
        self._zeroconf: Optional[Zeroconf] = None
        self._discovered: list[DiscoveredDevice] = []
        self._on_discovery: Optional[Callable[[DiscoveredDevice], None]] = None

    def scan(self, timeout: float = 5.0) -> list[dict]:
        """
        扫描局域网内的边缘设备

        Args:
            timeout: 扫描超时时间 (秒)

        Returns:
            发现的设备列表 [{"name", "host", "port", "properties"}, ...]
        """
        self._discovered = []
        self._zeroconf = Zeroconf()

        def on_found(device: DiscoveredDevice):
            self._discovered.append(device)
            if self._on_discovery:
                self._on_discovery(device)

        listener = _DeviceListener(on_found=on_found)

        try:
            browser = ServiceBrowser(self._zeroconf, self.SERVICE_TYPE, listener=listener)
            time.sleep(timeout)
            browser.cancel()
        finally:
            self._zeroconf.close()
            self._zeroconf = None

        return [d.to_dict() for d in self._discovered]

    def set_discovery_callback(self, callback: Callable[[DiscoveredDevice], None]):
        """设置实时发现回调"""
        self._on_discovery = callback

    def start_browser(self, on_discovery: Callable[[dict], None]) -> Zeroconf:
        """
        启动持续扫描 (后台线程)

        Args:
            on_discovery: 发现设备时的回调

        Returns:
            Zeroconf 实例 (调用者负责关闭)
        """
        if not HAS_ZEROCONF:
            raise ImportError("zeroconf 未安装")

        self._zeroconf = Zeroconf()

        def on_found(device: DiscoveredDevice):
            on_discovery(device.to_dict())

        listener = _DeviceListener(on_found=on_found)
        ServiceBrowser(self._zeroconf, self.SERVICE_TYPE, listener=listener)
        return self._zeroconf

    def stop_browser(self):
        """停止扫描"""
        if self._zeroconf:
            self._zeroconf.close()
            self._zeroconf = None


# CLI 入口
if __name__ == "__main__":
    import json
    import sys

    timeout = float(sys.argv[1]) if len(sys.argv) > 1 else 5.0
    print(f"Scanning for edge devices ({timeout}s)...")

    discovery = DeviceDiscoveryService()
    devices = discovery.scan(timeout)

    print(f"Found {len(devices)} device(s):")
    for d in devices:
        print(f"  - {d['name']} @ {d['host']}:{d['port']}")
        if d['properties']:
            for k, v in d['properties'].items():
                print(f"      {k}: {v}")

    print("\nJSON output:")
    print(json.dumps(devices, indent=2))
