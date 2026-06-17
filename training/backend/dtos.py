from __future__ import annotations

from dataclasses import field
from ._compat import slots_dataclass
from pathlib import Path
from typing import Any


@slots_dataclass
class AlgorithmDescriptor:
    key: str
    name: str
    category: str
    modality: str
    entry_type: str
    module_path: str | None = None
    callable_name: str | None = None
    script_path: str | None = None
    input_contract: dict[str, Any] = field(default_factory=dict)
    output_contract: dict[str, Any] = field(default_factory=dict)
    parameters: list[dict[str, Any]] = field(default_factory=list)


@slots_dataclass
class TaskContextRecord:
    task_id: int
    output_dir: Path
    metadata: dict[str, Any] = field(default_factory=dict)
