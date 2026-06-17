from __future__ import annotations

from dataclasses import field
from .._compat import slots_dataclass
from pathlib import Path

from ..models import Algorithm, CleaningSuggestion, Dataset, Sample
from ..plugins import PluginRunner
from ..errors import NotFoundError, ValidationError
from ..storage import FileIndexer
from .base import ServiceBase
from .sample_ordering import interleave_by_top_folder


@slots_dataclass
class CleaningService(ServiceBase):
    task_manager: object
    task_repository: object
    algorithm_repository: object
    dataset_repository: object
    plugin_runner: PluginRunner = PluginRunner()
    file_indexer: FileIndexer = field(default_factory=FileIndexer)
    _SUGGESTION_STATUS_MAP = {
        "approve": "approved",
        "approved": "approved",
        "reject": "rejected",
        "rejected": "rejected",
        "apply": "applied",
        "applied": "applied",
    }

    def create_task(self, dataset_id: int, algorithm_ids: list[int], parameters: dict) -> dict:
        if not algorithm_ids:
            raise ValidationError("At least one cleaning algorithm is required.")

        with self.session_factory() as session:
            dataset = session.query(Dataset).filter(Dataset.id == dataset_id).first()
            if dataset is None:
                raise NotFoundError(f"Dataset {dataset_id} not found.")
            if dataset.is_deleted or dataset.status == "deleted":
                raise ValidationError("Dataset must be active for cleaning.")

            algorithms: list[Algorithm] = []
            for algorithm_id in algorithm_ids:
                algorithm = self.algorithm_repository.get_algorithm(session, algorithm_id)
                if not algorithm:
                    raise NotFoundError(f"Algorithm {algorithm_id} not found.")
                if algorithm.category != "cleaning":
                    raise ValidationError("All algorithms must be cleaning algorithms.")
                if algorithm.status != "enabled":
                    raise ValidationError("All algorithms must be enabled.")
                algorithms.append(algorithm)
            primary_algorithm = algorithms[0]
            resolved_algorithm_ids = [algorithm.id for algorithm in algorithms]
            resolved_parameters = {**(parameters or {}), "algorithm_ids": resolved_algorithm_ids}

            task = self.task_repository.create_task(
                session,
                task_type="cleaning",
                status="pending",
                title="",
                source_dataset_id=dataset_id,
                target_dataset_id=dataset_id,
                algorithm_id=primary_algorithm.id,
                parameters_json=resolved_parameters,
                payload_json={"dataset_id": dataset_id, "algorithm_ids": resolved_algorithm_ids},
                result_json={},
            )
            task.title = f"清洗任务_{dataset.name}_#{task.id}"
            self.task_repository.add_task_log(session, task_id=task.id, level="info", message="Cleaning task created")
            session.commit()
            return {"ok": True, "data": {"task_id": task.id, "status": task.status}}

    def create_cleaning_task(self, dataset_id: int, algorithm_ids: list[int], parameters: dict) -> dict:
        return self.create_task(dataset_id, algorithm_ids, parameters)

    def run_task(self, task_id: int, context=None) -> dict:
        with self.session_factory() as session:
            task = self.task_repository.get_task_model(session, task_id)
            if task is None:
                raise NotFoundError(f"Task {task_id} not found.")
            if task.status != "running":
                raise ValidationError(f"Cleaning task {task_id} cannot run from status '{task.status}'.")
            dataset = session.query(Dataset).filter(Dataset.id == task.source_dataset_id).first()
            if dataset is None or dataset.is_deleted or dataset.status == "deleted":
                raise ValidationError("Cleaning source dataset is not active.")
            algorithm_ids = list(task.payload_json.get("algorithm_ids", []))
            algorithms: list[Algorithm] = []
            for algorithm_id in algorithm_ids:
                algorithm = self.algorithm_repository.get_algorithm(session, algorithm_id)
                if not algorithm:
                    raise NotFoundError(f"Algorithm {algorithm_id} not found.")
                if algorithm.category != "cleaning":
                    raise ValidationError("All algorithms must be cleaning algorithms.")
                if algorithm.status != "enabled":
                    raise ValidationError("All algorithms must be enabled.")
                algorithms.append(algorithm)

            samples = session.query(Sample).filter(Sample.dataset_id == dataset.id).order_by(Sample.id.asc()).all()
            samples = interleave_by_top_folder(samples)

        plugin_context = context or self.task_manager.build_context(task_id)
        all_suggestions: list[dict] = []
        try:
            for algorithm in algorithms:
                payload = {
                    "task_id": task_id,
                    "algorithm_key": algorithm.key,
                    "category": "cleaning",
                    "modality": dataset.modality,
                    "parameters": task.parameters_json,
                    "input": {
                        "dataset_id": dataset.id,
                        "dataset_path": dataset.storage_path,
                        "samples": [self._serialize_sample(sample) for sample in samples],
                    },
                    "output": {
                        "output_dir": str(self.task_manager.task_output_dir("cleaning", task_id)),
                    },
                }
                result = self.plugin_runner.run(
                    payload,
                    plugin_context,
                    module_path=algorithm.module_path or None,
                    callable_name=algorithm.callable_name or None,
                    script_path=algorithm.script_path or None,
                )
                if not result.get("ok", False):
                    error_code = result.get("error_code", "ALGORITHM_RUNTIME_ERROR")
                    error_message = result.get("message", "Cleaning plugin failed.")
                    self.task_manager.fail(task_id, error_code=error_code, error_message=error_message)
                    return {"ok": False, "error_code": error_code, "message": error_message}
                for suggestion in result.get("suggestions", []):
                    persisted_suggestion = dict(suggestion)
                    persisted_suggestion["algorithm_id"] = algorithm.id
                    all_suggestions.append(persisted_suggestion)

            with self.session_factory() as session:
                for suggestion in all_suggestions:
                    row = CleaningSuggestion(
                        task_id=task_id,
                        sample_id=suggestion["sample_id"],
                        algorithm_id=suggestion.get("algorithm_id"),
                        issue_type=suggestion["issue_type"],
                        suggested_action=suggestion["suggested_action"],
                        status="pending",
                        confidence=float(suggestion.get("confidence", 0.0)),
                        message=suggestion.get("message", ""),
                        details_json=suggestion.get("details", {}),
                    )
                    session.add(row)
                session.commit()
            self.task_manager.complete(task_id, result_json={"suggestions_created": len(all_suggestions)})
            return {"ok": True, "data": {"task_id": task_id, "suggestions_created": len(all_suggestions)}}
        except Exception as exc:
            self.task_manager.fail(task_id, error_code="ALGORITHM_RUNTIME_ERROR", error_message=str(exc))
            raise

    def list_suggestions(self, task_id: int, status: str | None, page: int, page_size: int) -> dict:
        with self.session_factory() as session:
            task = self.task_repository.get_task_model(session, task_id)
            if task is None:
                raise NotFoundError(f"Task {task_id} not found.")
            query = session.query(CleaningSuggestion).filter(CleaningSuggestion.task_id == task_id)
            if status:
                query = query.filter(CleaningSuggestion.status == status)
            total = query.count()
            items = (
                query.order_by(CleaningSuggestion.created_at.asc(), CleaningSuggestion.id.asc())
                .offset(max(page - 1, 0) * page_size)
                .limit(page_size)
                .all()
            )
            monitor_items = self._build_monitor_items(session, task)
            parameters = dict(task.parameters_json or {})
            parameters.pop("algorithm_ids", None)
            return {
                "total": total,
                "items": [self._serialize_suggestion(item) for item in items],
                "monitor_items": monitor_items,
                "parameters": parameters,
            }

    def handle_suggestion(self, suggestion_id: int, action: str) -> dict:
        normalized_action = self._SUGGESTION_STATUS_MAP.get(action)
        if normalized_action is None:
            raise ValidationError(f"Unsupported suggestion action '{action}'.")
        with self.session_factory() as session:
            suggestion = session.query(CleaningSuggestion).filter(CleaningSuggestion.id == suggestion_id).first()
            if suggestion is None:
                raise NotFoundError(f"Suggestion {suggestion_id} not found.")
            self._validate_suggestion_transition(suggestion, normalized_action)
            if normalized_action == "applied":
                self._apply_suggestion(session, suggestion)
            suggestion.status = normalized_action
            self.task_repository.add_task_log(
                session,
                task_id=suggestion.task_id,
                level="info",
                message=f"Cleaning suggestion {normalized_action}",
                payload_json={"suggestion_id": suggestion.id, "sample_id": suggestion.sample_id},
            )
            session.commit()
            return {"ok": True, "data": self._serialize_suggestion(suggestion)}

    def batch_handle_suggestions(self, suggestion_ids: list[int], action: str) -> dict:
        updated = []
        for suggestion_id in suggestion_ids:
            updated.append(self.handle_suggestion(suggestion_id, action)["data"])
        return {"ok": True, "data": {"updated_count": len(updated), "items": updated}}

    def store_cleaned_dataset(self, task_id: int, dataset_name: str | None = None) -> dict:
        with self.session_factory() as session:
            task = self.task_repository.get_task_model(session, task_id)
            if task is None:
                raise NotFoundError(f"Task {task_id} not found.")
            if task.task_type != "cleaning":
                raise ValidationError("Only cleaning tasks can be stored as cleaned datasets.")
            if task.status != "completed":
                raise ValidationError("Only completed cleaning tasks can be stored.")

            source_dataset = session.query(Dataset).filter(Dataset.id == task.source_dataset_id).first()
            if source_dataset is None:
                raise NotFoundError(f"Dataset {task.source_dataset_id} not found.")
            if source_dataset.is_deleted or source_dataset.status == "deleted":
                raise ValidationError("Cleaning source dataset is not active.")

            clean_name = (dataset_name or f"{source_dataset.name}_cleaned").strip()
            if not clean_name:
                raise ValidationError("Cleaned dataset name is required.")

            target_dataset = self.dataset_repository.create_dataset(
                session,
                name=clean_name,
                modality=source_dataset.modality,
                description=f"Cleaned dataset stored from cleaning task {task_id}",
                status="cleaned",
                parent_dataset_id=source_dataset.id,
                storage_path="",
                tags_json=["cleaned"],
                extra_json={
                    "source_dataset_id": source_dataset.id,
                    "cleaning_task_id": task_id,
                },
            )
            target_dataset.storage_path = str(self._allocate_dataset_dir(target_dataset.id, clean_name))

            suggestions = (
                session.query(CleaningSuggestion)
                .filter(CleaningSuggestion.task_id == task_id, CleaningSuggestion.status != "rejected")
                .order_by(CleaningSuggestion.confidence.desc(), CleaningSuggestion.id.asc())
                .all()
            )
            suggestions_by_sample: dict[int, list[CleaningSuggestion]] = {}
            output_sample_ids: set[int] = set()
            for suggestion in suggestions:
                suggestions_by_sample.setdefault(suggestion.sample_id, []).append(suggestion)
                if suggestion.output_sample_id:
                    output_sample_ids.add(suggestion.output_sample_id)

            source_samples = (
                session.query(Sample)
                .filter(Sample.dataset_id == source_dataset.id, Sample.status != "deleted")
                .order_by(Sample.id.asc())
                .all()
            )

            stored_count = 0
            skipped_count = 0
            for sample in source_samples:
                if sample.id in output_sample_ids:
                    continue
                sample_suggestions = suggestions_by_sample.get(sample.id, [])
                if self._should_skip_sample(sample_suggestions):
                    skipped_count += 1
                    continue

                source_path = self._stored_sample_source_path(session, sample, sample_suggestions)
                if not source_path.is_file():
                    skipped_count += 1
                    continue

                relative_path = sample.relative_path or sample.name
                copied = self.file_indexer.copy_into_dataset(
                    source_path,
                    Path(target_dataset.storage_path) / "cleaned",
                    relative_path,
                )
                self.dataset_repository.create_sample(
                    session,
                    dataset_id=target_dataset.id,
                    source_sample_id=sample.id,
                    name=sample.name,
                    modality=sample.modality,
                    file_path=str(copied),
                    relative_path=Path(relative_path).as_posix(),
                    sha256=self.file_indexer.compute_sha256(copied),
                    mime_type=self.file_indexer.detect_mime_type(copied),
                    extension=copied.suffix.lower(),
                    size_bytes=copied.stat().st_size,
                    status="cleaned",
                    metadata_json={
                        **(sample.metadata_json or {}),
                        "source_dataset_id": source_dataset.id,
                        "source_sample_id": sample.id,
                        "cleaning_task_id": task_id,
                    },
                    labels_json=list(sample.labels_json or []),
                )
                stored_count += 1

            self._refresh_dataset_stats(session, target_dataset)
            result_json = dict(task.result_json or {})
            result_json.update(
                {
                    "stored_dataset_id": target_dataset.id,
                    "stored_dataset_name": target_dataset.name,
                    "stored_dataset_path": target_dataset.storage_path,
                    "stored_count": stored_count,
                    "skipped_count": skipped_count,
                }
            )
            task.target_dataset_id = target_dataset.id
            task.result_json = result_json
            self.task_repository.add_task_log(
                session,
                task_id=task_id,
                level="info",
                message="Cleaning task stored as cleaned dataset",
                payload_json={
                    "source_dataset_id": source_dataset.id,
                    "target_dataset_id": target_dataset.id,
                    "stored_count": stored_count,
                    "skipped_count": skipped_count,
                    "storage_path": target_dataset.storage_path,
                },
            )
            session.commit()

            return {
                "ok": True,
                "data": {
                    "task_id": task_id,
                    "source_dataset_id": source_dataset.id,
                    "stored_count": stored_count,
                    "skipped_count": skipped_count,
                    "dataset": self._serialize_dataset(target_dataset),
                },
            }

    def _serialize_sample(self, sample: Sample) -> dict:
        return {
            "id": sample.id,
            "name": sample.name,
            "path": sample.file_path,
            "sample_path": sample.file_path,
            "sample_type": sample.modality,
            "relative_path": sample.relative_path,
            "sha256": sample.sha256,
            "metadata": sample.metadata_json,
            "status": sample.status,
        }

    def _serialize_suggestion(self, suggestion: CleaningSuggestion) -> dict:
        sample = None
        output_sample = None
        with self.session_factory() as session:
            if suggestion.sample_id:
                sample = session.query(Sample).filter(Sample.id == suggestion.sample_id).first()
            if suggestion.output_sample_id:
                output_sample = session.query(Sample).filter(Sample.id == suggestion.output_sample_id).first()
        return {
            "id": suggestion.id,
            "task_id": suggestion.task_id,
            "sample_id": suggestion.sample_id,
            "algorithm_id": suggestion.algorithm_id,
            "output_sample_id": suggestion.output_sample_id,
            "issue_type": suggestion.issue_type,
            "suggested_action": suggestion.suggested_action,
            "status": suggestion.status,
            "confidence": suggestion.confidence,
            "message": suggestion.message,
            "details": suggestion.details_json,
            "sample": self._serialize_sample(sample) if sample is not None else None,
            "output_sample": self._serialize_sample(output_sample) if output_sample is not None else None,
        }

    def _apply_suggestion(self, session, suggestion: CleaningSuggestion) -> None:
        sample = session.query(Sample).filter(Sample.id == suggestion.sample_id).first()
        if sample is None:
            raise NotFoundError(f"Sample {suggestion.sample_id} not found.")
        dataset = session.query(Dataset).filter(Dataset.id == sample.dataset_id).first()
        if dataset is None:
            raise NotFoundError(f"Dataset {sample.dataset_id} not found.")
        if dataset.is_deleted or dataset.status == "deleted":
            raise ValidationError("Cannot apply cleaning suggestion on a deleted dataset.")

        suggested_action = (suggestion.suggested_action or "").strip().lower()
        if suggested_action in {"delete", "exclude"}:
            sample_path = Path(sample.file_path)
            if sample_path.is_file():
                sample_path.unlink(missing_ok=True)
            self.dataset_repository.delete_sample(session, sample)
            self._refresh_dataset_stats(session, dataset)
            return
        if sample.status == "deleted":
            raise ValidationError("Cannot apply a repair-like suggestion to a deleted sample.")

        source_path = self._resolve_cleaned_source_path(sample, suggestion)
        if not source_path.is_file():
            raise ValidationError(f"Cleaned artifact path does not exist: {source_path}")

        cleaned_root = Path(dataset.storage_path) / "cleaned"
        relative_path = sample.relative_path or sample.name
        copied = self.file_indexer.copy_into_dataset(source_path, cleaned_root, relative_path)
        output_sample = self.dataset_repository.create_sample(
            session,
            dataset_id=dataset.id,
            source_sample_id=sample.id,
            name=copied.name,
            modality=sample.modality,
            file_path=str(copied),
            relative_path=Path(relative_path).as_posix(),
            sha256=self.file_indexer.compute_sha256(copied),
            mime_type=self.file_indexer.detect_mime_type(copied),
            extension=copied.suffix.lower(),
            size_bytes=copied.stat().st_size,
            status="cleaned",
            metadata_json={
                **(sample.metadata_json or {}),
                "cleaning_suggestion_id": suggestion.id,
                "source_sample_id": sample.id,
            },
            labels_json=list(sample.labels_json or []),
        )
        suggestion.output_sample_id = output_sample.id
        self._refresh_dataset_stats(session, dataset)

    def _resolve_cleaned_source_path(self, sample: Sample, suggestion: CleaningSuggestion) -> Path:
        details = suggestion.details_json or {}
        candidate = details.get("output_file_path") or details.get("cleaned_file_path")
        if not candidate:
            raise ValidationError("Repair-like suggestions require output_file_path or cleaned_file_path in details.")
        return Path(candidate)

    def _should_skip_sample(self, suggestions: list[CleaningSuggestion]) -> bool:
        for suggestion in suggestions:
            suggested_action = (suggestion.suggested_action or "").strip().lower()
            if suggested_action in {"delete", "exclude"}:
                return True
        return False

    def _stored_sample_source_path(self, session, sample: Sample, suggestions: list[CleaningSuggestion]) -> Path:
        for suggestion in suggestions:
            suggested_action = (suggestion.suggested_action or "").strip().lower()
            if suggested_action in {"repair", "replace", "fix", "clean"}:
                if suggestion.output_sample_id:
                    output_sample = session.query(Sample).filter(Sample.id == suggestion.output_sample_id).first()
                    if output_sample is not None:
                        return Path(output_sample.file_path)
                details = suggestion.details_json or {}
                candidate = details.get("output_file_path") or details.get("cleaned_file_path")
                if candidate:
                    return Path(candidate)
        return Path(sample.file_path)

    def _build_monitor_items(self, session, task) -> list[dict]:
        dataset = session.query(Dataset).filter(Dataset.id == task.source_dataset_id).first()
        if dataset is None:
            return []
        samples = (
            session.query(Sample)
            .filter(Sample.dataset_id == dataset.id)
            .order_by(Sample.id.asc())
            .all()
        )
        suggestions = (
            session.query(CleaningSuggestion)
            .filter(CleaningSuggestion.task_id == task.id)
            .order_by(CleaningSuggestion.confidence.desc(), CleaningSuggestion.id.asc())
            .all()
        )
        suggestions_by_sample: dict[int, list[CleaningSuggestion]] = {}
        for suggestion in suggestions:
            suggestions_by_sample.setdefault(suggestion.sample_id, []).append(suggestion)

        monitor_items = []
        for sample in samples:
            sample_suggestions = suggestions_by_sample.get(sample.id, [])
            selected = sample_suggestions[0] if sample_suggestions else None
            if selected is None:
                suggestion_id = -1
                if task.status == "completed":
                    operation = "keep"
                    operation_label = "保留"
                    issue_type = "none"
                    suggested_action = "keep"
                    confidence = 1.0
                    message = "未发现清洗问题，保留样本"
                    status = "kept"
                else:
                    operation = "pending"
                    operation_label = "待处理"
                    issue_type = "pending"
                    suggested_action = "pending"
                    confidence = 0.0
                    message = "等待清洗算法处理"
                    status = task.status
            else:
                suggestion_id = selected.id
                issue_type = selected.issue_type
                suggested_action = selected.suggested_action
                confidence = selected.confidence
                message = selected.message
                status = selected.status
                operation, operation_label = self._operation_for_action(selected.suggested_action)

            monitor_items.append(
                {
                    "sample_id": sample.id,
                    "suggestion_id": suggestion_id,
                    "sample_name": sample.name,
                    "sample_path": sample.file_path,
                    "sample_type": sample.modality,
                    "issue_type": issue_type,
                    "confidence": confidence,
                    "suggested_action": suggested_action,
                    "operation": operation,
                    "operation_label": operation_label,
                    "status": status,
                    "message": message,
                }
            )
        return monitor_items

    def _operation_for_action(self, suggested_action: str) -> tuple[str, str]:
        action = (suggested_action or "").strip().lower()
        if action in {"delete", "exclude"}:
            return "delete", "删除"
        if action in {"repair", "replace", "fix", "clean"}:
            return "repair", "修复"
        if action in {"review", "manual_review"}:
            return "review", "人工审核"
        if action in {"keep", "none"}:
            return "keep", "保留"
        return action or "review", suggested_action or "人工审核"

    def _validate_suggestion_transition(self, suggestion: CleaningSuggestion, normalized_action: str) -> None:
        current = (suggestion.status or "pending").strip().lower()
        if current == "applied":
            raise ValidationError("Applied suggestions cannot be changed.")
        if normalized_action == "approved" and current != "pending":
            raise ValidationError(f"Cannot approve suggestion from status '{current}'.")
        if normalized_action == "rejected" and current not in {"pending", "approved"}:
            raise ValidationError(f"Cannot reject suggestion from status '{current}'.")
        if normalized_action == "applied" and current not in {"pending", "approved"}:
            raise ValidationError(f"Cannot apply suggestion from status '{current}'.")

    def _refresh_dataset_stats(self, session, dataset: Dataset) -> None:
        total_samples = self.dataset_repository.dataset_sample_count(session, dataset.id)
        size_bytes = self.dataset_repository.dataset_total_size(session, dataset.id)
        modality_breakdown = self.dataset_repository.dataset_modality_breakdown(session, dataset.id)
        self.dataset_repository.update_dataset_counts(dataset, total_samples=total_samples, size_bytes=size_bytes)
        self.dataset_repository.upsert_statistics(
            session,
            dataset.id,
            total_samples=total_samples,
            size_bytes=size_bytes,
            modality_breakdown=modality_breakdown,
        )

    def _allocate_dataset_dir(self, dataset_id: int, name: str) -> Path:
        root = self.paths.datasets_dir / f"{dataset_id}_{self._sanitize_name(name)}"
        for subdir in [root, root / "raw", root / "cleaned", root / "generated", root / "preview"]:
            subdir.mkdir(parents=True, exist_ok=True)
        return root

    def _sanitize_name(self, name: str) -> str:
        invalid = '<>:"/\\|?*'
        sanitized = "".join("_" if char in invalid else char for char in name).strip().strip(".")
        return sanitized or "dataset"

    def _serialize_dataset(self, dataset: Dataset) -> dict:
        return {
            "id": dataset.id,
            "name": dataset.name,
            "modality": dataset.modality,
            "description": dataset.description,
            "status": dataset.status,
            "parent_dataset_id": dataset.parent_dataset_id,
            "storage_path": dataset.storage_path,
            "total_samples": dataset.total_samples,
            "size_bytes": dataset.size_bytes,
            "tags": dataset.tags_json or [],
            "extra": dataset.extra_json or {},
        }
