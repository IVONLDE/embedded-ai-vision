# SPDX-License-Identifier: MIT
"""
Edge Device Repository — 边缘设备数据访问层

提供 EdgeDevice 表的 CRUD 操作。
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional
from sqlalchemy.orm import Session

from backend.models import EdgeDevice


class EdgeDeviceRepository:
    """边缘设备 Repository"""

    def __init__(self, session_factory):
        self._session_factory = session_factory

    def _get_session(self) -> Session:
        return self._session_factory()

    # ── CRUD ─────────────────────────────────────────────

    def create(self, *, device_id: str, name: str, host: str,
               grpc_port: int = 50051, tags: dict = None) -> EdgeDevice:
        """创建设备记录"""
        session = self._get_session()
        try:
            device = EdgeDevice(
                device_id=device_id,
                name=name,
                host=host,
                grpc_port=grpc_port,
                tags_json=tags or {},
            )
            session.add(device)
            session.commit()
            session.refresh(device)
            return device
        finally:
            session.close()

    def get_by_device_id(self, device_id: str) -> Optional[EdgeDevice]:
        """按 device_id 查询"""
        session = self._get_session()
        try:
            return session.query(EdgeDevice).filter(
                EdgeDevice.device_id == device_id
            ).first()
        finally:
            session.close()

    def get_by_id(self, id: int) -> Optional[EdgeDevice]:
        """按主键查询"""
        session = self._get_session()
        try:
            return session.query(EdgeDevice).filter(EdgeDevice.id == id).first()
        finally:
            session.close()

    def list_all(self, status: str = None) -> list[EdgeDevice]:
        """列出所有设备, 可按状态过滤"""
        session = self._get_session()
        try:
            query = session.query(EdgeDevice)
            if status:
                query = query.filter(EdgeDevice.status == status)
            return query.order_by(EdgeDevice.created_at.desc()).all()
        finally:
            session.close()

    def update(self, device_id: str, **kwargs) -> Optional[EdgeDevice]:
        """更新设备属性"""
        session = self._get_session()
        try:
            device = session.query(EdgeDevice).filter(
                EdgeDevice.device_id == device_id
            ).first()
            if not device:
                return None

            # 允许更新的字段
            updatable = [
                "name", "host", "grpc_port", "status", "scene",
                "model_version", "fps", "npu_usage", "cpu_temp",
                "memory_bytes", "uptime_sec", "frame_count",
                "avg_inference_ms", "last_heartbeat", "tags_json",
            ]
            for key, value in kwargs.items():
                if key in updatable:
                    setattr(device, key, value)

            session.commit()
            session.refresh(device)
            return device
        finally:
            session.close()

    def delete(self, device_id: str) -> bool:
        """删除设备"""
        session = self._get_session()
        try:
            device = session.query(EdgeDevice).filter(
                EdgeDevice.device_id == device_id
            ).first()
            if not device:
                return False
            session.delete(device)
            session.commit()
            return True
        finally:
            session.close()

    def update_heartbeat(self, device_id: str, **telemetry) -> Optional[EdgeDevice]:
        """更新心跳遥测数据"""
        return self.update(device_id, **telemetry, last_heartbeat=datetime.utcnow())

    def set_status(self, device_id: str, status: str) -> Optional[EdgeDevice]:
        """设置设备状态"""
        return self.update(device_id, status=status)

    def set_model_version(self, device_id: str, version: str) -> Optional[EdgeDevice]:
        """设置模型版本"""
        return self.update(device_id, model_version=version)