from __future__ import annotations

from typing import Any, Protocol


class PluginContext(Protocol):
    def set_progress(self, progress: float, message: str = "") -> None:
        ...

    def log(self, level: str, message: str, payload: dict[str, Any] | None = None) -> None:
        ...

    def is_cancel_requested(self) -> bool:
        ...


class AlgorithmPlugin(Protocol):
    def run(self, payload: dict[str, Any], context: PluginContext) -> dict[str, Any]:
        ...
