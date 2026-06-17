from __future__ import annotations

import json
from dataclasses import field
from .._compat import slots_dataclass
from pathlib import Path

from ..errors import NotFoundError, ValidationError
from ..models import Algorithm, Dataset, EvaluationResult, EvaluationScenario, Sample
from ..plugins import PluginRunner
from .base import ServiceBase


@slots_dataclass
class EvaluationService(ServiceBase):
    task_manager: object
    task_repository: object
    algorithm_repository: object
    dataset_repository: object
    plugin_runner: PluginRunner = field(default_factory=PluginRunner)

    _DEFAULT_SCENARIOS = (
        {
            "key": "underwater_target_detection_recognition",
            "name": "水下目标检测与识别",
            "modality": "multimodal",
            "description": "用于水下声呐目标检测、目标识别与开放集识别的数据增强前后对比仿真。",
            "baseline_models_json": ["sonar-oltr", "multi-agent-simulation"],
            "metric_schema_json": ["coordination_score", "coverage_score", "response_score", "overall_score"],
        },
        {
            "key": "ship_target_recognition_tracking",
            "name": "舰船目标识别与跟踪",
            "modality": "multimodal",
            "description": "用于舰船目标识别、跟踪与态势感知任务的应用仿真评估。",
            "baseline_models_json": ["ship-recognition-tracking", "multi-agent-simulation"],
            "metric_schema_json": ["coordination_score", "coverage_score", "response_score", "overall_score"],
        },
        {
            "key": "system_health_fault_diagnosis",
            "name": "系统健康状态预估与故障诊断",
            "modality": "multimodal",
            "description": "用于系统健康状态预测、故障诊断和运维决策的数据评估。",
            "baseline_models_json": ["health-fault-diagnosis", "multi-agent-simulation"],
            "metric_schema_json": ["coordination_score", "coverage_score", "response_score", "overall_score"],
        },
        {
            "key": "intelligent_decision_command_control",
            "name": "智能决策与指挥控制",
            "modality": "multimodal",
            "description": "用于智能决策、任务规划与指挥控制链路的多智能体仿真评估。",
            "baseline_models_json": ["decision-command-control", "multi-agent-simulation"],
            "metric_schema_json": ["coordination_score", "coverage_score", "response_score", "overall_score"],
        },
        {
            "key": "multimodal_data_fusion",
            "name": "多模态数据融合",
            "modality": "multimodal",
            "description": "用于图像、文本、音频、表格等多模态数据融合质量与覆盖能力评估。",
            "baseline_models_json": ["multimodal-fusion", "multi-agent-simulation"],
            "metric_schema_json": ["coordination_score", "coverage_score", "response_score", "overall_score"],
        },
    )

    def list_scenarios(self, modality: str | None = None) -> list[dict]:
        with self.session_factory() as session:
            if self._seed_scenarios(session):
                session.commit()
            query = session.query(EvaluationScenario)
            query = query.filter(EvaluationScenario.status != "retired")
            if modality:
                query = query.filter(EvaluationScenario.modality.in_([modality, "multimodal"]))
            scenarios = query.order_by(EvaluationScenario.created_at.asc(), EvaluationScenario.id.asc()).all()
            return [self._serialize_scenario(item) for item in scenarios]

    def create_task(
        self,
        scenario_id: int,
        baseline_dataset_id: int,
        target_dataset_id: int,
        algorithm_id: int,
        parameters: dict,
    ) -> dict:
        with self.session_factory() as session:
            self._seed_scenarios(session)
            scenario = session.query(EvaluationScenario).filter(EvaluationScenario.id == scenario_id).first()
            if scenario is None:
                raise NotFoundError(f"Scenario {scenario_id} not found.")

            baseline_dataset = session.query(Dataset).filter(Dataset.id == baseline_dataset_id).first()
            target_dataset = session.query(Dataset).filter(Dataset.id == target_dataset_id).first()
            if baseline_dataset is None:
                raise NotFoundError(f"Dataset {baseline_dataset_id} not found.")
            if target_dataset is None:
                raise NotFoundError(f"Dataset {target_dataset_id} not found.")
            if baseline_dataset.is_deleted or baseline_dataset.status == "deleted":
                raise ValidationError("Baseline dataset must be active for evaluation.")
            if target_dataset.is_deleted or target_dataset.status == "deleted":
                raise ValidationError("Target dataset must be active for evaluation.")
            if baseline_dataset.modality != target_dataset.modality:
                raise ValidationError("Baseline and target dataset modalities must match.")
            if scenario.modality not in {baseline_dataset.modality, "multimodal"}:
                raise ValidationError("Scenario modality must match the dataset modality.")

            algorithm = self.algorithm_repository.get_algorithm(session, algorithm_id)
            if not algorithm:
                raise NotFoundError(f"Algorithm {algorithm_id} not found.")
            if algorithm.category not in ("evaluation", "training"):
                raise ValidationError("Algorithm must be an evaluation or training algorithm.")
            if algorithm.status != "enabled":
                raise ValidationError("Algorithm must be enabled.")
            if algorithm.modality not in {baseline_dataset.modality, "multimodal"}:
                raise ValidationError("Algorithm modality must match the dataset modality.")

            task = self.task_repository.create_task(
                session,
                task_type="evaluation",
                status="pending",
                title=f"Evaluation task for target dataset {target_dataset.id}",
                source_dataset_id=baseline_dataset.id,
                target_dataset_id=target_dataset.id,
                algorithm_id=algorithm.id,
                scenario_id=scenario.id,
                parameters_json=parameters or {},
                payload_json={
                    "scenario_id": scenario.id,
                    "baseline_dataset_id": baseline_dataset.id,
                    "target_dataset_id": target_dataset.id,
                    "algorithm_id": algorithm.id,
                },
                result_json={},
            )
            self.task_repository.add_task_log(session, task_id=task.id, level="info", message="Evaluation task created")
            session.commit()
            return {"ok": True, "data": {"task_id": task.id, "status": task.status}}

    def run_task(self, task_id: int, context=None) -> dict:
        with self.session_factory() as session:
            self._seed_scenarios(session)
            task = self.task_repository.get_task_model(session, task_id)
            if task is None:
                raise NotFoundError(f"Task {task_id} not found.")
            if task.status != "running":
                raise ValidationError(f"Evaluation task {task_id} cannot run from status '{task.status}'.")

            scenario = session.query(EvaluationScenario).filter(EvaluationScenario.id == task.scenario_id).first()
            baseline_dataset = session.query(Dataset).filter(Dataset.id == task.source_dataset_id).first()
            target_dataset = session.query(Dataset).filter(Dataset.id == task.target_dataset_id).first()
            if scenario is None:
                raise NotFoundError(f"Scenario {task.scenario_id} not found.")
            if baseline_dataset is None or baseline_dataset.is_deleted or baseline_dataset.status == "deleted":
                raise ValidationError("Baseline dataset is not active.")
            if target_dataset is None or target_dataset.is_deleted or target_dataset.status == "deleted":
                raise ValidationError("Target dataset is not active.")

            algorithm = self.algorithm_repository.get_algorithm(session, task.algorithm_id)
            if not algorithm:
                raise NotFoundError(f"Algorithm {task.algorithm_id} not found.")
            if algorithm.category not in ("evaluation", "training"):
                raise ValidationError("Algorithm must be an evaluation or training algorithm.")
            if algorithm.status != "enabled":
                raise ValidationError("Algorithm must be enabled.")

            baseline_samples = (
                session.query(Sample)
                .filter(Sample.dataset_id == baseline_dataset.id, Sample.status != "deleted")
                .order_by(Sample.id.asc())
                .all()
            )
            target_samples = (
                session.query(Sample)
                .filter(Sample.dataset_id == target_dataset.id, Sample.status != "deleted")
                .order_by(Sample.id.asc())
                .all()
            )

        plugin_context = context or self.task_manager.build_context(task_id)
        try:
            payload = {
                "task_id": task_id,
                "algorithm_key": algorithm.key,
                "category": "evaluation",
                "modality": scenario.modality,
                "parameters": task.parameters_json,
                "scenario": self._serialize_scenario(scenario),
                "input": {
                    "baseline_dataset": {
                        "id": baseline_dataset.id,
                        "name": baseline_dataset.name,
                        "modality": baseline_dataset.modality,
                        "path": baseline_dataset.storage_path,
                        "samples": [self._serialize_sample(sample) for sample in baseline_samples],
                    },
                    "target_dataset": {
                        "id": target_dataset.id,
                        "name": target_dataset.name,
                        "modality": target_dataset.modality,
                        "path": target_dataset.storage_path,
                        "samples": [self._serialize_sample(sample) for sample in target_samples],
                    },
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
                error_message = result.get("message", "Evaluation plugin failed.")
                self.task_manager.fail(task_id, error_code=error_code, error_message=error_message)
                return {"ok": False, "error_code": error_code, "message": error_message}

            persisted_results = self._persist_results(
                task_id=task_id,
                scenario_id=scenario.id,
                baseline_dataset_id=baseline_dataset.id,
                target_dataset_id=target_dataset.id,
                algorithm_id=algorithm.id,
                result=result,
            )
            self.task_manager.complete(task_id, result_json={"result_count": len(persisted_results)})
            return {"ok": True, "data": {"task_id": task_id, "result_count": len(persisted_results)}}
        except Exception as exc:
            self.task_manager.fail(task_id, error_code="ALGORITHM_RUNTIME_ERROR", error_message=str(exc))
            raise

    def get_results(self, task_id: int) -> dict:
        with self.session_factory() as session:
            rows = (
                session.query(EvaluationResult)
                .filter(EvaluationResult.task_id == task_id)
                .order_by(EvaluationResult.created_at.asc(), EvaluationResult.id.asc())
                .all()
            )
            return {"ok": True, "data": {"task_id": task_id, "items": [self._serialize_result(item) for item in rows]}}

    def export_report(self, task_id: int, output_path: str) -> dict:
        result_payload = self.get_results(task_id)["data"]
        output_file = Path(output_path)
        output_file.parent.mkdir(parents=True, exist_ok=True)
        output_file.write_text(json.dumps(result_payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return {"ok": True, "data": {"task_id": task_id, "output_path": str(output_file), "result_count": len(result_payload["items"])}}

    def _seed_scenarios(self, session) -> bool:
        desired_by_key = {payload["key"]: payload for payload in self._DEFAULT_SCENARIOS}
        changed = False
        for scenario in session.query(EvaluationScenario).all():
            if scenario.key not in desired_by_key and scenario.status == "seeded":
                scenario.status = "retired"
                changed = True
            elif scenario.key in desired_by_key:
                payload = desired_by_key[scenario.key]
                for field_name, field_value in payload.items():
                    if getattr(scenario, field_name) != field_value:
                        setattr(scenario, field_name, field_value)
                        changed = True
                if scenario.status == "retired":
                    scenario.status = "seeded"
                    changed = True
        existing_keys = {item.key for item in session.query(EvaluationScenario.key).all()}
        created = False
        for payload in self._DEFAULT_SCENARIOS:
            if payload["key"] in existing_keys:
                continue
            session.add(EvaluationScenario(status="seeded", **payload))
            created = True
        session.flush()
        return created or changed

    def _persist_results(
        self,
        *,
        task_id: int,
        scenario_id: int,
        baseline_dataset_id: int,
        target_dataset_id: int,
        algorithm_id: int,
        result: dict,
    ) -> list[dict]:
        persisted: list[dict] = []
        if "results" in result:
            result_items = list(result.get("results") or [])
        else:
            result_items = [
                {
                    "model_name": result.get("model_name", "default-evaluator"),
                    "metrics": result.get("metrics", {}),
                    "summary": result.get("summary", ""),
                    "artifacts": result.get("artifacts", []),
                }
            ]

        with self.session_factory() as session:
            for item in result_items:
                row = EvaluationResult(
                    task_id=task_id,
                    scenario_id=scenario_id,
                    baseline_dataset_id=baseline_dataset_id,
                    target_dataset_id=target_dataset_id,
                    algorithm_id=algorithm_id,
                    model_name=item.get("model_name", "default-evaluator"),
                    metrics_json=item.get("metrics", {}),
                    summary=item.get("summary", ""),
                    artifacts_json=item.get("artifacts", []),
                )
                session.add(row)
                session.flush()
                persisted.append(self._serialize_result(row))
            self.task_repository.add_task_log(
                session,
                task_id=task_id,
                level="info",
                message="Evaluation results persisted",
                payload_json={"result_count": len(persisted)},
            )
            session.commit()
        return persisted

    def _serialize_scenario(self, scenario: EvaluationScenario) -> dict:
        return {
            "id": scenario.id,
            "key": scenario.key,
            "name": scenario.name,
            "modality": scenario.modality,
            "description": scenario.description,
            "baseline_models": scenario.baseline_models_json,
            "metric_schema": scenario.metric_schema_json,
            "status": scenario.status,
        }

    def _serialize_sample(self, sample: Sample) -> dict:
        return {
            "id": sample.id,
            "name": sample.name,
            "path": sample.file_path,
            "status": sample.status,
            "metadata": sample.metadata_json,
            "labels": sample.labels_json or [],
        }

    def _serialize_result(self, row: EvaluationResult) -> dict:
        return {
            "id": row.id,
            "task_id": row.task_id,
            "scenario_id": row.scenario_id,
            "baseline_dataset_id": row.baseline_dataset_id,
            "target_dataset_id": row.target_dataset_id,
            "algorithm_id": row.algorithm_id,
            "model_name": row.model_name,
            "metrics": row.metrics_json,
            "summary": row.summary,
            "artifacts": row.artifacts_json,
        }
