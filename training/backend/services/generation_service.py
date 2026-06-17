from __future__ import annotations

from dataclasses import field
from .._compat import slots_dataclass
from pathlib import Path

from ..errors import NotFoundError, ValidationError
from ..models import Algorithm, Dataset, GenerationOutput, Sample
from ..plugins import PluginRunner
from ..storage import FileIndexer
from .base import ServiceBase
from .sample_ordering import interleave_by_top_folder


@slots_dataclass
class GenerationService(ServiceBase):
    task_manager: object
    task_repository: object
    algorithm_repository: object
    dataset_repository: object
    plugin_runner: PluginRunner = field(default_factory=PluginRunner)
    file_indexer: FileIndexer = field(default_factory=FileIndexer)

    def create_task(
        self,
        source_dataset_id: int,
        target_dataset_id: int,
        algorithm_ids: list[int],
        parameters: dict,
        target_count: int,
    ) -> dict:
        if not algorithm_ids:
            raise ValidationError("At least one generation algorithm is required.")
        if target_count <= 0:
            raise ValidationError("target_count must be greater than zero.")

        with self.session_factory() as session:
            source_dataset = session.query(Dataset).filter(Dataset.id == source_dataset_id).first()
            if source_dataset is None:
                raise NotFoundError(f"Dataset {source_dataset_id} not found.")
            if source_dataset.is_deleted or source_dataset.status == "deleted":
                raise ValidationError("Source dataset must be active for generation.")

            source_samples = (
                session.query(Sample)
                .filter(Sample.dataset_id == source_dataset.id, Sample.status != "deleted")
                .order_by(Sample.id.asc())
                .all()
            )
            source_samples = [sample for sample in source_samples if self._is_generation_input_sample(sample, source_dataset.modality)]
            source_samples = interleave_by_top_folder(source_samples)
            if not source_samples:
                raise ValidationError("Source dataset must contain at least one active sample.")

            algorithms: list[Algorithm] = []
            for algorithm_id in algorithm_ids:
                algorithm = self.algorithm_repository.get_algorithm(session, algorithm_id)
                if not algorithm:
                    raise NotFoundError(f"Algorithm {algorithm_id} not found.")
                if algorithm.category != "generation":
                    raise ValidationError("All algorithms must be generation algorithms.")
                if algorithm.status != "enabled":
                    raise ValidationError("All algorithms must be enabled.")
                if algorithm.modality not in {source_dataset.modality, "multimodal"}:
                    raise ValidationError("Algorithm modality must match the source dataset modality.")
                algorithms.append(algorithm)

            target_dataset = self._resolve_target_dataset(session, source_dataset, target_dataset_id)
            resolved_algorithm_ids = [algorithm.id for algorithm in algorithms]
            resolved_parameters = {**(parameters or {}), "algorithm_ids": resolved_algorithm_ids, "target_count": target_count}

            task = self.task_repository.create_task(
                session,
                task_type="generation",
                status="pending",
                title="",
                source_dataset_id=source_dataset.id,
                target_dataset_id=target_dataset.id,
                algorithm_id=algorithms[0].id,
                parameters_json=resolved_parameters,
                payload_json={
                    "source_dataset_id": source_dataset.id,
                    "target_dataset_id": target_dataset.id,
                    "algorithm_ids": resolved_algorithm_ids,
                    "target_count": target_count,
                },
                result_json={},
            )
            task.title = f"生成任务_{source_dataset.name}_#{task.id}"
            self.task_repository.add_task_log(session, task_id=task.id, level="info", message="Generation task created")
            session.commit()
            return {
                "ok": True,
                "data": {
                    "task_id": task.id,
                    "status": task.status,
                    "target_dataset_id": target_dataset.id,
                    "target_dataset_name": target_dataset.name,
                },
            }

    def create_generation_task(
        self,
        source_dataset_id: int,
        target_dataset_id: int,
        algorithm_ids: list[int],
        parameters: dict,
        target_count: int,
    ) -> dict:
        return self.create_task(source_dataset_id, target_dataset_id, algorithm_ids, parameters, target_count)

    def run_task(self, task_id: int, context=None) -> dict:
        with self.session_factory() as session:
            task = self.task_repository.get_task_model(session, task_id)
            if task is None:
                raise NotFoundError(f"Task {task_id} not found.")
            if task.status != "running":
                raise ValidationError(f"Generation task {task_id} cannot run from status '{task.status}'.")

            source_dataset = session.query(Dataset).filter(Dataset.id == task.source_dataset_id).first()
            target_dataset = session.query(Dataset).filter(Dataset.id == task.target_dataset_id).first()
            if source_dataset is None or source_dataset.is_deleted or source_dataset.status == "deleted":
                raise ValidationError("Generation source dataset is not active.")
            if target_dataset is None or target_dataset.is_deleted or target_dataset.status == "deleted":
                raise ValidationError("Generation target dataset is not active.")

            algorithm_ids = list(task.payload_json.get("algorithm_ids", []))
            target_count = int(task.payload_json.get("target_count", 0))
            if target_count <= 0:
                raise ValidationError("Generation task target_count must be greater than zero.")

            algorithms: list[Algorithm] = []
            for algorithm_id in algorithm_ids:
                algorithm = self.algorithm_repository.get_algorithm(session, algorithm_id)
                if not algorithm:
                    raise NotFoundError(f"Algorithm {algorithm_id} not found.")
                if algorithm.category != "generation":
                    raise ValidationError("All algorithms must be generation algorithms.")
                if algorithm.status != "enabled":
                    raise ValidationError("All algorithms must be enabled.")
                if algorithm.modality not in {source_dataset.modality, "multimodal"}:
                    raise ValidationError("Algorithm modality must match the source dataset modality.")
                algorithms.append(algorithm)

            source_samples = (
                session.query(Sample)
                .filter(Sample.dataset_id == source_dataset.id, Sample.status != "deleted")
                .order_by(Sample.id.asc())
                .all()
            )
            source_samples = [sample for sample in source_samples if self._is_generation_input_sample(sample, source_dataset.modality)]
            source_samples = interleave_by_top_folder(source_samples)
            if not source_samples:
                raise ValidationError("Source dataset must contain at least one active sample.")

        plugin_context = context or self.task_manager.build_context(task_id)
        pending_outputs: list[tuple[int, list[dict]]] = []
        produced_count = 0
        try:
            for algorithm in algorithms:
                remaining_count = target_count - produced_count
                if remaining_count <= 0:
                    break
                payload = {
                    "task_id": task_id,
                    "algorithm_key": algorithm.key,
                    "category": "generation",
                    "modality": source_dataset.modality,
                    "parameters": task.parameters_json,
                    "target_count": remaining_count,
                    "input": {
                        "dataset_id": source_dataset.id,
                        "dataset_path": source_dataset.storage_path,
                        "samples": [self._serialize_sample(sample) for sample in source_samples],
                    },
                    "output": {
                        "output_dir": self.task_manager.get_output_dir(task_id),
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
                    error_message = result.get("message", "Generation plugin failed.")
                    self.task_manager.fail(task_id, error_code=error_code, error_message=error_message)
                    return {"ok": False, "error_code": error_code, "message": error_message}

                outputs = list(result.get("outputs", []))[:remaining_count]
                pending_outputs.append((algorithm.id, outputs))
                produced_count += len(outputs)
                progress_pct = min(produced_count / target_count * 100.0, 99.0)
                self.task_manager.set_progress(task_id, progress_pct, f"Produced {produced_count}/{target_count}")

            if produced_count < target_count:
                import logging
                logging.getLogger("isg").warning(
                    f"Generation task {task_id}: produced {produced_count}/{target_count}, "
                    f"{target_count - produced_count} samples skipped. Continuing with available outputs."
                )

            for algorithm_id, outputs in pending_outputs:
                self._persist_generation_outputs(
                    task_id=task_id,
                    target_dataset_id=target_dataset.id,
                    algorithm_id=algorithm_id,
                    outputs=outputs,
                )

            source_copied_count = 0
            if source_dataset.modality == "image":
                source_copied_count = self._persist_source_image_outputs(
                    task_id=task_id,
                    target_dataset_id=target_dataset.id,
                    source_samples=source_samples,
                )

            total_count = produced_count + source_copied_count
            self.task_manager.complete(
                task_id,
                result_json={
                    "generated_count": produced_count,
                    "source_copied_count": source_copied_count,
                    "total_count": total_count,
                    "target_dataset_id": target_dataset.id,
                },
            )
            return {
                "ok": True,
                "data": {
                    "task_id": task_id,
                    "generated_count": produced_count,
                    "source_copied_count": source_copied_count,
                    "total_count": total_count,
                    "target_dataset_id": target_dataset.id,
                },
            }
        except Exception as exc:
            self.task_manager.fail(task_id, error_code="ALGORITHM_RUNTIME_ERROR", error_message=str(exc))
            raise

    def list_outputs(self, task_id: int, status: str | None, page: int, page_size: int) -> dict:
        with self.session_factory() as session:
            task = self.task_repository.get_task_model(session, task_id)
            if task is None:
                raise NotFoundError(f"Task {task_id} not found.")
            query = session.query(GenerationOutput).filter(GenerationOutput.task_id == task_id)
            if status:
                query = query.filter(GenerationOutput.status == status)
            total = query.count()
            items = (
                query.order_by(GenerationOutput.created_at.asc(), GenerationOutput.id.asc())
                .offset(max(page - 1, 0) * page_size)
                .limit(page_size)
                .all()
            )
            parameters = dict(task.parameters_json or {})
            parameters.pop("algorithm_ids", None)
            return {
                "total": total,
                "items": [self._serialize_generation_output(session, item) for item in items],
                "parameters": parameters,
                "page": max(page, 1),
                "page_size": max(page_size, 1),
            }

    def get_generation_outputs(self, task_id: int, status: str | None, page: int, page_size: int) -> dict:
        return self.list_outputs(task_id, status, page, page_size)

    def _resolve_target_dataset(self, session, source_dataset: Dataset, target_dataset_id: int) -> Dataset:
        if target_dataset_id:
            target_dataset = session.query(Dataset).filter(Dataset.id == target_dataset_id).first()
            if target_dataset is None:
                raise NotFoundError(f"Dataset {target_dataset_id} not found.")
            if target_dataset.is_deleted or target_dataset.status == "deleted":
                raise ValidationError("Target dataset must be active for generation.")
            if target_dataset.modality != source_dataset.modality:
                raise ValidationError("Target dataset modality must match the source dataset modality.")
            return target_dataset

        target_dataset = self.dataset_repository.create_dataset(
            session,
            name=f"Generated from {source_dataset.name}",
            modality=source_dataset.modality,
            description=f"Auto-created target dataset for source dataset {source_dataset.id}",
            status="generated",
            parent_dataset_id=source_dataset.id,
            storage_path="",
            tags_json=["generated"],
            extra_json={"source_dataset_id": source_dataset.id, "dataset_stage": "generated"},
        )
        target_dataset.storage_path = str(self._allocate_dataset_dir(target_dataset.id, target_dataset.name))
        return target_dataset

    def _persist_generation_outputs(self, *, task_id: int, target_dataset_id: int, algorithm_id: int, outputs: list[dict]) -> list[dict]:
        if not outputs:
            return []

        persisted_items: list[dict] = []
        with self.session_factory() as session:
            target_dataset = session.query(Dataset).filter(Dataset.id == target_dataset_id).first()
            if target_dataset is None:
                raise NotFoundError(f"Dataset {target_dataset_id} not found.")

            for output in outputs:
                output_path = Path(output["output_path"])
                if not output_path.is_file():
                    raise ValidationError(f"Generated output file does not exist: {output_path}")

                source_sample = None
                if output.get("source_sample_id"):
                    source_sample = session.query(Sample).filter(Sample.id == output.get("source_sample_id")).first()
                inherited_labels = output.get("labels")
                if inherited_labels is None and source_sample is not None:
                    inherited_labels = list(source_sample.labels_json or [])
                inherited_metadata = dict(output.get("metadata", {}) or {})
                if inherited_labels:
                    inherited_metadata.setdefault("labels_inherited", True)
                    inherited_metadata.setdefault("source_labels", inherited_labels)

                requested_relative_path = output.get("relative_path") or output_path.name
                generated_root = Path(target_dataset.storage_path) / "generated"
                copied = self.file_indexer.copy_into_dataset(output_path, generated_root, requested_relative_path)
                final_relative_path = copied.relative_to(generated_root).as_posix()
                output_sample = self.dataset_repository.create_sample(
                    session,
                    dataset_id=target_dataset.id,
                    source_sample_id=output.get("source_sample_id"),
                    name=copied.name,
                    modality=target_dataset.modality,
                    file_path=str(copied),
                    relative_path=final_relative_path,
                    sha256=self.file_indexer.compute_sha256(copied),
                    mime_type=self.file_indexer.detect_mime_type(copied),
                    extension=copied.suffix.lower(),
                    size_bytes=copied.stat().st_size,
                    status="generated",
                    metadata_json=inherited_metadata,
                    labels_json=inherited_labels or [],
                )
                row = GenerationOutput(
                    task_id=task_id,
                    source_sample_id=output.get("source_sample_id"),
                    output_sample_id=output_sample.id,
                    algorithm_id=algorithm_id,
                    status=output.get("status", "created"),
                    metadata_json=inherited_metadata,
                )
                session.add(row)
                session.flush()
                persisted_items.append(self._serialize_generation_output(session, row))

            self._refresh_dataset_stats(session, target_dataset)
            self.task_repository.add_task_log(
                session,
                task_id=task_id,
                level="info",
                message="Generation outputs persisted",
                payload_json={"generated_count": len(persisted_items), "target_dataset_id": target_dataset.id},
            )
            session.commit()
        return persisted_items

    def _persist_source_image_outputs(self, *, task_id: int, target_dataset_id: int, source_samples: list[Sample]) -> int:
        if not source_samples:
            return 0

        copied_count = 0
        with self.session_factory() as session:
            target_dataset = session.query(Dataset).filter(Dataset.id == target_dataset_id).first()
            if target_dataset is None:
                raise NotFoundError(f"Dataset {target_dataset_id} not found.")

            generated_root = Path(target_dataset.storage_path) / "generated"
            for source_sample in source_samples:
                source_path = Path(source_sample.file_path or "")
                if not source_path.is_file():
                    continue

                labels = list(source_sample.labels_json or [])
                metadata = dict(source_sample.metadata_json or {})
                metadata.update(
                    {
                        "result_type": "source",
                        "is_original": True,
                        "source_sample_id": source_sample.id,
                    }
                )
                requested_relative_path = Path("source") / (source_sample.relative_path or source_path.name)
                copied = self.file_indexer.copy_into_dataset(source_path, generated_root, requested_relative_path.as_posix())
                final_relative_path = copied.relative_to(generated_root).as_posix()
                output_sample = self.dataset_repository.create_sample(
                    session,
                    dataset_id=target_dataset.id,
                    source_sample_id=source_sample.id,
                    name=copied.name,
                    modality=target_dataset.modality,
                    file_path=str(copied),
                    relative_path=final_relative_path,
                    sha256=self.file_indexer.compute_sha256(copied),
                    mime_type=self.file_indexer.detect_mime_type(copied),
                    extension=copied.suffix.lower(),
                    size_bytes=copied.stat().st_size,
                    status="generated",
                    metadata_json=metadata,
                    labels_json=labels,
                )
                session.add(
                    GenerationOutput(
                        task_id=task_id,
                        source_sample_id=source_sample.id,
                        output_sample_id=output_sample.id,
                        algorithm_id=None,
                        status="source",
                        metadata_json=metadata,
                    )
                )
                copied_count += 1

            self._refresh_dataset_stats(session, target_dataset)
            self.task_repository.add_task_log(
                session,
                task_id=task_id,
                level="info",
                message="Source image samples copied into generation outputs",
                payload_json={"source_copied_count": copied_count, "target_dataset_id": target_dataset.id},
            )
            session.commit()
        return copied_count

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

    def _serialize_sample(self, sample: Sample) -> dict:
        return {
            "id": sample.id,
            "name": sample.name,
            "path": sample.file_path,
            "sample_path": sample.file_path,
            "sample_type": sample.modality,
            "relative_path": sample.relative_path,
            "metadata": sample.metadata_json,
            "labels": sample.labels_json or [],
            "source_sample_id": sample.source_sample_id,
            "status": sample.status,
        }

    def _is_generation_input_sample(self, sample: Sample, modality: str) -> bool:
        path = Path(sample.file_path or "")
        if not path.is_file():
            return False
        if modality != "image":
            return True
        image_extensions = {".bmp", ".jpeg", ".jpg", ".png", ".tif", ".tiff", ".webp"}
        return path.suffix.lower() in image_extensions

    def _serialize_generation_output(self, session, row: GenerationOutput) -> dict:
        source_sample = session.query(Sample).filter(Sample.id == row.source_sample_id).first()
        output_sample = session.query(Sample).filter(Sample.id == row.output_sample_id).first()
        return {
            "id": row.id,
            "task_id": row.task_id,
            "source_sample_id": row.source_sample_id,
            "output_sample_id": row.output_sample_id,
            "algorithm_id": row.algorithm_id,
            "status": row.status,
            "metadata": row.metadata_json,
            "output_path": output_sample.file_path if output_sample else "",
            "source_sample": self._serialize_sample(source_sample) if source_sample else None,
            "output_sample": self._serialize_sample(output_sample) if output_sample else None,
        }

    def _allocate_dataset_dir(self, dataset_id: int, name: str) -> Path:
        root = self.paths.datasets_dir / f"{dataset_id}_{self._sanitize_name(name)}"
        for subdir in [root, root / "raw", root / "cleaned", root / "generated", root / "preview"]:
            subdir.mkdir(parents=True, exist_ok=True)
        return root

    def _sanitize_name(self, name: str) -> str:
        invalid = '<>:"/\\|?*'
        sanitized = "".join("_" if char in invalid else char for char in name).strip().strip(".")
        return sanitized or "dataset"
