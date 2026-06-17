"""
Edge Service — 边缘设备管理 (简化适配版, 为 service_facade 注册)

功能:
  - 设备注册/心跳
  - 模型推送
  - 场景切换
"""

from __future__ import annotations


class EdgeService:
    """边缘设备管理服务 (适配 BackendServiceFacade 注册)"""

    def __init__(self, *, paths, session_factory, log_repository):
        self._paths = paths
        self._session_factory = session_factory
        self._log_repo = log_repository
        self._devices = {}

    def register_device(self, device_id: str, host: str, **kwargs) -> dict:
        self._devices[device_id] = {"device_id": device_id, "host": host, "status": "online", **kwargs}
        return {"status": "success", "device_id": device_id}

    def get_device(self, device_id: str) -> dict:
        dev = self._devices.get(device_id)
        if not dev:
            return {"status": "error", "message": "Device not found"}
        return {"status": "success", "data": dev}

    def list_devices(self) -> list:
        return list(self._devices.values())

    def switch_scene(self, device_id: str, scene: str) -> dict:
        if device_id not in self._devices:
            return {"status": "error", "message": "Device not found"}
        self._devices[device_id]["scene"] = scene
        return {"status": "success", "scene": scene}

    def set_device_status(self, device_id: str, status: str) -> dict:
        if device_id not in self._devices:
            return {"status": "error", "message": "Device not found"}
        self._devices[device_id]["status"] = status
        return {"status": "success"}