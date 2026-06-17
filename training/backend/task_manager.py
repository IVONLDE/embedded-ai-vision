from __future__ import annotations

from datetime import datetime, timezone
from dataclasses import field
from ._compat import slots_dataclass
from pathlib import Path

from .errors import NotFoundError, ValidationError


@slots_dataclass
class TaskPluginContext:
    task_id: int
    task_manager: "TaskManager"

    def set_progress(self, progress: float, message: str = "") -> None:
        self.task_manager.set_progress(self.task_id, progress, message)

    def log(self, level: str, message: str, payload: dict | None = None) -> None:
        self.task_manager.log(self.task_id, level, message, payload or {})

    def is_cancel_requested(self) -> bool:
        return self.task_manager.is_cancel_requested(self.task_id)

    @property
    def output_dir(self) -> str:
        return self.task_manager.get_output_dir(self.task_id)


@slots_dataclass
class TaskManager:
    paths: object
    session_factory: object
    task_repository: object
    log_repository: object
    _cancel_flags: dict[int, bool] = field(default_factory=dict)

    def request_cancel(self, task_id: int) -> None:
        self._cancel_flags[task_id] = True

    def cancel(self, task_id: int) -> dict:
        self.request_cancel(task_id)
        with self.session_factory() as session:
            task = self.task_repository.get_task_model(session, task_id)
            if task is None:
                raise NotFoundError(f"Task {task_id} not found.")
            if task.status == "pending":
                task.status = "cancelled"
                task.finished_at = datetime.now(timezone.utc)
                self.task_repository.add_task_log(session, task_id=task_id, level="info", message="Task cancelled before execution")
                session.commit()
                return {"ok": True, "data": {"task_id": task_id, "status": "cancelled"}}

            task.progress_message = "Cancellation requested"
            self.task_repository.add_task_log(session, task_id=task_id, level="warning", message="Cancellation requested")
            session.commit()
        return {"ok": True, "data": {"task_id": task_id, "status": "cancellation_requested"}}

    def is_cancel_requested(self, task_id: int) -> bool:
        return self._cancel_flags.get(task_id, False)

    def clear_cancel(self, task_id: int) -> None:
        self._cancel_flags.pop(task_id, None)

    def start(self, task_id: int) -> dict:
        self.clear_cancel(task_id)
        with self.session_factory() as session:
            task = self.task_repository.get_task_model(session, task_id)
            if task is None:
                raise NotFoundError(f"Task {task_id} not found.")
            if task.status != "pending":
                raise ValidationError(f"Task {task_id} cannot start from status '{task.status}'.")
            task.status = "running"
            task.progress = 0.0
            task.started_at = datetime.now(timezone.utc)
            task.output_dir = str(self.task_output_dir(task.task_type, task.id))
            self.task_repository.add_task_log(session, task_id=task_id, level="info", message="Task started")
            session.commit()
        return {"ok": True, "data": {"task_id": task_id, "status": "running"}}

    def mark_interrupted_tasks(self) -> int:
        return self.task_repository.mark_running_interrupted()

    def get_running_task_ids(self) -> list[int]:
        return self.task_repository.get_running_task_ids()

    def set_progress(self, task_id: int, progress: float, message: str = "") -> None:
        with self.session_factory() as session:
            task = self.task_repository.get_task_model(session, task_id)
            if task is None:
                raise NotFoundError(f"Task {task_id} not found.")
            task.progress = progress
            task.progress_message = message
            session.commit()

    def log(self, task_id: int, level: str, message: str, payload: dict | None = None) -> None:
        with self.session_factory() as session:
            task = self.task_repository.get_task_model(session, task_id)
            if task is None:
                raise NotFoundError(f"Task {task_id} not found.")
            self.task_repository.add_task_log(session, task_id=task_id, level=level, message=message, payload_json=payload or {})
            session.commit()

    def complete(self, task_id: int, result_json: dict | None = None) -> None:
        with self.session_factory() as session:
            task = self.task_repository.get_task_model(session, task_id)
            if task is None:
                raise NotFoundError(f"Task {task_id} not found.")
            if task.status != "running":
                raise ValidationError(f"Task {task_id} cannot complete from status '{task.status}'.")
            task.status = "completed"
            task.progress = 100.0
            task.finished_at = datetime.now(timezone.utc)
            task.result_json = result_json or {}
            self.task_repository.add_task_log(session, task_id=task_id, level="info", message="Task completed")
            session.commit()

    def fail(self, task_id: int, *, error_code: str, error_message: str) -> None:
        with self.session_factory() as session:
            task = self.task_repository.get_task_model(session, task_id)
            if task is None:
                raise NotFoundError(f"Task {task_id} not found.")
            if task.status != "running":
                raise ValidationError(f"Task {task_id} cannot fail from status '{task.status}'.")
            task.status = "cancelled" if error_code == "CANCELLED" else "failed"
            task.error_code = error_code
            task.error_message = error_message
            task.finished_at = datetime.now(timezone.utc)
            self.task_repository.add_task_log(session, task_id=task_id, level="error" if error_code != "CANCELLED" else "warning", message=error_message, payload_json={"error_code": error_code})
            session.commit()

    def build_context(self, task_id: int) -> TaskPluginContext:
        return TaskPluginContext(task_id=task_id, task_manager=self)

    def get_output_dir(self, task_id: int) -> str:
        with self.session_factory() as session:
            task = self.task_repository.get_task_model(session, task_id)
            if task is None:
                raise NotFoundError(f"Task {task_id} not found.")
            return task.output_dir or ""

    def task_output_dir(self, task_type: str, task_id: int) -> Path:
        output_dir = self.paths.tasks_dir / task_type / str(task_id)
        output_dir.mkdir(parents=True, exist_ok=True)
        return output_dir
