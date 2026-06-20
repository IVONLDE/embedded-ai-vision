# SPDX-License-Identifier: MIT
"""
Edge Device RPC Client — 边缘设备通信客户端

通信方式 (按优先级):
  1. gRPC 直连 (高性能, 推荐生产环境)
  2. SSH + JSON-RPC (兼容模式, 开发调试用)

用法:
    from backend.edge_client import EdgeClient

    client = EdgeClient("192.168.1.50", grpc_port=50051)
    status = client.get_status()
    client.switch_scene("vehicle")
    client.push_model("/path/to/model.rknn", model_version="v2.0")
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import subprocess
import time
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class DeviceStatus:
    """边缘设备运行状态"""
    device_id: str = ""
    scene: str = ""
    model: str = ""
    model_version: str = ""
    status: str = "unknown"
    fps: float = 0.0
    npu_usage: float = 0.0
    cpu_temp: float = 0.0
    memory_bytes: int = 0
    uptime_sec: int = 0
    frame_count: int = 0
    avg_inference_ms: float = 0.0
    app_version: str = ""
    rollback_available: bool = False
    raw: dict = None

    @classmethod
    def from_response(cls, data: dict) -> "DeviceStatus":
        return cls(
            device_id=data.get("device_id", ""),
            scene=data.get("scene", ""),
            model=data.get("model", ""),
            model_version=data.get("model_version", ""),
            status=data.get("status", "unknown"),
            fps=data.get("fps", 0.0),
            npu_usage=data.get("npu_usage", 0.0),
            cpu_temp=data.get("cpu_temp", 0.0),
            memory_bytes=data.get("memory_bytes", 0),
            uptime_sec=data.get("uptime_sec", 0),
            frame_count=data.get("frame_count", 0),
            avg_inference_ms=data.get("avg_inference_ms", 0.0),
            app_version=data.get("app_version", ""),
            rollback_available=data.get("rollback_available", False),
            raw=data,
        )


@dataclass
class OtaResult:
    """OTA 操作结果"""
    status: int = -1         # 0=成功, -1=失败, 2=需重启
    message: str = ""
    version: str = ""
    previous_version: str = ""
    needs_restart: bool = False


class EdgeClient:
    """
    边缘设备通信客户端

    支持 gRPC 直连和 SSH+JSON-RPC 两种模式。
    """

    def __init__(self, host: str, ssh_user: str = "root",
                 grpc_port: int = 50051,
                 socket_path: str = "/tmp/edge-ai-grpc.sock",
                 ssh_timeout: int = 10,
                 use_grpc: bool = False):
        """
        Args:
            host: 设备 IP 地址
            ssh_user: SSH 用户名
            grpc_port: gRPC 端口
            socket_path: UNIX socket 路径
            ssh_timeout: SSH 连接超时(秒)
            use_grpc: 是否尝试 gRPC 直连
        """
        self._host = host
        self._ssh_user = ssh_user
        self._grpc_port = grpc_port
        self._socket_path = socket_path
        self._ssh_timeout = ssh_timeout
        self._use_grpc = use_grpc
        self._grpc_channel = None

    # ── gRPC 直连 (可选) ──────────────────────────────────
    def _init_grpc(self):
        """初始化 gRPC 通道 (需要 grpcio 库)"""
        if self._grpc_channel:
            return True
        try:
            import grpc
            target = f"{self._host}:{self._grpc_port}"
            self._grpc_channel = grpc.insecure_channel(target)
            # 尝试连接
            grpc.channel_ready_future(self._grpc_channel).result(timeout=5)
            return True
        except Exception:
            self._grpc_channel = None
            return False

    # ── SSH + JSON-RPC 通信 ─────────────────────────────────
    def _call(self, method: str, params: dict = None) -> dict:
        """通过 SSH 发送 JSON-RPC 请求到边缘设备"""
        request = {
            "method": method,
            "params": params or {},
        }
        json_str = json.dumps(request, ensure_ascii=False)

        cmd = [
            "ssh",
            "-o", f"ConnectTimeout={self._ssh_timeout}",
            "-o", "StrictHostKeyChecking=no",
            "-o", "BatchMode=no",
            f"{self._ssh_user}@{self._host}",
            f"echo '{json_str.replace(chr(39), chr(39) + chr(92) + chr(39))}' | nc -U {self._socket_path} -W 5",
        ]

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self._ssh_timeout + 5,
            )

            if result.returncode != 0:
                stderr = result.stderr.strip()
                return {
                    "status": -1,
                    "message": f"SSH error: {stderr}" if stderr else "SSH connection failed",
                }

            raw_response = result.stdout.strip()
            if not raw_response:
                return {"status": -1, "message": "Empty response from device"}

            try:
                return json.loads(raw_response)
            except json.JSONDecodeError:
                return {"status": -1, "message": f"Invalid JSON: {raw_response[:200]}"}

        except subprocess.TimeoutExpired:
            return {"status": -1, "message": f"Connection to {self._host} timed out"}
        except FileNotFoundError:
            return {"status": -1, "message": "SSH client (ssh) not found"}
        except Exception as e:
            return {"status": -1, "message": str(e)}

    def _scp(self, local_path: str, remote_path: str) -> dict:
        """SCP 文件传输"""
        try:
            result = subprocess.run(
                [
                    "scp",
                    "-o", f"ConnectTimeout={self._ssh_timeout}",
                    "-o", "StrictHostKeyChecking=no",
                    local_path,
                    f"{self._ssh_user}@{self._host}:{remote_path}",
                ],
                capture_output=True,
                text=True,
                timeout=self._ssh_timeout + 30,
            )
            if result.returncode != 0:
                return {"status": -1, "message": f"SCP failed: {result.stderr.strip()[:200]}"}
            return {"status": 0, "message": "ok"}
        except subprocess.TimeoutExpired:
            return {"status": -1, "message": "SCP timed out"}
        except Exception as e:
            return {"status": -1, "message": f"SCP error: {e}"}

    # ── GetStatus ──────────────────────────────────────────
    def get_status(self) -> DeviceStatus:
        """查询边缘设备运行状态"""
        resp = self._call("GetStatus")
        if resp.get("status") == 0:
            return DeviceStatus.from_response(resp)
        return DeviceStatus(status="error", raw=resp)

    # ── GetVersionInfo (OTA) ───────────────────────────────
    def get_version_info(self) -> dict:
        """查询设备版本信息 (OTA)"""
        return self._call("GetVersionInfo")

    # ── SwitchScene ────────────────────────────────────────
    def switch_scene(self, scene_name: str) -> dict:
        """切换推理场景"""
        valid_scenes = {"face", "body", "vehicle", "defect"}
        if scene_name not in valid_scenes:
            return {"status": -1, "message": f"Invalid scene: {scene_name}"}
        return self._call("SwitchScene", {"scene_name": scene_name})

    # ── PushModel ─────────────────────────────────────────
    def push_model(self, model_path: str, model_name: str = None,
                   model_version: str = None,
                   sha256_checksum: str = None,
                   auto_rollback: bool = True) -> dict:
        """
        推送模型到边缘设备 (SCP + JSON-RPC)

        流程:
          1. SCP 拷贝模型文件到设备临时目录
          2. JSON-RPC 通知设备安装模型 (校验+备份+替换+热加载)

        Args:
            model_path: 本地模型文件路径
            model_name: 设备上的模型名称 (默认使用文件名)
            model_version: 模型版本号
            sha256_checksum: SHA256 校验和 (默认自动计算)
            auto_rollback: 失败时自动回滚
        """
        if not os.path.isfile(model_path):
            return {"status": -1, "message": f"Model file not found: {model_path}"}

        if model_name is None:
            model_name = os.path.basename(model_path)

        # 自动计算 SHA256
        if sha256_checksum is None:
            sha256_checksum = self._compute_file_sha256(model_path)

        # Step 1: SCP 拷贝到设备临时目录
        remote_path = f"/opt/edge-ai/models/.ota_tmp/{model_name}"
        scp_result = self._scp(model_path, remote_path)
        if scp_result.get("status") != 0:
            return scp_result

        # Step 2: JSON-RPC 通知设备安装
        return self._call("PushModel", {
            "model_name": model_name,
            "model_path": remote_path,
            "model_version": model_version or "",
            "sha256": sha256_checksum,
            "auto_rollback": auto_rollback,
        })

    def push_model_inline(self, model_path: str, model_name: str = None) -> dict:
        """
        推送模型 (base64 内联传输, 适合小模型 <10MB)
        """
        if not os.path.isfile(model_path):
            return {"status": -1, "message": f"Model file not found: {model_path}"}

        file_size = os.path.getsize(model_path)
        max_size = 10 * 1024 * 1024
        if file_size > max_size:
            return {
                "status": -1,
                "message": f"Model too large for inline push: {file_size} bytes "
                           f"(max {max_size}). Use push_model() for SCP transfer.",
            }

        if model_name is None:
            model_name = os.path.basename(model_path)

        with open(model_path, "rb") as f:
            model_data = f.read()

        model_b64 = base64.b64encode(model_data).decode("ascii")

        return self._call("PushModel", {
            "model_name": model_name,
            "model_data": model_b64,
        })

    # ── AppUpdate (OTA) ────────────────────────────────────
    def push_app_update(self, app_path: str, app_version: str,
                        sha256_checksum: str = None,
                        auto_rollback: bool = True) -> dict:
        """
        推送应用更新到边缘设备

        Args:
            app_path: 本地应用二进制文件路径
            app_version: 新版本号
            sha256_checksum: SHA256 校验和
            auto_rollback: 失败时自动回滚
        """
        if not os.path.isfile(app_path):
            return {"status": -1, "message": f"App file not found: {app_path}"}

        if sha256_checksum is None:
            sha256_checksum = self._compute_file_sha256(app_path)

        # SCP 拷贝到设备临时目录
        remote_path = "/opt/edge-ai/.ota_tmp/edge-ai-camera"
        scp_result = self._scp(app_path, remote_path)
        if scp_result.get("status") != 0:
            return scp_result

        return self._call("PushAppUpdate", {
            "app_path": remote_path,
            "app_version": app_version,
            "sha256": sha256_checksum,
            "auto_rollback": auto_rollback,
        })

    # ── Rollback (OTA) ─────────────────────────────────────
    def rollback(self, target: str = "model") -> dict:
        """
        回滚到上一版本

        Args:
            target: "model" 或 "app"
        """
        return self._call("Rollback", {"target": target})

    # ── UpdateConfig ───────────────────────────────────────
    def update_config(self, params: dict) -> dict:
        """更新运行时配置参数"""
        return self._call("UpdateConfig", params)

    # ── Restart ────────────────────────────────────────────
    def restart(self) -> dict:
        """远程重启边缘设备推理服务"""
        return self._call("Restart")

    # ── 工具方法 ────────────────────────────────────────────

    @staticmethod
    def _compute_file_sha256(path: str) -> str:
        """计算文件 SHA256"""
        sha256 = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                sha256.update(chunk)
        return sha256.hexdigest()


# ── CLI 入口 ──────────────────────────────────────────────
if __name__ == "__main__":
    import sys

    if len(sys.argv) < 3:
        print("Usage: python edge_client.py <host> <command> [args...]")
        print()
        print("Commands:")
        print("  status                                    Query device status")
        print("  version                                   Query version info (OTA)")
        print("  scene <name>                              Switch scene")
        print("  push <model_path> [model_name]            Push model (SCP)")
        print("  push-app <app_path> <version>             Push app update (OTA)")
        print("  rollback [model|app]                      Rollback to previous version")
        print("  config <key>=<value> [<key>=<value>...]   Update config")
        print("  restart                                   Restart inference service")
        sys.exit(1)

    host = sys.argv[1]
    command = sys.argv[2]
    client = EdgeClient(host)

    if command == "status":
        status = client.get_status()
        print(f"Device:    {status.device_id}")
        print(f"Status:    {status.status}")
        print(f"Scene:     {status.scene}")
        print(f"Model:     {status.model}")
        print(f"Version:   {status.model_version}")
        print(f"App:       {status.app_version}")
        print(f"FPS:       {status.fps}")
        print(f"NPU:       {status.npu_usage}%")
        print(f"CPU Temp:  {status.cpu_temp}°C")
        print(f"Rollback:  {'available' if status.rollback_available else 'none'}")

    elif command == "version":
        info = client.get_version_info()
        print(json.dumps(info, indent=2))

    elif command == "scene":
        if len(sys.argv) < 4:
            print("Usage: python edge_client.py <host> scene <name>")
            sys.exit(1)
        resp = client.switch_scene(sys.argv[3])
        print(json.dumps(resp, indent=2))

    elif command == "push":
        if len(sys.argv) < 4:
            print("Usage: python edge_client.py <host> push <model_path>")
            sys.exit(1)
        model_path = sys.argv[3]
        model_name = sys.argv[4] if len(sys.argv) > 4 else None
        print(f"Pushing model: {model_path}...")
        resp = client.push_model(model_path, model_name)
        print(json.dumps(resp, indent=2))

    elif command == "push-app":
        if len(sys.argv) < 5:
            print("Usage: python edge_client.py <host> push-app <app_path> <version>")
            sys.exit(1)
        app_path = sys.argv[3]
        version = sys.argv[4]
        print(f"Pushing app: {app_path} v{version}...")
        resp = client.push_app_update(app_path, version)
        print(json.dumps(resp, indent=2))

    elif command == "rollback":
        target = sys.argv[3] if len(sys.argv) > 3 else "model"
        print(f"Rolling back {target}...")
        resp = client.rollback(target)
        print(json.dumps(resp, indent=2))

    elif command == "config":
        if len(sys.argv) < 4:
            print("Usage: python edge_client.py <host> config <key>=<value>...")
            sys.exit(1)
        params = {}
        for arg in sys.argv[3:]:
            if "=" in arg:
                k, v = arg.split("=", 1)
                try:
                    v = float(v) if "." in v else int(v)
                except ValueError:
                    pass
                params[k] = v
        resp = client.update_config(params)
        print(json.dumps(resp, indent=2))

    elif command == "restart":
        print(f"Restarting device {host}...")
        resp = client.restart()
        print(json.dumps(resp, indent=2))
        print("Note: Device will be unavailable for ~5-10 seconds.")

    else:
        print(f"Unknown command: {command}")
        sys.exit(1)
