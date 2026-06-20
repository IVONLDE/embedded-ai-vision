# SPDX-License-Identifier: MIT
"""
Edge Device RPC Client — 边缘设备通信客户端

通过 SSH + UNIX Domain Socket 与边缘设备的 gRPC/JSON-RPC 服务通信。

协议:
  - 边缘设备: edge/src/comm/grpc_server.cpp (JSON-RPC over UNIX socket)
  - PC 端通过 SSH 隧道访问边缘设备的 UNIX socket

用法:
    from backend.edge_client import EdgeClient

    client = EdgeClient("192.168.1.50", ssh_user="root")
    status = client.get_status()
    client.switch_scene("vehicle")
    client.push_model("/path/to/model.rknn")
"""

from __future__ import annotations

import base64
import json
import subprocess
import time
from dataclasses import dataclass
from typing import Optional


@dataclass
class DeviceStatus:
    """边缘设备运行状态"""
    device_id: str = ""
    scene: str = ""
    model: str = ""
    status: str = "unknown"
    conf_threshold: float = 0.3
    nms_threshold: float = 0.45
    mqtt_enabled: bool = False
    grpc_enabled: bool = False
    raw: dict = None

    @classmethod
    def from_response(cls, data: dict) -> "DeviceStatus":
        device = data.get("device", {})
        return cls(
            device_id=device.get("device_id", ""),
            scene=device.get("scene", ""),
            model=device.get("model", ""),
            status=device.get("status", "unknown"),
            conf_threshold=device.get("conf_threshold", 0.3),
            nms_threshold=device.get("nms_threshold", 0.45),
            mqtt_enabled=device.get("mqtt_enabled", False),
            grpc_enabled=device.get("grpc_enabled", False),
            raw=device,
        )


