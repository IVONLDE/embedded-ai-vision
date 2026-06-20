# SPDX-License-Identifier: MIT
"""
Model Version Repository — 模型版本数据访问层

提供 ModelVersion 表的 CRUD 操作。
"""

from __future__ import annotations

from typing import Optional
from sqlalchemy.orm import Session

from backend.models import ModelVersion


class ModelVersionRepository:
    """模型版本 Repository"""

    def __init__(self, session_factory):
        self._session_factory = session_factory

    def _get_session(self) -> Session:
        return self._session_factory()

    # ── CRUD ─────────────────────────────────────────────

    def create(self, *, name: str, version: str, model_type: str,
               scene: str, file_path: str, sha256: str = None,
               file_size: int = 0, quantization: str = "fp16",
               onnx_path: str = None, pt_path: str = None,
               accuracy_metric: float = None, notes: str = "",
               deployed_devices: list = None) -> ModelVersion:
        """创建模型版本记录"""
        session = self._get_session()
        try:
            mv = ModelVersion(
                name=name,
                version=version,
                model_type=model_type,
                scene=scene,
                file_path=file_path,
                onnx_path=onnx_path,
                pt_path=pt_path,
                sha256=sha256,
                file_size=file_size,
                quantization=quantization,
                accuracy_metric=accuracy_metric,
                deployed_devices_json=deployed_devices or [],
                notes=notes,
            )
            session.add(mv)
            session.commit()
            session.refresh(mv)
            return mv
        finally:
            session.close()

    def get_by_id(self, id: int) -> Optional[ModelVersion]:
        session = self._get_session()
        try:
            return session.query(ModelVersion).filter(ModelVersion.id == id).first()
        finally:
            session.close()

    def list_all(self, scene: str = None, model_type: str = None,
                 status: str = None) -> list[ModelVersion]:
        """列出模型版本, 可按场景/类型/状态过滤"""
        session = self._get_session()
        try:
            query = session.query(ModelVersion)
            if scene:
                query = query.filter(ModelVersion.scene == scene)
            if model_type:
                query = query.filter(ModelVersion.model_type == model_type)
            if status:
                query = query.filter(ModelVersion.status == status)
            return query.order_by(ModelVersion.created_at.desc()).all()
        finally:
            session.close()

    def get_latest(self, scene: str, model_type: str = None) -> Optional[ModelVersion]:
        """获取指定场景的最新模型版本"""
        session = self._get_session()
        try:
            query = session.query(ModelVersion).filter(
                ModelVersion.scene == scene,
                ModelVersion.status == "active",
            )
            if model_type:
                query = query.filter(ModelVersion.model_type == model_type)
            return query.order_by(ModelVersion.created_at.desc()).first()
        finally:
            session.close()

    def update(self, id: int, **kwargs) -> Optional[ModelVersion]:
        session = self._get_session()
        try:
            mv = session.query(ModelVersion).filter(ModelVersion.id == id).first()
            if not mv:
                return None
            updatable = [
                "name", "version", "status", "file_path", "onnx_path",
                "pt_path", "sha256", "file_size", "quantization",
                "accuracy_metric", "deployed_devices_json", "notes",
            ]
            for key, value in kwargs.items():
                if key in updatable:
                    setattr(mv, key, value)
            session.commit()
            session.refresh(mv)
            return mv
        finally:
            session.close()

    def add_deployed_device(self, id: int, device_id: str) -> Optional[ModelVersion]:
        """记录模型已部署到某设备"""
        session = self._get_session()
        try:
            mv = session.query(ModelVersion).filter(ModelVersion.id == id).first()
            if not mv:
                return None
            devices = mv.deployed_devices_json or []
            if device_id not in devices:
                devices.append(device_id)
                mv.deployed_devices_json = devices
                session.commit()
                session.refresh(mv)
            return mv
        finally:
            session.close()

    def delete(self, id: int) -> bool:
        session = self._get_session()
        try:
            mv = session.query(ModelVersion).filter(ModelVersion.id == id).first()
            if not mv:
                return False
            session.delete(mv)
            session.commit()
            return True
        finally:
            session.close()
