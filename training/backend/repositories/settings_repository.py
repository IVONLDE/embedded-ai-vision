from __future__ import annotations

from datetime import datetime, timezone

from ..models import AppSetting, OperationLog
from .base import RepositoryBase


class SettingsRepository(RepositoryBase):

    def get_setting(self, session, key: str):
        return session.query(AppSetting).filter(AppSetting.key == key).first()

    def get_all_settings(self, session) -> list[AppSetting]:
        return session.query(AppSetting).order_by(AppSetting.key.asc()).all()

    def upsert_setting(self, session, key: str, value, description: str = ""):
        setting = session.query(AppSetting).filter(AppSetting.key == key).first()
        if setting:
            setting.value_json = value
            setting.description = description or setting.description
            setting.updated_at = datetime.now(timezone.utc)
        else:
            setting = AppSetting(key=key, value_json=value, description=description)
            session.add(setting)
        return setting

    def add_operation_log(self, session, *, level: str, action: str, resource_type: str = "", resource_id: str = "", message: str, payload_json: dict | None = None):
        log = OperationLog(
            level=level,
            action=action,
            resource_type=resource_type or None,
            resource_id=resource_id or None,
            message=message,
            payload_json=payload_json or {},
        )
        session.add(log)
        return log

    def list_operation_logs(self, session, page: int, page_size: int, resource_type: str = ""):
        query = session.query(OperationLog)
        if resource_type:
            query = query.filter(OperationLog.resource_type == resource_type)
        total = query.count()
        items = (
            query.order_by(OperationLog.created_at.desc(), OperationLog.id.desc())
            .offset(max(page - 1, 0) * page_size)
            .limit(page_size)
            .all()
        )
        return total, items
