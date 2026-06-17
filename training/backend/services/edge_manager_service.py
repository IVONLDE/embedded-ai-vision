# SPDX-License-Identifier: MIT
#
# Edge Device Manager Service — 边缘设备管理
#
# PC 端 (ISG-mian) 中管理边缘设备的 Service。
# 通过 gRPC 与边缘设备通信，通过 MQTT 接收检测结果。
#
# 功能:
#   - 设备注册/发现
#   - 心跳监控
#   - 模型推送 (OTA)
#   - 场景切换
#   - 远程重启

from __future__ import annotations

import time
import threading
from dataclasses import dataclass
from typing import Callable, Dict, List


@dataclass
class DeviceInfo:
    """边缘设备信息"""
    device_id: str = ""
    host: str = ""              # IP 地址
    grpc_port: int = 50051
    status: str = "offline"     # online / offline / error
    scene: str = ""
    model_version: str = ""
    fps: float = 0.0
    npu_usage: float = 0.0
    cpu_temp: float = 0.0
    memory_bytes: int = 0
    uptime_sec: int = 0
    frame_count: int = 0
    last_heartbeat: float = 0.0
    avg_inference_ms: float = 0.0


class EdgeManagerService:
    """
    边缘设备管理器

    用法:
        mgr = EdgeManagerService()
        mgr.register_device("rk3399pro-001", "192.168.1.50")
        mgr.push_model("rk3399pro-001", "/path/to/model.rknn")
        mgr.switch_scene("rk3399pro-001", "vehicle")
        print(mgr.get_device_status("rk3399pro-001"))
    """

    def __init__(self):
        self._devices: Dict[str, DeviceInfo] = {}
        self._callbacks: Dict[str, List[Callable]] = {
            "on_heartbeat": [],
            "on_detection": [],
            "on_status_change": [],
        }

    # ── 设备注册 ──────────────────────────────────────────
    def register_device(self, device_id: str, host: str,
                        grpc_port: int = 50051) -> dict:
        """注册边缘设备"""
        if device_id in self._devices:
            return {"status": "error", "message": "Device already registered"}

        device = DeviceInfo(
            device_id=device_id,
            host=host,
            grpc_port=grpc_port,
        )
        self._devices[device_id] = device

        print(f"[EdgeManager] Device registered: {device_id} @ {host}:{grpc_port}")
        return {"status": "success", "device_id": device_id}

    def unregister_device(self, device_id: str) -> dict:
        """注销设备"""
        if device_id not in self._devices:
            return {"status": "error", "message": "Device not found"}

        del self._devices[device_id]
        print(f"[EdgeManager] Device unregistered: {device_id}")
        return {"status": "success"}

    # ── 设备状态 ──────────────────────────────────────────
    def get_device_status(self, device_id: str) -> dict:
        """获取设备状态"""
        device = self._devices.get(device_id)
        if not device:
            return {"status": "error", "message": "Device not found"}

        return {
            "status": "success",
            "device_id": device.device_id,
            "host": device.host,
            "device_status": device.status,
            "scene": device.scene,
            "model_version": device.model_version,
            "fps": device.fps,
            "npu_usage": device.npu_usage,
            "cpu_temp": device.cpu_temp,
            "uptime_sec": device.uptime_sec,
            "frame_count": device.frame_count,
            "avg_inference_ms": device.avg_inference_ms,
        }

    def list_devices(self) -> List[dict]:
        """列出所有设备"""
        return [self.get_device_status(did) for did in self._devices]

    # ── 模型推送 (via gRPC) ───────────────────────────────
    def push_model(self, device_id: str, model_path: str,
                   model_version: str = "") -> dict:
        """推送模型到边缘设备"""
        device = self._devices.get(device_id)
        if not device:
            return {"status": "error", "message": "Device not found"}

        # 校验文件大小 (限制 200MB, 避免 OOM)
        import os
        file_size = os.path.getsize(model_path)
        max_size = 200 * 1024 * 1024  # 200MB
        if file_size > max_size:
            return {"status": "error",
                    "message": f"Model too large: {file_size} bytes (max {max_size})"}

        try:
            with open(model_path, "rb") as f:
                model_data = f.read()
        except (FileNotFoundError, OSError) as e:
            return {"status": "error",
                    "message": f"Cannot read model file: {e}"}

        print(f"[EdgeManager] Pushing model to {device_id}: {model_path} "
              f"({len(model_data)} bytes)")

        # TODO: gRPC call — PushModel
        # stub = EdgeServiceStub(grpc.insecure_channel(f"{device.host}:{device.grpc_port}"))
        # response = stub.PushModel(ModelRequest(
        #     device_id=device_id,
        #     model_data=model_data,
        #     model_version=model_version,
        # ))
        # return {"status": "success", "model_version": response.model_version}

        return {"status": "success", "message": "Model pushed (gRPC not yet connected)"}

    # ── 场景切换 (via gRPC) ───────────────────────────────
    def switch_scene(self, device_id: str, scene_name: str) -> dict:
        """切换边缘设备推理场景"""
        device = self._devices.get(device_id)
        if not device:
            return {"status": "error", "message": "Device not found"}

        valid_scenes = ["face", "body", "vehicle", "defect"]
        if scene_name not in valid_scenes:
            return {"status": "error", "message": f"Invalid scene: {scene_name}"}

        print(f"[EdgeManager] Switching scene: {device_id} → {scene_name}")

        # TODO: gRPC call — SwitchScene
        device.scene = scene_name

        return {"status": "success", "scene": scene_name}

    # ── 心跳处理 (via MQTT callback) ──────────────────────
    def on_heartbeat_received(self, device_id: str, payload: dict):
        """处理设备心跳"""
        device = self._devices.get(device_id)
        if not device:
            return

        device.status = payload.get("status", "online")
        device.fps = payload.get("fps", 0.0)
        device.scene = payload.get("scene", device.scene)
        device.model_version = payload.get("model_version", device.model_version)
        device.last_heartbeat = time.time()

        for callback in self._callbacks["on_heartbeat"]:
            callback(device_id, payload)

    # ── 检测结果处理 (via MQTT callback) ──────────────────
    def on_detection_received(self, device_id: str, payload: dict):
        """处理检测结果"""
        device = self._devices.get(device_id)
        if not device:
            return

        device.frame_count = payload.get("frame_index", 0)
        detections = payload.get("detections", [])

        for callback in self._callbacks["on_detection"]:
            callback(device_id, detections)

    # ── 事件回调 ──────────────────────────────────────────
    def add_callback(self, event: str, callback: Callable):
        """注册事件回调"""
        if event in self._callbacks:
            self._callbacks[event].append(callback)

    # ── 远程重启 ──────────────────────────────────────────
    def restart_device(self, device_id: str) -> dict:
        """远程重启设备推理服务"""
        device = self._devices.get(device_id)
        if not device:
            return {"status": "error", "message": "Device not found"}

        print(f"[EdgeManager] Restarting device: {device_id}")

        # TODO: gRPC call — Restart
        return {"status": "success", "message": "Restart command sent"}