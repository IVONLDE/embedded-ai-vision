"""
Model Export Service — 模型导出与版本管理

功能:
  - PyTorch → ONNX → RKNN 导出
  - 模型版本注册与查询
  - 导出历史记录
"""

from __future__ import annotations

import os
import hashlib
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional


@dataclass
class ExportResult:
    """导出结果"""
    model_name: str = ""
    version: str = ""
    rknn_path: str = ""
    onnx_path: str = ""
    pt_path: str = ""
    sha256: str = ""
    file_size: int = 0
    quantization: str = "fp16"
    duration_sec: float = 0.0
    status: str = "success"  # success / failed
    error_message: str = ""


class ExportService:
    """
    模型导出服务

    用法:
        svc = ExportService(paths=paths, session_factory=sf, ...)
        result = svc.export_model("yolov5n.pt", "yolov5n.rknn", "yolov5", "vehicle")
        versions = svc.list_versions("vehicle")
    """

    def __init__(self, *, paths, session_factory,
                 algorithm_repository, log_repository):
        self._paths = paths
        self._session_factory = session_factory
        self._algorithm_repo = algorithm_repository
        self._log_repo = log_repository

    # ── 模型导出 ──────────────────────────────────────────
    def export_model(self, pt_path: str, output_name: str,
                     model_type: str = "yolov5",
                     scene: str = "vehicle",
                     quantize: bool = False,
                     calib_dir: str = None) -> dict:
        """
        导出 PyTorch 模型为 RKNN 格式

        @param pt_path:      PyTorch 模型路径 (.pt)
        @param output_name:  输出文件名 (不含扩展名)
        @param model_type:   yolov5 / osnet / classifier
        @param scene:        face / body / vehicle / defect
        @param quantize:     是否 INT8 量化
        @param calib_dir:    校准图片目录
        @return: {"status": "success", "data": {...}}
        """
        if not os.path.exists(pt_path):
            return {"status": "error", "message": f"Model file not found: {pt_path}"}

        start_time = time.time()

        try:
            # 调用 RKNN-Toolkit1 导出脚本
            import sys
            scripts_dir = os.path.normpath(
                os.path.join(os.path.dirname(__file__), "..", "..", "scripts")
            )
            if scripts_dir not in sys.path:
                sys.path.insert(0, scripts_dir)
            from export_to_rknn1 import (
                export_onnx_yolov5, export_onnx_osnet, export_rknn
            )

            models_dir = os.path.join(self._paths.root, "data", "models")
            os.makedirs(models_dir, exist_ok=True)

            onnx_path = os.path.join(models_dir, f"{output_name}.onnx")
            rknn_path = os.path.join(models_dir, f"{output_name}.rknn")

            # Step 1: PyTorch → ONNX
            if model_type == "yolov5":
                export_onnx_yolov5(pt_path, onnx_path)
            elif model_type == "osnet":
                export_onnx_osnet(pt_path, onnx_path)
            else:
                return {"status": "error", "message": f"Unknown model type: {model_type}"}

            # Step 2: ONNX → RKNN
            export_rknn(onnx_path, rknn_path,
                        quantize=quantize, calib_dir=calib_dir,
                        target_platform="rk3399pro")

            # 计算 SHA256
            sha256 = self._compute_sha256(rknn_path)
            file_size = os.path.getsize(rknn_path)
            duration = time.time() - start_time

            result = ExportResult(
                model_name=output_name,
                version=time.strftime("%Y%m%d_%H%M%S"),
                rknn_path=rknn_path,
                onnx_path=onnx_path,
                pt_path=pt_path,
                sha256=sha256,
                file_size=file_size,
                quantization="int8" if quantize else "fp16",
                duration_sec=duration,
            )

            print(f"[ExportService] Model exported: {rknn_path} "
                  f"({file_size} bytes, {duration:.1f}s)")

            return {
                "status": "success",
                "data": {
                    "rknn_path": rknn_path,
                    "onnx_path": onnx_path,
                    "sha256": sha256,
                    "file_size": file_size,
                    "duration_sec": round(duration, 1),
                    "quantization": result.quantization,
                }
            }

        except Exception as e:
            duration = time.time() - start_time
            print(f"[ExportService] Export failed: {e}")
            return {
                "status": "error",
                "message": str(e),
                "duration_sec": round(duration, 1),
            }

    # ── 版本管理 ──────────────────────────────────────────
    def list_versions(self, scene: str = None) -> List[dict]:
        """列出模型版本"""
        models_dir = os.path.join(self._paths.root, "data", "models")
        if not os.path.exists(models_dir):
            return []

        versions = []
        for fname in os.listdir(models_dir):
            if fname.endswith(".rknn"):
                fpath = os.path.join(models_dir, fname)
                versions.append({
                    "name": fname,
                    "path": fpath,
                    "size": os.path.getsize(fpath),
                    "modified": os.path.getmtime(fpath),
                })

        versions.sort(key=lambda v: v["modified"], reverse=True)
        return versions

    def get_latest_model(self, scene: str = None) -> Optional[dict]:
        """获取最新模型"""
        versions = self.list_versions(scene)
        return versions[0] if versions else None

    # ── 辅助 ──────────────────────────────────────────────
    @staticmethod
    def _compute_sha256(file_path: str) -> str:
        """计算文件 SHA256"""
        sha = hashlib.sha256()
        with open(file_path, "rb") as f:
            while True:
                chunk = f.read(8192)
                if not chunk:
                    break
                sha.update(chunk)
        return sha.hexdigest()
