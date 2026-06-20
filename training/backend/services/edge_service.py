# SPDX-License-Identifier: MIT
"""
Edge Service — 边缘设备管理 (适配 BackendServiceFacade 注册)

功能:
  - 设备注册/心跳
  - 模型推送
  - 场景切换
  - 状态查询

依赖 backend.edge_client.EdgeClient 实现与边缘设备的实际通信。
"""

from __future__ import annotations

from backend.edge_client import EdgeClient, DeviceStatus


class EdgeService:
    """边缘设备管理服务 (适配 BackendServiceFacade 注册)"""

    def __init__(self, *, paths, session_factory, log_repository):
        self._paths = paths
        self._session_factory = session_factory
        self._log_repo = log_repository
        self._devices: dict[str, dict] = {}

    def register_device(self, device_id: str, host: str, **kwargs) -> dict:
        """注册边缘设备"""
        if device_id in self._devices:
            return {"status": "error", "message": "Device already registered"}

        self._devices[device_id] = {
            "device_id": device_id,
            "host": host,
            "status": "online",
            **kwargs,
        }
        self._log_repo.add(
            "info", f"Edge device registered: {device_id} @ {host}"
        )
        return {"status": "success", "device_id": device_id}

    def get_device(self, device_id: str) -> dict:
        """获取设备信息（尝试实时查询状态）"""
        dev = self._devices.get(device_id)
        if not dev:
            return {"status": "error", "message": "Device not found"}

        # 尝试实时查询设备状态
        try:
            client = EdgeClient(dev["host"])
            status = client.get_status()
            if status.status != "error":
                dev["status"] = status.status
                dev["scene"] = status.scene
                dev["model"] = status.model
        except Exception:
            pass  # 设备离线或不可达，返回缓存信息

        return {"status": "success", "data": dict(dev)}

    def list_devices(self) -> list[dict]:
        """列出所有已注册设备"""
        return list(self._devices.values())

    def unregister_device(self, device_id: str) -> dict:
        """注销设备"""
        if device_id not in self._devices:
            return {"status": "error", "message": "Device not found"}
        del self._devices[device_id]
        return {"status": "success"}

    def switch_scene(self, device_id: str, scene: str) -> dict:
        """
        切换边缘设备推理场景

        通过 JSON-RPC (SSH + UNIX socket) 发送切换指令。
        """
        dev = self._devices.get(device_id)
        if not dev:
            return {"status": "error", "message": "Device not found"}

        valid_scenes = {"face", "body", "vehicle", "defect"}
        if scene not in valid_scenes:
            return {"status": "error",
                    "message": f"Invalid scene: {scene}. "
                               f"Valid: {', '.join(valid_scenes)}"}

        try:
            client = EdgeClient(dev["host"])
            resp = client.switch_scene(scene)
            if resp.get("status") == 0:
                dev["scene"] = scene
                self._log_repo.add(
                    "info", f"Scene switched: {device_id} → {scene}"
                )
                return {"status": "success", "scene": scene}
            return resp
        except Exception as e:
            self._log_repo.add(
                "error", f"Scene switch failed: {device_id}: {e}"
            )
            return {"status": "error", "message": str(e)}

    def push_model(self, device_id: str, model_path: str,
                   model_name: str = None) -> dict:
        """
        推送模型到边缘设备

        分两步:
          1. SCP 拷贝模型文件
          2. JSON-RPC 通知热加载
        """
        dev = self._devices.get(device_id)
        if not dev:
            return {"status": "error", "message": "Device not found"}

        import os
        if not os.path.isfile(model_path):
            return {"status": "error",
                    "message": f"Model file not found: {model_path}"}

        file_size = os.path.getsize(model_path)
        max_size = 200 * 1024 * 1024  # 200MB
        if file_size > max_size:
            return {"status": "error",
                    "message": f"Model too large: {file_size} bytes "
                               f"(max {max_size})"}

        try:
            client = EdgeClient(dev["host"])
            resp = client.push_model(model_path, model_name)
            if resp.get("status") == 0:
                dev["model"] = model_name or os.path.basename(model_path)
                self._log_repo.add(
                    "info", f"Model pushed: {device_id} ← {model_path}"
                )
            return resp
        except Exception as e:
            self._log_repo.add(
                "error", f"Model push failed: {device_id}: {e}"
            )
            return {"status": "error", "message": str(e)}

    def restart_device(self, device_id: str) -> dict:
        """远程重启边缘设备推理服务"""
        dev = self._devices.get(device_id)
        if not dev:
            return {"status": "error", "message": "Device not found"}

        try:
            client = EdgeClient(dev["host"])
            resp = client.restart()
            if resp.get("status") == 0:
                dev["status"] = "restarting"
                self._log_repo.add(
                    "info", f"Device restarted: {device_id}"
                )
            return resp
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def set_device_status(self, device_id: str, status: str) -> dict:
        """手动更新设备状态"""
        if device_id not in self._devices:
            return {"status": "error", "message": "Device not found"}
        self._devices[device_id]["status"] = status
        return {"status": "success"}

    def query_status(self, device_id: str) -> DeviceStatus:
        """实时查询设备状态 (通过 EdgeClient)"""
        dev = self._devices.get(device_id)
        if not dev:
            return DeviceStatus(status="error")

        client = EdgeClient(dev["host"])
        return client.get_status()