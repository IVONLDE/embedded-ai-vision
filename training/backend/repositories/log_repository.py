from __future__ import annotations

from ..models import OperationLog
from .base import RepositoryBase


class LogRepository(RepositoryBase):
    def add(
        self,
        session,
        *,
        level: str,
        action: str,
        resource_type: str | None,
        resource_id: str | None,
        message: str,
        payload_json: dict | None = None,
    ) -> OperationLog:
        entry = OperationLog(
            level=level,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            message=message,
            payload_json=payload_json or {},
        )
        session.add(entry)
        session.flush()
        return entry

    def recent(self, session, *, limit: int):
        return session.query(OperationLog).order_by(OperationLog.created_at.desc(), OperationLog.id.desc()).limit(limit).all()
