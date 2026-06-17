from __future__ import annotations

from dataclasses import field
from .._compat import slots_dataclass
from pathlib import Path

from ..errors import NotFoundError, ValidationError
from ..models import Algorithm, Dataset, Sample
from ..plugins import PluginRunner
from .base import ServiceBase
from .sample_ordering import interleave_by_top_folder


@slots_dataclass
class TrainingService(ServiceBase):
    task_manager: object
    task_repository: object
    algorithm_repository: object
    dataset_repository: object
    plugin_runner: PluginRunner = field(default_factory=PluginRunner)

    def create_task(
        self,
        scenario_id: int,
        dataset_id: int,
        algorithm_id: int,
        parameters: dict,
    ) -> dict:
        if not algorithm_id:
            raise ValidationError("A training algorithm is required.")

        with self.session_factory() as session:
            dataset = session.query(Dataset).filter(Dataset.id == dataset_id).first()
            if dataset is None:
                raise NotFoundError(f"Dataset {dataset_id} not found.")
            if dataset.is_deleted or dataset.status == "deleted":
                raise ValidationError("Dataset must be active for training.")

            samples = (
                session.query(Sample)
                .filter(Sample.dataset_id == dataset.id, Sample.status != "deleted")
                .all()
            )
            if not samples:
                raise ValidationError("Dataset must contain at least one active sample.")

            algorithm = self.algorithm_repository.get_algorithm(session, algorithm_id)
            if not algorithm:
                raise NotFoundError(f"Algorithm {algorithm_id} not found.")
            if algorithm.category != "training":
                raise ValidationError("Algorithm must be a training algorithm.")
            if algorithm.status != "enabled":
                raise ValidationError("Algorithm must be enabled.")

            resolved_parameters = {**(parameters or {}), "algorithm_id": algorithm.id}
            title = f"Training: {algorithm.name} on {dataset.name}"

            task = self.task_repository.create_task(
                session,
                task_type="training",
                status="pending",
                title=title,
                source_dataset_id=dataset.id,
                algorithm_id=algorithm.id,
                scenario_id=scenario_id if scenario_id else None,
                parameters_json=resolved_parameters,
                payload_json={
                    "dataset_id": dataset.id,
                    "algorithm_id": algorithm.id,
                    "scenario_id": scenario_id,
                },
                result_json={},
            )
            self.task_repository.add_task_log(session, task_id=task.id, level="info", message="Training task created")
            session.commit()
            return {
                "ok": True,
                "data": {"task_id": task.id, "status": task.status},
            }

    def run_task(self, task_id: int, context=None) -> dict:
        with self.session_factory() as session:
            task = self.task_repository.get_task_model(session, task_id)
            if task is None:
                raise NotFoundError(f"Task {task_id} not found.")
            if task.status != "running":
                raise ValidationError(f"Training task {task_id} cannot run from status '{task.status}'.")

            dataset = session.query(Dataset).filter(Dataset.id == task.source_dataset_id).first()
            if dataset is None or dataset.is_deleted or dataset.status == "deleted":
                raise ValidationError("Training dataset is not active.")

            algorithm = self.algorithm_repository.get_algorithm(session, task.algorithm_id)
            if not algorithm:
                raise NotFoundError(f"Algorithm {task.algorithm_id} not found.")
            if algorithm.category != "training":
                raise ValidationError("Algorithm must be a training algorithm.")

            samples = (
                session.query(Sample)
                .filter(Sample.dataset_id == dataset.id, Sample.status != "deleted")
                .order_by(Sample.id.asc())
                .all()
            )
            samples = interleave_by_top_folder(samples)
            if not samples:
                raise ValidationError("Dataset must contain at least one active sample.")

        plugin_context = context or self.task_manager.build_context(task_id)

        try:
            payload = {
                "task_id": task_id,
                "algorithm_key": algorithm.key,
                "category": "training",
                "modality": dataset.modality,
                "parameters": task.parameters_json,
                "input": {
                    "dataset_id": dataset.id,
                    "dataset_path": dataset.storage_path,
                    "samples": [self._serialize_sample(sample) for sample in samples],
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
                error_message = result.get("message", "Training plugin failed.")
                self.task_manager.fail(task_id, error_code=error_code, error_message=error_message)
                return {"ok": False, "error_code": error_code, "message": error_message}

            outputs = list(result.get("outputs", []))
            result_json = {
                "output_count": len(outputs),
                "artifacts": [o.get("artifact_path") for o in outputs if o.get("artifact_path")],
                "metrics": outputs[0].get("metrics", {}) if outputs else {},
                "summary": outputs[0].get("summary", "") if outputs else "",
            }
            self.task_manager.complete(task_id, result_json=result_json)
            return {"ok": True, "data": {"task_id": task_id, "output_count": len(outputs)}}
        except Exception as exc:
            self.task_manager.fail(task_id, error_code="ALGORITHM_RUNTIME_ERROR", error_message=str(exc))
            raise

    def _serialize_sample(self, sample: Sample) -> dict:
        return {
            "id": sample.id,
            "name": sample.name,
            "path": sample.file_path,
            "sample_path": sample.file_path,
            "relative_path": sample.relative_path,
            "status": sample.status,
            "metadata": sample.metadata_json,
            "labels": sample.labels_json or [],
        }
