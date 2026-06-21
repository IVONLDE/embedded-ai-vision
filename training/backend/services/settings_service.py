from __future__ import annotations

import shutil
from .._compat import slots_dataclass, to_local_isoformat

from .base import ServiceBase


@slots_dataclass
class SettingsService(ServiceBase):
    settings_repository: object
    log_repository: object

    _DEFAULT_SETTINGS = {
        "ui.theme": {"value": "light", "description": "UI theme (light/dark)"},
        "storage.root_dir": {"value": "./data", "description": "Default storage root directory"},
        "task.max_workers": {"value": 2, "description": "Maximum concurrent task workers"},
        "preview.max_samples": {"value": 100, "description": "Maximum preview samples"},
        "log.retention_days": {"value": 30, "description": "Operation log retention days"},
        "mqtt.broker_host": {"value": "debian10.local", "description": "MQTT broker host address"},
        "mqtt.broker_port": {"value": 1883, "description": "MQTT broker port"},
    }

    def get_system_status(self) -> dict:
        data_dir = self.paths.data_dir
        data_dir.mkdir(parents=True, exist_ok=True)
        try:
            disk = shutil.disk_usage(data_dir)
            disk_info = {
                "disk_total_gb": round(disk.total / (1024**3), 1),
                "disk_free_gb": round(disk.free / (1024**3), 1),
                "disk_used_gb": round(disk.used / (1024**3), 1),
                "storage_available": disk.free > 0,
            }
        except Exception:
            disk_info = {"disk_total_gb": 0, "disk_free_gb": 0, "disk_used_gb": 0, "storage_available": False}
        db_exists = self.paths.database_path.exists()
        return {
            "ok": True,
            "data": {
                "database_available": db_exists,
                "storage_dir": str(data_dir),
                **disk_info,
            },
        }

    def get_settings(self) -> dict:
        with self.session_factory() as session:
            items = self.settings_repository.get_all_settings(session)
            return {
                "ok": True,
                "data": {
                    item.key: {"value": item.value_json, "description": item.description}
                    for item in items
                },
            }

    def get_setting(self, key: str):
        with self.session_factory() as session:
            item = self.settings_repository.get_setting(session, key)
            return item.value_json if item else None

    def update_setting(self, key: str, value) -> dict:
        with self.session_factory() as session:
            setting = self.settings_repository.upsert_setting(session, key, value)
            self.log_repository.add(
                session,
                level="info",
                action="update_setting",
                resource_type="app_setting",
                resource_id=key,
                message=f"Updated setting {key}",
            )
            session.commit()
            return {
                "ok": True,
                "data": {"key": setting.key, "value": setting.value_json},
            }

    def ensure_defaults(self) -> None:
        with self.session_factory() as session:
            for key, spec in self._DEFAULT_SETTINGS.items():
                existing = self.settings_repository.get_setting(session, key)
                if existing is None:
                    self.settings_repository.upsert_setting(
                        session, key, spec["value"], spec["description"]
                    )
            session.commit()

    def list_operation_logs(self, page: int, page_size: int, resource_type: str = "") -> dict:
        with self.session_factory() as session:
            total, items = self.settings_repository.list_operation_logs(
                session, page=max(page, 1), page_size=max(page_size, 1), resource_type=resource_type or ""
            )
            return {
                "total": total,
                "items": [
                    {
                        "id": item.id,
                        "level": item.level,
                        "action": item.action,
                        "resource_type": item.resource_type or "",
                        "resource_id": item.resource_id or "",
                        "message": item.message,
                        "created_at": to_local_isoformat(item.created_at),
                    }
                    for item in items
                ],
                "page": max(page, 1),
                "page_size": max(page_size, 1),
            }
