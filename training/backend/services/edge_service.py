# SPDX-License-Identifier: MIT
"""
Edge Service — 边缘设备管理 + OTA 升级服务

功能:
  - 设备注册/心跳/状态管理
  - 模型版本管理 + 推送
  - 批量部署到多设备
  - 版本回滚
  - MQTT 心跳处理

使用 EdgeClient (SSH + JSON-RPC) 与边缘设备通信。
"""

from __future__ import annotations

import hashlib
import os
import time
import threading
from datetime import datetime
from typing import Optional
from concurrent.futures import ThreadPoolExecutor, as_completed

from backend.edge_client import EdgeClient, DeviceStatus
from backend.repositories.edge_device_repository import EdgeDeviceRepository
from backend.repositories.model_version_repository import ModelVersionRepository


class EdgeService:
    """边缘设备管理 + OTA 服务"""

    def __init__(self, *, paths, session_factory, log_repository,
                 edge_device_repository: EdgeDeviceRepository = None,
                 model_version_repository: ModelVersionRepository = None):
        self._paths = paths
        self._session_factory = session_factory
        self._log_repo = log_repository
        self._device_repo = edge_device_repository or EdgeDeviceRepository(session_factory)
        self._model_repo = model_version_repository or ModelVersionRepository(session_factory)

        # 批量部署线程池
        self._executor = ThreadPoolExecutor(max_workers=4)

    # ── 设备管理 ─────────────────────────────────────────────

    def register_device(self, device_id: str, name: str, host: str,
                        grpc_port: int = 50051, tags: dict = None) -> dict:
        """
        注册边缘设备

        Args:
            device_id: 设备唯一标识
            name: 显示名称
            host: IP 地址
            grpc_port: gRPC 端口 (默认 50051)
            tags: 标签 (如 {"location": "entrance", "scene": "vehicle"})
        """
        try:
            existing = self._device_repo.get_by_device_id(device_id)
            if existing:
                return {"status": "error", "message": "Device already registered"}

            device = self._device_repo.create(
                device_id=device_id,
                name=name,
                host=host,
                grpc_port=grpc_port,
                tags=tags or {},
            )
            self._log_repo.add("info", f"Edge device registered: {device_id} @ {host}")
            return {"status": "success", "device": self._device_to_dict(device)}
        except Exception as e:
            self._log_repo.add("error", f"Failed to register device {device_id}: {e}")
            return {"status": "error", "message": str(e)}

    def get_device(self, device_id: str) -> dict:
        """获取设备信息 (包含实时状态查询)"""
        device = self._device_repo.get_by_device_id(device_id)
        if not device:
            return {"status": "error", "message": "Device not found"}

        # 尝试实时查询状态
        try:
            client = EdgeClient(device.host, grpc_port=device.grpc_port)
            status = client.get_status()
            if status.status != "error":
                # 更新遥测数据
                self._device_repo.update(
                    device_id,
                    status=status.status,
                    scene=status.scene,
                    model_version=status.model,
                    fps=getattr(status, "fps", 0),
                    npu_usage=getattr(status, "npu_usage", 0),
                    cpu_temp=getattr(status, "cpu_temp", 0),
                    last_heartbeat=datetime.utcnow(),
                )
                device = self._device_repo.get_by_device_id(device_id)
        except Exception:
            pass

        return {"status": "success", "device": self._device_to_dict(device)}

    def list_devices(self, status: str = None) -> list[dict]:
        """列出所有设备"""
        devices = self._device_repo.list_all(status=status)
        return [self._device_to_dict(d) for d in devices]

    def unregister_device(self, device_id: str) -> dict:
        """注销设备"""
        success = self._device_repo.delete(device_id)
        if success:
            self._log_repo.add("info", f"Edge device unregistered: {device_id}")
            return {"status": "success"}
        return {"status": "error", "message": "Device not found"}

    # ── 场景切换 ────────────────────────────────────────────

    def switch_scene(self, device_id: str, scene: str) -> dict:
        """切换边缘设备推理场景"""
        device = self._device_repo.get_by_device_id(device_id)
        if not device:
            return {"status": "error", "message": "Device not found"}

        valid_scenes = {"face", "body", "vehicle", "defect"}
        if scene not in valid_scenes:
            return {"status": "error",
                    "message": f"Invalid scene: {scene}. Valid: {', '.join(valid_scenes)}"}

        try:
            client = EdgeClient(device.host, grpc_port=device.grpc_port)
            resp = client.switch_scene(scene)
            if resp.get("status") == 0:
                self._device_repo.update(device_id, scene=scene)
                self._log_repo.add("info", f"Scene switched: {device_id} → {scene}")
                return {"status": "success", "scene": scene}
            return resp
        except Exception as e:
            self._log_repo.add("error", f"Scene switch failed: {device_id}: {e}")
            return {"status": "error", "message": str(e)}

    # ── 模型推送 (单设备) ───────────────────────────────────

    def push_model(self, device_id: str, model_path: str,
                   model_name: str = None, model_version: str = None,
                   auto_rollback: bool = True) -> dict:
        """
        推送模型到边缘设备 (SCP + JSON-RPC)

        Args:
            device_id: 目标设备 ID
            model_path: 本地模型文件路径 (.rknn)
            model_name: 设备上的模型名称 (默认使用文件名)
            model_version: 模型版本号 (用于 OTA 管理)
            auto_rollback: 失败时自动回滚
        """
        device = self._device_repo.get_by_device_id(device_id)
        if not device:
            return {"status": "error", "message": "Device not found"}

        if not os.path.isfile(model_path):
            return {"status": "error", "message": f"Model file not found: {model_path}"}

        file_size = os.path.getsize(model_path)
        max_size = 200 * 1024 * 1024  # 200MB
        if file_size > max_size:
            return {"status": "error",
                    "message": f"Model too large: {file_size} bytes (max {max_size})"}

        # 计算 SHA256
        sha256 = self._compute_file_sha256(model_path)

        # 模型名称默认使用文件名
        if model_name is None:
            model_name = os.path.basename(model_path)

        try:
            client = EdgeClient(device.host, grpc_port=device.grpc_port)
            resp = client.push_model(model_path, model_name)

            if resp.get("status") == 0:
                self._device_repo.update(
                    device_id,
                    model_version=model_version or model_name,
                )

                # 如果有 ModelVersion 记录, 添加部署记录
                if model_version:
                    mvs = self._model_repo.list_all(scene=device.scene)
                    for mv in mvs:
                        if mv.version == model_version:
                            self._model_repo.add_deployed_device(mv.id, device_id)
                            break

                self._log_repo.add(
                    "info", f"Model pushed: {device_id} ← {model_path}"
                )
                return {
                    "status": "success",
                    "model": model_name,
                    "sha256": sha256,
                }
            return resp
        except Exception as e:
            self._log_repo.add("error", f"Model push failed: {device_id}: {e}")
            return {"status": "error", "message": str(e)}

    # ── 批量部署 ────────────────────────────────────────────

    def deploy_to_devices(self, model_path: str, device_ids: list[str],
                           model_version: str = None,
                           progress_callback=None) -> dict:
        """
        批量部署模型到多个设备

        Args:
            model_path: 本地模型文件路径
            device_ids: 目标设备 ID 列表
            model_version: 模型版本号
            progress_callback: 进度回调 (device_id, status, message)

        Returns:
            {"status": "success", "results": {device_id: result_dict}}
        """
        if not os.path.isfile(model_path):
            return {"status": "error", "message": f"Model file not found: {model_path}"}

        results = {}
        total = len(device_ids)
        completed = 0

        def push_one(device_id: str) -> tuple[str, dict]:
            nonlocal completed
            result = self.push_model(device_id, model_path, model_version=model_version)
            completed += 1
            if progress_callback:
                progress_callback(device_id, result.get("status"), result.get("message"), completed, total)
            return device_id, result

        # 并行推送 (最多 4 个设备同时)
        futures = {}
        for device_id in device_ids:
            future = self._executor.submit(push_one, device_id)
            futures[future] = device_id

        for future in as_completed(futures):
            device_id, result = future.result()
            results[device_id] = result

        success_count = sum(1 for r in results.values() if r.get("status") == "success")
        self._log_repo.add(
            "info",
            f"Batch deploy completed: {success_count}/{total} devices"
        )

        return {
            "status": "success" if success_count == total else "partial",
            "total": total,
            "success": success_count,
            "failed": total - success_count,
            "results": results,
        }

    # ── 版本回滚 ────────────────────────────────────────────

    def rollback(self, device_id: str, target: str = "model") -> dict:
        """
        回滚设备到上一版本

        Args:
            device_id: 设备 ID
            target: "model" 或 "app"
        """
        device = self._device_repo.get_by_device_id(device_id)
        if not device:
            return {"status": "error", "message": "Device not found"}

        try:
            client = EdgeClient(device.host, grpc_port=device.grpc_port)
            # 发送回滚命令 (MQTT 或 JSON-RPC)
            resp = client._call("Rollback", {"target": target})

            if resp.get("status") == 0:
                self._log_repo.add("info", f"Rollback success: {device_id} → {target}")
                return {"status": "success", "rolled_back": target}
            return resp
        except Exception as e:
            self._log_repo.add("error", f"Rollback failed: {device_id}: {e}")
            return {"status": "error", "message": str(e)}

    # ── 重启设备 ────────────────────────────────────────────

    def restart_device(self, device_id: str) -> dict:
        """远程重启边缘设备推理服务"""
        device = self._device_repo.get_by_device_id(device_id)
        if not device:
            return {"status": "error", "message": "Device not found"}

        try:
            client = EdgeClient(device.host, grpc_port=device.grpc_port)
            resp = client.restart()
            if resp.get("status") == 0:
                self._device_repo.update(device_id, status="restarting")
                self._log_repo.add("info", f"Device restarted: {device_id}")
            return resp
        except Exception as e:
            return {"status": "error", "message": str(e)}

    # ── 心跳处理 (MQTT) ─────────────────────────────────────

    def on_heartbeat(self, device_id: str, telemetry: dict) -> dict:
        """
        处理 MQTT 心跳消息, 更新设备遥测数据

        Args:
            device_id: 设备 ID
            telemetry: 遥测数据 {
                "status": "online",
                "fps": 24.5,
                "npu_usage": 72.3,
                "cpu_temp": 65.2,
                "memory_bytes": 1048576,
                "model_version": "yolov5n-v3",
                "scene": "vehicle"
            }
        """
        try:
            device = self._device_repo.get_by_device_id(device_id)
            if not device:
                # 自动注册新设备 (可选)
                self._log_repo.add(
                    "warning", f"Heartbeat from unknown device: {device_id}"
                )
                return {"status": "error", "message": "Unknown device"}

            self._device_repo.update(
                device_id,
                status=telemetry.get("status", "online"),
                scene=telemetry.get("scene", device.scene),
                model_version=telemetry.get("model_version", device.model_version),
                fps=telemetry.get("fps", 0),
                npu_usage=telemetry.get("npu_usage", 0),
                cpu_temp=telemetry.get("cpu_temp", 0),
                memory_bytes=telemetry.get("memory_bytes", 0),
                frame_count=telemetry.get("frame_count", 0),
                avg_inference_ms=telemetry.get("avg_inference_ms", 0),
                last_heartbeat=datetime.utcnow(),
            )
            return {"status": "success"}
        except Exception as e:
            self._log_repo.add("error", f"Heartbeat processing failed: {e}")
            return {"status": "error", "message": str(e)}

    # ── 模型版本管理 ───────────────────────────────────────

    def register_model_version(self, name: str, version: str,
                                model_type: str, scene: str,
                                file_path: str, sha256: str = None,
                                file_size: int = None, quantization: str = "fp16",
                                onnx_path: str = None, pt_path: str = None,
                                accuracy_metric: float = None,
                                notes: str = "") -> dict:
        """注册模型版本"""
        if file_size is None and os.path.isfile(file_path):
            file_size = os.path.getsize(file_path)
        if sha256 is None and os.path.isfile(file_path):
            sha256 = self._compute_file_sha256(file_path)

        mv = self._model_repo.create(
            name=name,
            version=version,
            model_type=model_type,
            scene=scene,
            file_path=file_path,
            sha256=sha256,
            file_size=file_size or 0,
            quantization=quantization,
            onnx_path=onnx_path,
            pt_path=pt_path,
            accuracy_metric=accuracy_metric,
            notes=notes,
        )
        self._log_repo.add("info", f"Model version registered: {name} v{version}")
        return {"status": "success", "model_version": self._mv_to_dict(mv)}

    def list_model_versions(self, scene: str = None,
                            model_type: str = None) -> list[dict]:
        """列出模型版本"""
        mvs = self._model_repo.list_all(scene=scene, model_type=model_type)
        return [self._mv_to_dict(mv) for mv in mvs]

    # ── 工具方法 ────────────────────────────────────────────

    @staticmethod
    def _compute_file_sha256(path: str) -> str:
        """计算文件 SHA256"""
        sha256 = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                sha256.update(chunk)
        return sha256.hexdigest()

    @staticmethod
    def _device_to_dict(device) -> dict:
        """EdgeDevice ORM 转 dict"""
        return {
            "id": device.id,
            "device_id": device.device_id,
            "name": device.name,
            "host": device.host,
            "grpc_port": device.grpc_port,
            "status": device.status,
            "scene": device.scene,
            "model_version": device.model_version,
            "fps": device.fps,
            "npu_usage": device.npu_usage,
            "cpu_temp": device.cpu_temp,
            "memory_bytes": device.memory_bytes,
            "uptime_sec": device.uptime_sec,
            "frame_count": device.frame_count,
            "avg_inference_ms": device.avg_inference_ms,
            "last_heartbeat": device.last_heartbeat.isoformat() if device.last_heartbeat else None,
            "tags": device.tags_json,
            "created_at": device.created_at.isoformat() if device.created_at else None,
        }

    @staticmethod
    def _mv_to_dict(mv) -> dict:
        """ModelVersion ORM 转 dict"""
        return {
            "id": mv.id,
            "name": mv.name,
            "version": mv.version,
            "model_type": mv.model_type,
            "scene": mv.scene,
            "file_path": mv.file_path,
            "sha256": mv.sha256,
            "file_size": mv.file_size,
            "quantization": mv.quantization,
            "accuracy_metric": mv.accuracy_metric,
            "deployed_devices": mv.deployed_devices_json,
            "notes": mv.notes,
            "created_at": mv.created_at.isoformat() if mv.created_at else None,
        }
