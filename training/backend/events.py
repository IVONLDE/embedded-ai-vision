from __future__ import annotations

from dataclasses import field
from ._compat import slots_dataclass
from typing import Any


@slots_dataclass
class TaskProgressEvent:
    task_id: int
    progress: float
    message: str = ""


@slots_dataclass
class TaskLogEvent:
    task_id: int
    level: str
    message: str
    payload: dict[str, Any] = field(default_factory=dict)
