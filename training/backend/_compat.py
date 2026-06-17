from __future__ import annotations

from datetime import datetime, timezone, timedelta
from dataclasses import dataclass


# 中国标准时间 (UTC+8)
_CHINA_TZ = timezone(timedelta(hours=8))


def to_local_isoformat(dt: datetime | None) -> str:
    """将 UTC naive datetime (SQLite存储) 转换为本地时间 ISO 格式字符串。

    SQLite 的 func.now() 存储的是 UTC 时间，但 SQLAlchemy 读取时
    丢失了时区信息（naive datetime）。此函数将 naive datetime 解释
    为 UTC，然后转换为中国标准时间 (UTC+8) 输出。
    """
    if dt is None:
        return ""
    if dt.tzinfo is None:
        # SQLite 存储的 naive datetime，实际为 UTC
        dt = dt.replace(tzinfo=timezone.utc)
    # 统一转为中国标准时间
    local_dt = dt.astimezone(_CHINA_TZ)
    return local_dt.strftime("%Y-%m-%d %H:%M:%S")


def build_slots_dataclass(dataclass_fn=dataclass):
    def decorator(cls=None, **kwargs):
        def wrap(inner_cls):
            try:
                return dataclass_fn(inner_cls, slots=True, **kwargs)
            except TypeError as exc:
                if "slots" not in str(exc):
                    raise
                return dataclass_fn(inner_cls, **kwargs)

        if cls is None:
            return wrap
        return wrap(cls)

    return decorator


slots_dataclass = build_slots_dataclass()