class EdgeClient:
    """
    边缘设备 JSON-RPC 客户端

    通过 SSH 连接边缘设备，发送 JSON-RPC 请求到 UNIX socket。

    支持的 RPC 方法:
      - PushModel:    推送模型文件
      - SwitchScene:  切换推理场景
      - GetStatus:    查询设备状态
      - UpdateConfig: 更新运行时参数
      - Restart:      远程重启
    """

    def __init__(self, host: str, ssh_user: str = "root",
                 socket_path: str = "/tmp/edge-ai-grpc.sock",
                 ssh_timeout: int = 10):
        self._host = host
        self._ssh_user = ssh_user
        self._socket_path = socket_path
        self._ssh_timeout = ssh_timeout

    # ── 发送 JSON-RPC 请求 ─────────────────────────────────
    def _call(self, method: str, params: dict = None) -> dict:
        """
        通过 SSH 发送 JSON-RPC 请求到边缘设备 UNIX socket。

        命令:
          echo '<json>' | nc -U /tmp/edge-ai-grpc.sock -W 5
        """
        request = {
            "method": method,
            "params": params or {},
        }
        json_str = json.dumps(request, ensure_ascii=False)

        # 通过 SSH 执行 nc 连接到 UNIX socket
        cmd = [
            "ssh",
            "-o", "ConnectTimeout={}".format(self._ssh_timeout),
            "-o", "StrictHostKeyChecking=no",
            "-o", "BatchMode=no",
            "{}@{}".format(self._ssh_user, self._host),
            "echo '{}' | nc -U {} -W 5".format(
                json_str.replace("'", "'\\''"),
                self._socket_path,
            ),
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

    # ── GetStatus ──────────────────────────────────────────
    def get_status(self) -> DeviceStatus:
        """查询边缘设备运行状态"""
        resp = self._call("GetStatus")
        if resp.get("status") == 0:
            return DeviceStatus.from_response(resp)
        return DeviceStatus(status="error", raw=resp)

    # ── SwitchScene ────────────────────────────────────────
    def switch_scene(self, scene_name: str) -> dict:
        """
        切换推理场景

        Args:
            scene_name: 场景名称 (face / body / vehicle / defect)

        Returns:
            {"status": 0, "message": "ok"} 或 {"status": -1, "message": "..."}
        """
        valid_scenes = {"face", "body", "vehicle", "defect"}
        if scene_name not in valid_scenes:
            return {"status": -1, "message": f"Invalid scene: {scene_name}"}

        return self._call("SwitchScene", {"scene_name": scene_name})

    # ── PushModel ─────────────────────────────────────────
    def push_model(self, model_path: str, model_name: str = None) -> dict:
        """
        推送模型文件到边缘设备 (通过 SCP + JSON-RPC)

        分两步:
          1. SCP 拷贝模型文件到设备
          2. JSON-RPC 通知设备热加载

        Args:
            model_path: 本地模型文件路径
            model_name: 设备上的模型名称 (默认使用文件名)

        Returns:
            {"status": 0, "message": "ok"} 或错误信息
        """
        import os

        if not os.path.isfile(model_path):
            return {"status": -1, "message": f"Model file not found: {model_path}"}

        if model_name is None:
            model_name = os.path.basename(model_path)

        # Step 1: SCP 拷贝
        remote_path = f"/opt/edge-ai/models/{model_name}"
        try:
            scp_result = subprocess.run(
                [
                    "scp",
                    "-o", "ConnectTimeout={}".format(self._ssh_timeout),
                    "-o", "StrictHostKeyChecking=no",
                    model_path,
                    "{}@{}:{}".format(self._ssh_user, self._host, remote_path),
                ],
                capture_output=True,
                text=True,
                timeout=self._ssh_timeout + 30,
            )
            if scp_result.returncode != 0:
                return {
                    "status": -1,
                    "message": f"SCP failed: {scp_result.stderr.strip()[:200]}",
                }
        except subprocess.TimeoutExpired:
            return {"status": -1, "message": "SCP timed out"}
        except Exception as e:
            return {"status": -1, "message": f"SCP error: {e}"}

        # Step 2: 通知设备热加载
        return self._call("PushModel", {"model_name": model_name})

    def push_model_inline(self, model_path: str, model_name: str = None) -> dict:
        """
        推送模型文件到边缘设备 (base64 内联传输)

        将模型文件编码为 base64 后通过 JSON-RPC 直接传输。
        适合小模型 (<10MB)，避免 SCP 的两步操作。

        注意: 大模型应使用 push_model() (SCP 方式)。
        """
        import os

        if not os.path.isfile(model_path):
            return {"status": -1, "message": f"Model file not found: {model_path}"}

        file_size = os.path.getsize(model_path)
        max_size = 10 * 1024 * 1024  # 10MB
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

    # ── UpdateConfig ───────────────────────────────────────
    def update_config(self, params: dict) -> dict:
        """
        更新运行时配置参数

        Args:
            params: 配置键值对 (如 {"conf_threshold": 0.5, "nms_threshold": 0.3})

        Returns:
            {"status": 0, "message": "config updated"}
        """
        return self._call("UpdateConfig", params)

    # ── Restart ────────────────────────────────────────────
    def restart(self) -> dict:
        """
        远程重启边缘设备推理服务

        注意: 此操作会中断推理服务 ~5-10 秒。
        systemd 会自动重启进程。
        """
        return self._call("Restart")


# ── CLI 入口 (用于脚本直接调用) ──────────────────────────
if __name__ == "__main__":
    import sys

    if len(sys.argv) < 3:
        print("Usage: python edge_client.py <host> <command> [args...]")
        print()
        print("Commands:")
        print("  status                                    Query device status")
        print("  scene <name>                              Switch scene (face/body/vehicle/defect)")
        print("  push <model_path> [model_name]            Push model (SCP)")
        print("  config <key>=<value> [<key>=<value>...]   Update config")
        print("  restart                                   Restart inference service")
        print()
        print("Example:")
        print("  python edge_client.py 192.168.1.50 status")
        print("  python edge_client.py 192.168.1.50 scene vehicle")
        print("  python edge_client.py 192.168.1.50 push yolov5n.rknn")
        sys.exit(1)

    host = sys.argv[1]
    command = sys.argv[2]
    client = EdgeClient(host)

    if command == "status":
        status = client.get_status()
        print(f"Device: {status.device_id}")
        print(f"Status: {status.status}")
        print(f"Scene:  {status.scene}")
        print(f"Model:  {status.model}")
        print(f"Conf threshold: {status.conf_threshold}")
        print(f"NMS threshold:  {status.nms_threshold}")
        print(f"MQTT:   {status.mqtt_enabled}")
        print(f"gRPC:   {status.grpc_enabled}")

    elif command == "scene":
        if len(sys.argv) < 4:
            print("Usage: python edge_client.py <host> scene <name>")
            sys.exit(1)
        scene_name = sys.argv[3]
        resp = client.switch_scene(scene_name)
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