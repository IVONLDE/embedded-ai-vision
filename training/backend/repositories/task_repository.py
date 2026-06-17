from __future__ import annotations

from datetime import datetime, timezone

import shutil
from pathlib import Path

from .._compat import to_local_isoformat
from ..models import Task, TaskLog, CleaningSuggestion, GenerationOutput, EvaluationResult
from ..models import Dataset
from .base import RepositoryBase


class TaskRepository(RepositoryBase):
    def create_task(self, session, **values) -> Task:
        task = Task(**values)
        session.add(task)
        session.flush()
        return task

    def get_task_model(self, session, task_id: int) -> Task | None:
        return session.query(Task).filter(Task.id == task_id).first()

    def get_task(self, task_id: int) -> dict | None:
        with self.session_factory() as session:
            task = self.get_task_model(session, task_id)
            return self._serialize_task(task, session=session) if task else None

    def list_tasks(self, *, task_type: str, status: str, page: int, page_size: int) -> dict:
        with self.session_factory() as session:
            query = session.query(Task)
            if task_type:
                query = query.filter(Task.task_type == task_type)
            if status:
                query = query.filter(Task.status == status)
            total = query.count()
            items = (
                query.order_by(Task.created_at.desc(), Task.id.desc())
                .offset(max(page - 1, 0) * page_size)
                .limit(page_size)
                .all()
            )
            return {
                "total": total,
                "items": [self._serialize_task(item, session=session) for item in items],
                "page": max(page, 1),
                "page_size": max(page_size, 1),
            }

    def add_task_log(self, session, *, task_id: int, level: str, message: str, payload_json: dict | None = None) -> TaskLog:
        row = TaskLog(task_id=task_id, level=level, message=message, payload_json=payload_json or {})
        session.add(row)
        session.flush()
        return row

    def list_task_logs(self, task_id: int, page: int, page_size: int) -> dict:
        with self.session_factory() as session:
            query = session.query(TaskLog).filter(TaskLog.task_id == task_id)
            total = query.count()
            items = (
                query.order_by(TaskLog.created_at.asc(), TaskLog.id.asc())
                .offset(max(page - 1, 0) * page_size)
                .limit(page_size)
                .all()
            )
            return {
                "total": total,
                "items": [
                    {
                        "id": item.id,
                        "task_id": item.task_id,
                        "level": item.level,
                        "message": item.message,
                        "payload_json": item.payload_json,
                        "created_at": to_local_isoformat(item.created_at),
                    }
                    for item in items
                ],
                "page": max(page, 1),
                "page_size": max(page_size, 1),
            }

    def mark_running_interrupted(self) -> int:
        changed = 0
        with self.session_factory() as session:
            rows = session.query(Task).filter(Task.status == "running").all()
            now = datetime.now(timezone.utc)
            for row in rows:
                row.status = "interrupted"
                row.finished_at = now
                changed += 1
                self.add_task_log(session, task_id=row.id, level="warning", message="Task marked interrupted on manager sweep")
            session.commit()
        return changed

    def delete_task(self, session, task_id: int) -> dict | None:
        task = self.get_task_model(session, task_id)
        if task is None:
            return None
        task_info = self._serialize_task(task, session=session)

        session.query(CleaningSuggestion).filter(CleaningSuggestion.task_id == task_id).delete()
        session.query(GenerationOutput).filter(GenerationOutput.task_id == task_id).delete()
        session.query(EvaluationResult).filter(EvaluationResult.task_id == task_id).delete()
        session.query(TaskLog).filter(TaskLog.task_id == task_id).delete()
        session.delete(task)

        output_dir = task_info.get("output_dir", "")
        if output_dir:
            path = Path(output_dir)
            if path.exists():
                shutil.rmtree(path)

        return task_info

    def update_task_title(self, session, task_id: int, title: str) -> Task | None:
        task = self.get_task_model(session, task_id)
        if task is None:
            return None
        task.title = title
        session.flush()
        return task

    def get_running_task_ids(self) -> list[int]:
        with self.session_factory() as session:
            rows = session.query(Task.id).filter(Task.status == "running").all()
            return [row[0] for row in rows]

    def _serialize_task(self, task: Task, session=None) -> dict:
        source_dataset = self._dataset_payload(session, task.source_dataset_id)
        target_dataset = self._dataset_payload(session, task.target_dataset_id)
        return {
            "id": task.id,
            "task_type": task.task_type,
            "status": task.status,
            "title": task.title,
            "source_dataset_id": task.source_dataset_id,
            "target_dataset_id": task.target_dataset_id,
            "source_dataset_name": source_dataset.get("name", ""),
            "source_dataset_path": source_dataset.get("storage_path", ""),
            "target_dataset_name": target_dataset.get("name", ""),
            "target_dataset_path": target_dataset.get("storage_path", ""),
            "algorithm_id": task.algorithm_id,
            "progress": task.progress,
            "progress_message": task.progress_message,
            "parameters_json": task.parameters_json,
            "payload_json": task.payload_json,
            "result_json": task.result_json,
            "error_message": task.error_message or "",
            "output_dir": task.output_dir or "",
            "created_at": to_local_isoformat(task.created_at),
        }

    def _dataset_payload(self, session, dataset_id: int | None) -> dict:
        if session is None or not dataset_id:
            return {}
        dataset = session.query(Dataset).filter(Dataset.id == dataset_id).first()
        if dataset is None:
            return {}
        return {"name": dataset.name, "storage_path": dataset.storage_path}
