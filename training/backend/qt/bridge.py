from __future__ import annotations

import shutil
from pathlib import Path

from .._compat import slots_dataclass, to_local_isoformat

from ..service_facade import BackendServiceFacade
from ..errors import NotFoundError, ValidationError


def _normalize_error(exc: Exception) -> dict:
    if isinstance(exc, NotFoundError):
        return {"ok": False, "error_code": "NOT_FOUND", "message": str(exc)}
    if isinstance(exc, ValidationError):
        return {"ok": False, "error_code": "VALIDATION_ERROR", "message": str(exc)}
    return {"ok": False, "error_code": "INTERNAL_ERROR", "message": str(exc)}


@slots_dataclass
class BackendBridge:
    facade: BackendServiceFacade

    def create_dataset(self, name: str, modality: str, description: str = "") -> dict:
        try:
            return self.facade.dataset_service.create_dataset(
                name,
                self._normalize_modality(modality),
                description,
            )
        except Exception as exc:
            return _normalize_error(exc)

    def update_dataset(self, dataset_id: int, name: str, type_name: str) -> dict:
        try:
            return self.facade.dataset_service.update_dataset(dataset_id, name, type_name)
        except Exception as exc:
            return _normalize_error(exc)

    def delete_dataset(self, dataset_id: int) -> dict:
        try:
            return self.facade.dataset_service.delete_dataset(dataset_id)
        except Exception as exc:
            return _normalize_error(exc)

    def get_datasets(self, page: int, page_size: int, status: str) -> dict:
        try:
            result = self.facade.dataset_service.get_datasets(page, page_size, status)
            result["items"] = [self.to_qml_dataset(item) for item in result.get("items", [])]
            return result
        except Exception as exc:
            return _normalize_error(exc)

    def get_dataset_samples(self, dataset_id: int, page: int, page_size: int, status: str) -> dict:
        try:
            result = self.facade.dataset_service.get_dataset_samples(dataset_id, page, page_size, status)
            result["items"] = [self.to_qml_sample(item) for item in result.get("items", [])]
            return result
        except Exception as exc:
            return _normalize_error(exc)

    def get_dataset_directory(self, dataset_id: int, path: str) -> dict:
        try:
            return self.facade.dataset_service.get_dataset_directory(dataset_id, path)
        except Exception as exc:
            return _normalize_error(exc)

    def get_dataset_preview_samples(self, dataset_id: int, limit: int, status: str) -> dict:
        try:
            result = self.facade.dataset_service.get_dataset_preview_samples(dataset_id, limit, status)
            result["items"] = [self.to_qml_sample(item) for item in result.get("items", [])]
            return result
        except Exception as exc:
            return _normalize_error(exc)

    def get_sample_preview(self, sample_id: int) -> dict:
        try:
            result = self.facade.dataset_service.get_sample_preview(sample_id)
            if result.get("ok") and "data" in result:
                result["data"] = self.to_qml_sample(result["data"])
            return result
        except Exception as exc:
            return _normalize_error(exc)

    def preview_file_by_path(self, file_path: str) -> dict:
        try:
            return self.facade.dataset_service.preview_file_by_path(file_path)
        except Exception as exc:
            return _normalize_error(exc)

    def get_dataset_stats(self, dataset_id: int) -> dict:
        try:
            return self.facade.dataset_service.get_dataset_stats(dataset_id)
        except Exception as exc:
            return _normalize_error(exc)

    def import_files(self, dataset_id: int, file_paths: list[str]) -> dict:
        try:
            return self.facade.dataset_service.import_files(dataset_id, file_paths)
        except Exception as exc:
            return _normalize_error(exc)

    def import_folder(self, dataset_id: int, folder_path: str, include_subfolders: bool) -> dict:
        try:
            return self.facade.dataset_service.import_folder(dataset_id, folder_path, include_subfolders)
        except Exception as exc:
            return _normalize_error(exc)

    def import_dataset_bundle(self, payload: dict) -> dict:
        try:
            result = self.facade.dataset_service.import_dataset_bundle(payload or {})
            if result.get("ok"):
                result["data"]["datasets"] = [self.to_qml_dataset(item) for item in result["data"].get("datasets", [])]
                if result["data"].get("train_dataset"):
                    result["data"]["train_dataset"] = self.to_qml_dataset(result["data"]["train_dataset"])
                if result["data"].get("test_dataset"):
                    result["data"]["test_dataset"] = self.to_qml_dataset(result["data"]["test_dataset"])
            return result
        except Exception as exc:
            return _normalize_error(exc)


    def get_system_stats(self) -> dict:
        try:
            return self.facade.dataset_service.get_system_stats()
        except Exception as exc:
            return _normalize_error(exc)

    def get_recent_activities(self, limit: int = 5) -> list[dict]:
        try:
            return self.facade.dataset_service.get_recent_activities(limit)
        except Exception:
            return []  # type: ignore[return-value]

    def get_data_type_distribution(self) -> dict:
        try:
            return self.facade.dataset_service.get_data_type_distribution()
        except Exception as exc:
            return _normalize_error(exc)


    def get_algorithms(self, category: str, modality: str) -> list[dict]:
        try:
            normalized_modality = self._normalize_modality(modality) if (modality or "").strip() else ""
            return self.facade.algorithm_service.get_algorithms(category, normalized_modality)
        except Exception:
            return []  # type: ignore[return-value]

    def create_algorithm(self, payload: dict) -> dict:
        try:
            return self.facade.algorithm_service.create_algorithm(payload)
        except Exception as exc:
            return _normalize_error(exc)

    def update_algorithm(self, algorithm_id: int, payload: dict) -> dict:
        try:
            return self.facade.algorithm_service.update_algorithm(algorithm_id, payload)
        except Exception as exc:
            return _normalize_error(exc)

    def delete_algorithm(self, algorithm_id: int) -> dict:
        try:
            return self.facade.algorithm_service.delete_algorithm(algorithm_id)
        except Exception as exc:
            return _normalize_error(exc)

    def set_algorithm_enabled(self, algorithm_id: int, enabled: bool) -> dict:
        try:
            return self.facade.algorithm_service.set_algorithm_enabled(algorithm_id, enabled)
        except Exception as exc:
            return _normalize_error(exc)

    def validate_algorithm(self, algorithm_id: int) -> dict:
        try:
            return self.facade.algorithm_service.validate_algorithm(algorithm_id)
        except Exception as exc:
            return _normalize_error(exc)

    def get_algorithm_bindings(self) -> dict:
        try:
            return self.facade.algorithm_service.get_bindings()
        except Exception as exc:
            return _normalize_error(exc)

    def save_algorithm_binding(self, training_key: str, evaluation_key: str) -> dict:
        try:
            return self.facade.algorithm_service.set_binding(training_key, evaluation_key)
        except Exception as exc:
            return _normalize_error(exc)

    def delete_algorithm_binding(self, training_key: str) -> dict:
        try:
            return self.facade.algorithm_service.delete_binding(training_key)
        except Exception as exc:
            return _normalize_error(exc)

    def get_tasks(self, task_type: str, status: str, page: int, page_size: int) -> dict:
        try:
            result = self.facade.task_repository.list_tasks(
                task_type=task_type or "",
                status=status or "",
                page=max(page, 1),
                page_size=max(page_size, 1),
            )
            result["items"] = [self._serialize_task(item) for item in result.get("items", [])]
            return result
        except Exception as exc:
            return _normalize_error(exc)

    def start_task(self, task_id: int) -> dict:
        try:
            return self.facade.task_manager.start(task_id)
        except Exception as exc:
            return _normalize_error(exc)

    def delete_task(self, task_id: int) -> dict:
        try:
            with self.facade.session_factory() as session:
                result = self.facade.task_repository.delete_task(session, task_id)
                if result is None:
                    return {"ok": False, "error_code": "NOT_FOUND", "message": f"Task {task_id} not found."}
                session.commit()
                return {"ok": True, "data": result}
        except Exception as exc:
            return _normalize_error(exc)

    def update_task_title(self, task_id: int, title: str) -> dict:
        try:
            clean_title = (title or "").strip()
            if not clean_title:
                raise ValidationError("Task title cannot be empty.")
            with self.facade.session_factory() as session:
                task = self.facade.task_repository.update_task_title(session, task_id, clean_title)
                if task is None:
                    return {"ok": False, "error_code": "NOT_FOUND", "message": f"Task {task_id} not found."}
                session.commit()
                return {"ok": True, "data": self.facade.task_repository._serialize_task(task, session=session)}
        except Exception as exc:
            return _normalize_error(exc)

    def cancel_task(self, task_id: int) -> dict:
        try:
            return self.facade.task_manager.cancel(task_id)
        except Exception as exc:
            return _normalize_error(exc)

    def get_task_logs(self, task_id: int, page: int, page_size: int) -> dict:
        try:
            result = self.facade.task_repository.list_task_logs(
                task_id, page=max(page, 1), page_size=max(page_size, 1)
            )
            result["items"] = [self._serialize_task_log(item) for item in result.get("items", [])]
            return result
        except Exception as exc:
            return _normalize_error(exc)

    def create_cleaning_task(self, dataset_id: int, algorithm_ids: list[int], parameters: dict) -> dict:
        try:
            return self.facade.cleaning_service.create_task(dataset_id, algorithm_ids, parameters)
        except Exception as exc:
            return _normalize_error(exc)

    def get_cleaning_tasks(self, dataset_id: int, status: str, page: int = 1, page_size: int = 100) -> dict:
        try:
            return self.get_tasks("cleaning", status, page, page_size)
        except Exception as exc:
            return _normalize_error(exc)

    def get_cleaning_suggestions(self, task_id: int, status: str, page: int, page_size: int) -> dict:
        try:
            return self.facade.cleaning_service.list_suggestions(task_id, status or None, page, page_size)
        except Exception as exc:
            return _normalize_error(exc)

    def approve_cleaning_suggestion(self, suggestion_id: int, action: str) -> dict:
        try:
            return self.facade.cleaning_service.handle_suggestion(suggestion_id, action)
        except Exception as exc:
            return _normalize_error(exc)

    def batch_approve_cleaning_suggestions(self, suggestion_ids: list[int], action: str) -> dict:
        try:
            return self.facade.cleaning_service.batch_handle_suggestions(suggestion_ids, action)
        except Exception as exc:
            return _normalize_error(exc)

    def store_cleaning_task_result(self, task_id: int, dataset_name: str) -> dict:
        try:
            return self.facade.cleaning_service.store_cleaned_dataset(task_id, dataset_name)
        except Exception as exc:
            return _normalize_error(exc)

    def run_cleaning_task(self, task_id: int) -> dict:
        try:
            self.facade.task_manager.start(task_id)
            return self.facade.cleaning_service.run_task(task_id)
        except Exception as exc:
            return _normalize_error(exc)

    def create_generation_task(
        self,
        source_dataset_id: int,
        target_dataset_id: int,
        algorithm_ids: list[int],
        parameters: dict,
        target_count: int,
    ) -> dict:
        try:
            return self.facade.generation_service.create_task(
                source_dataset_id, target_dataset_id, algorithm_ids, parameters, target_count
            )
        except Exception as exc:
            return _normalize_error(exc)

    def get_generation_tasks(self, dataset_id: int, status: str) -> dict:
        try:
            return self.get_tasks("generation", status, 1, 200)
        except Exception as exc:
            return _normalize_error(exc)

    def get_generation_outputs(self, task_id: int, status: str, page: int, page_size: int) -> dict:
        try:
            return self.facade.generation_service.list_outputs(task_id, status or None, page, page_size)
        except Exception as exc:
            return _normalize_error(exc)

    def run_generation_task(self, task_id: int) -> dict:
        try:
            self.facade.task_manager.start(task_id)
            return self.facade.generation_service.run_task(task_id)
        except Exception as exc:
            return _normalize_error(exc)

    def create_training_task(
        self,
        scenario_id: int,
        dataset_id: int,
        algorithm_id: int,
        parameters: dict,
    ) -> dict:
        try:
            return self.facade.training_service.create_task(
                scenario_id, dataset_id, algorithm_id, parameters
            )
        except Exception as exc:
            return _normalize_error(exc)

    def get_training_tasks(self, dataset_id: int, status: str) -> dict:
        try:
            return self.get_tasks("training", status, 1, 200)
        except Exception as exc:
            return _normalize_error(exc)

    def run_training_task(self, task_id: int) -> dict:
        try:
            self.facade.task_manager.start(task_id)
            return self.facade.training_service.run_task(task_id)
        except Exception as exc:
            return _normalize_error(exc)

    def import_test_set(self, dataset_name: str, folder_path: str) -> dict:
        try:
            return self.facade.dataset_service.import_folder_with_stage(
                dataset_name, folder_path, stage="test"
            )
        except Exception as exc:
            return _normalize_error(exc)

    def get_scenarios(self, modality: str = "") -> list[dict]:
        try:
            return self.facade.evaluation_service.list_scenarios(modality or None)
        except Exception:
            return []  # type: ignore[return-value]

    def create_evaluation_task(
        self,
        scenario_id: int,
        baseline_dataset_id: int,
        target_dataset_id: int,
        algorithm_id: int,
        parameters: dict,
    ) -> dict:
        try:
            return self.facade.evaluation_service.create_task(
                scenario_id, baseline_dataset_id, target_dataset_id, algorithm_id, parameters
            )
        except Exception as exc:
            return _normalize_error(exc)

    def get_evaluation_tasks(self, status: str) -> dict:
        try:
            return self.get_tasks("evaluation", status, 1, 200)
        except Exception as exc:
            return _normalize_error(exc)

    def get_evaluation_results(self, task_id: int) -> dict:
        try:
            return self.facade.evaluation_service.get_results(task_id)
        except Exception as exc:
            return _normalize_error(exc)

    def export_evaluation_report(self, task_id: int, output_path: str) -> dict:
        try:
            return self.facade.evaluation_service.export_report(task_id, output_path)
        except Exception as exc:
            return _normalize_error(exc)

    def run_evaluation_task(self, task_id: int) -> dict:
        try:
            self.facade.task_manager.start(task_id)
            return self.facade.evaluation_service.run_task(task_id)
        except Exception as exc:
            return _normalize_error(exc)

    def get_system_status(self) -> dict:
        try:
            return self.facade.settings_service.get_system_status()
        except Exception as exc:
            return _normalize_error(exc)

    def get_settings(self) -> dict:
        try:
            return self.facade.settings_service.get_settings()
        except Exception as exc:
            return _normalize_error(exc)

    def update_setting(self, key: str, value) -> dict:
        try:
            return self.facade.settings_service.update_setting(key, value)
        except Exception as exc:
            return _normalize_error(exc)

    def get_setting(self, key: str):
        try:
            return self.facade.settings_service.get_setting(key)
        except Exception:
            return None

    def ensure_default_settings(self) -> None:
        self.facade.settings_service.ensure_defaults()

    def seed_default_algorithms(self) -> None:
        from ..seed_data import DEFAULT_ALGORITHMS, DEFAULT_BINDINGS
        existing = self.facade.algorithm_service.get_algorithms("", "")
        existing_map = {a["key"]: a for a in existing}
        for algo in DEFAULT_ALGORITHMS:
            if algo["key"] in existing_map:
                continue  # 已有算法不覆盖，保留用户修改
            else:
                self.facade.algorithm_service.create_algorithm(dict(algo))
        self._repair_training_validation_rules(existing_map)
        self._merge_legacy_algorithm_aliases()

    def _repair_training_validation_rules(self, existing_map: dict) -> None:
        """修复已有训练算法的 validation_rules_json：
        若为空 {} 但种子数据中存在对应的 scenario_key，则补齐。"""
        from ..seed_data import DEFAULT_ALGORITHMS
        from ..models import Algorithm

        seed_vr_map = {}
        for algo in DEFAULT_ALGORITHMS:
            vr_json = algo.get("validation_rules_json")
            if algo.get("category") == "training" and isinstance(vr_json, dict) and vr_json.get("scenario_key"):
                seed_vr_map[algo["key"]] = vr_json

        if not seed_vr_map:
            return

        with self.facade.session_factory() as session:
            for algo_key, seed_vr in seed_vr_map.items():
                existing = session.query(Algorithm).filter(Algorithm.key == algo_key).first()
                if existing is None:
                    continue
                current_vr = existing.validation_rules_json or {}
                # 仅在当前值为空或缺少 scenario_key 时修复
                if not isinstance(current_vr, dict) or not current_vr.get("scenario_key"):
                    existing.validation_rules_json = seed_vr
            session.commit()

    def _merge_legacy_algorithm_aliases(self) -> None:
        from ..models import (
            Algorithm,
            AlgorithmParameter,
            CleaningSuggestion,
            EvaluationResult,
            GenerationOutput,
            Task,
        )

        aliases = {"图片低分辨率清洗": "cleaning.image_resolution_filter"}
        with self.facade.session_factory() as session:
            for legacy_key, target_key in aliases.items():
                legacy = session.query(Algorithm).filter(Algorithm.key == legacy_key).first()
                target = session.query(Algorithm).filter(Algorithm.key == target_key).first()
                if legacy is None or target is None or legacy.id == target.id:
                    continue

                for model in (Task, CleaningSuggestion, GenerationOutput, EvaluationResult):
                    session.query(model).filter(model.algorithm_id == legacy.id).update(
                        {model.algorithm_id: target.id},
                        synchronize_session=False,
                    )
                self._replace_algorithm_id_in_task_payloads(session, legacy.id, target.id)
                session.query(AlgorithmParameter).filter(AlgorithmParameter.algorithm_id == legacy.id).delete(
                    synchronize_session=False
                )
                session.delete(legacy)
            session.commit()

    def _replace_algorithm_id_in_task_payloads(self, session, legacy_id: int, target_id: int) -> None:
        from ..models import Task

        for task in session.query(Task).all():
            changed = False
            parameters = dict(task.parameters_json or {})
            payload = dict(task.payload_json or {})
            for container in (parameters, payload):
                algorithm_ids = list(container.get("algorithm_ids", []))
                replaced_ids = [target_id if item == legacy_id else item for item in algorithm_ids]
                if replaced_ids != algorithm_ids:
                    container["algorithm_ids"] = replaced_ids
                    changed = True
            if changed:
                task.parameters_json = parameters
                task.payload_json = payload

        # 播种默认训练→评估绑定
        existing_bindings = self.facade.algorithm_service.get_bindings()
        for training_key, eval_key in DEFAULT_BINDINGS.items():
            if training_key not in existing_bindings:
                try:
                    self.facade.algorithm_service.set_binding(training_key, eval_key)
                except Exception:
                    pass  # 绑定失败的静默跳过（算法可能尚未注册）

    def reflect_parameters(self, script_path: str) -> dict:
        """从 .py 脚本反射参数列表。"""
        try:
            return self.facade.algorithm_service.plugin_runner.reflect_parameters(script_path)
        except Exception as exc:
            return _normalize_error(exc)

    def import_plugin_file(self, source_path: str) -> dict:
        """将用户上传的 .py 文件复制到 plugins/user/ 目录。"""
        try:
            src = Path(source_path).resolve()
            if not src.exists():
                return {"ok": False, "error_code": "NOT_FOUND", "message": f"源文件不存在: {src}"}
            plugins_user_dir = self.facade.paths.plugins_dir / "user"
            plugins_user_dir.mkdir(parents=True, exist_ok=True)
            dest = plugins_user_dir / src.name
            if src == dest.resolve():
                return {"ok": True, "path": str(dest)}
            if dest.exists():
                dest.unlink()
            shutil.copy2(src, dest)
            return {"ok": True, "path": str(dest)}
        except Exception as exc:
            return _normalize_error(exc)

    def download_algorithm_plugin_spec(self, target_path: str) -> dict:
        try:
            src = Path(__file__).resolve().parents[2] / "docs" / "ISG 算法插件开发规范 v1.0.pdf"
            if not src.is_file():
                return {"ok": False, "error_code": "NOT_FOUND", "message": f"未找到插件规范文档: {src}"}

            dest = Path(target_path).expanduser()
            if dest.suffix.lower() != ".pdf":
                dest = dest.with_suffix(".pdf")
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest)
            return {"ok": True, "path": str(dest)}
        except Exception as exc:
            return _normalize_error(exc)

    def get_operation_logs(self, page: int, page_size: int, resource_type: str = "") -> dict:
        try:
            return self.facade.settings_service.list_operation_logs(page, page_size, resource_type)
        except Exception as exc:
            return _normalize_error(exc)

    # ── 边缘设备管理 + OTA ──────────────────────────────────

    def register_edge_device(self, device_id: str, name: str, host: str,
                             grpc_port: int = 50051, tags: dict = None) -> dict:
        try:
            return self.facade.edge_service.register_device(
                device_id, name, host, grpc_port, tags
            )
        except Exception as exc:
            return _normalize_error(exc)

    def get_edge_device(self, device_id: str) -> dict:
        try:
            return self.facade.edge_service.get_device(device_id)
        except Exception as exc:
            return _normalize_error(exc)

    def list_edge_devices(self, status: str = "") -> list[dict]:
        try:
            return self.facade.edge_service.list_devices(status or None)
        except Exception:
            return []

    def unregister_edge_device(self, device_id: str) -> dict:
        try:
            return self.facade.edge_service.unregister_device(device_id)
        except Exception as exc:
            return _normalize_error(exc)

    def switch_device_scene(self, device_id: str, scene: str) -> dict:
        try:
            return self.facade.edge_service.switch_scene(device_id, scene)
        except Exception as exc:
            return _normalize_error(exc)

    def push_model_to_device(self, device_id: str, model_path: str,
                             model_version: str = "") -> dict:
        try:
            return self.facade.edge_service.push_model(
                device_id, model_path, model_version=model_version or None
            )
        except Exception as exc:
            return _normalize_error(exc)

    def deploy_model_to_devices(self, model_path: str, device_ids: list,
                                model_version: str = "") -> dict:
        try:
            return self.facade.edge_service.deploy_to_devices(
                model_path, device_ids, model_version=model_version or None
            )
        except Exception as exc:
            return _normalize_error(exc)

    def rollback_device(self, device_id: str, target: str = "model") -> dict:
        try:
            return self.facade.edge_service.rollback(device_id, target)
        except Exception as exc:
            return _normalize_error(exc)

    def restart_device(self, device_id: str) -> dict:
        try:
            return self.facade.edge_service.restart_device(device_id)
        except Exception as exc:
            return _normalize_error(exc)

    def register_model_version(self, name: str, version: str,
                               model_type: str, scene: str,
                               file_path: str, quantization: str = "fp16",
                               notes: str = "") -> dict:
        try:
            return self.facade.edge_service.register_model_version(
                name=name, version=version, model_type=model_type,
                scene=scene, file_path=file_path,
                quantization=quantization, notes=notes,
            )
        except Exception as exc:
            return _normalize_error(exc)

    def list_model_versions(self, scene: str = "", model_type: str = "") -> list[dict]:
        try:
            return self.facade.edge_service.list_model_versions(
                scene=scene or None, model_type=model_type or None
            )
        except Exception:
            return []

    def on_device_heartbeat(self, device_id: str, telemetry: dict) -> dict:
        try:
            return self.facade.edge_service.on_heartbeat(device_id, telemetry)
        except Exception as exc:
            return _normalize_error(exc)

    def push_onnx_to_device(self, device_id: str, onnx_path: str,
                            model_version: str = "") -> dict:
        """推送 ONNX 到设备, 板子端做 ONNX→RKNN 转换 (方案B)"""
        try:
            return self.facade.edge_service.push_onnx(
                device_id, onnx_path, model_version=model_version or None
            )
        except Exception as exc:
            return _normalize_error(exc)


    def _normalize_modality(self, modality: str) -> str:
        return {
            "\u56fe\u50cf": "image",
            "\u6587\u672c": "text",
            "\u97f3\u9891": "audio",
            "\u8868\u683c": "tabular",
            "\u89c6\u9891": "video",
            "\u591a\u6a21\u6001": "multimodal",
            "\u5176\u4ed6": "other",
        }.get((modality or "").strip(), (modality or "").strip() or "other")

    def to_qml_dataset(self, item: dict) -> dict:
        size_bytes = int(item.get("size_bytes") or 0)
        stage = self._dataset_stage(item)
        return {
            **item,
            "type": self._qml_modality_label(item.get("modality", "")),
            "sampleCount": item.get("total_samples", 0),
            "size": self._format_size(size_bytes),
            "stage": stage,
            "stageLabel": self._dataset_stage_label(stage),
        }

    def to_qml_sample(self, item: dict) -> dict:
        size_bytes = int(item.get("size_bytes") or 0)
        return {
            **item,
            "type": self._qml_modality_label(item.get("modality", "")),
            "size": self._format_size(size_bytes),
            "modified": item.get("updated_at", ""),
        }

    def _qml_modality_label(self, modality: str) -> str:
        return {
            "image": "\u56fe\u50cf",
            "text": "\u6587\u672c",
            "audio": "\u97f3\u9891",
            "tabular": "\u8868\u683c",
            "video": "\u89c6\u9891",
            "multimodal": "\u591a\u6a21\u6001",
        }.get(modality, modality or "\u5176\u4ed6")

    def _dataset_stage(self, item: dict) -> str:
        status = str(item.get("status", "")).lower()
        tags = {str(tag).lower() for tag in (item.get("tags") or [])}
        if status == "deleted" or "deleted" in tags:
            return "deleted"
        if status == "cleaned" or "cleaned" in tags:
            return "cleaned"
        if status == "generated" or "generated" in tags:
            return "generated"
        if status in {"imported", "created", "raw", "test"} or "imported" in tags or "raw" in tags or "test" in tags:
            return "raw"
        return status or "raw"

    def _dataset_stage_label(self, stage: str) -> str:
        return {
            "raw": "\u539f\u59cb\u6570\u636e\u96c6",
            "cleaned": "\u6e05\u6d17\u6570\u636e\u96c6",
            "generated": "\u751f\u6210\u6570\u636e\u96c6",
            "deleted": "\u5df2\u5220\u9664",
        }.get(stage, "\u539f\u59cb\u6570\u636e\u96c6")

    def _format_size(self, size_bytes: int) -> str:
        if size_bytes >= 1024 * 1024 * 1024:
            return f"{size_bytes / (1024 * 1024 * 1024):.1f} GB"
        if size_bytes >= 1024 * 1024:
            return f"{size_bytes / (1024 * 1024):.1f} MB"
        if size_bytes >= 1024:
            return f"{size_bytes / 1024:.1f} KB"
        return f"{size_bytes} B"

    def _serialize_task(self, task) -> dict:
        if isinstance(task, dict):
            return {
                "id": task.get("id"),
                "task_type": task.get("task_type", ""),
                "status": task.get("status", ""),
                "title": task.get("title") or "",
                "progress": task.get("progress", 0.0),
                "progress_message": task.get("progress_message") or "",
                "source_dataset_id": task.get("source_dataset_id"),
                "target_dataset_id": task.get("target_dataset_id"),
                "source_dataset_name": task.get("source_dataset_name") or "",
                "source_dataset_path": task.get("source_dataset_path") or "",
                "target_dataset_name": task.get("target_dataset_name") or "",
                "target_dataset_path": task.get("target_dataset_path") or "",
                "algorithm_id": task.get("algorithm_id"),
                "error_message": task.get("error_message") or "",
                "output_dir": task.get("output_dir") or "",
                "parameters": task.get("parameters_json") or task.get("parameters") or {},
                "payload": task.get("payload_json") or task.get("payload") or {},
                "result": task.get("result_json") or task.get("result") or {},
                "created_at": task.get("created_at") or "",
            }
        return {
            "id": task.id,
            "task_type": task.task_type,
            "status": task.status,
            "progress": task.progress,
            "progress_message": task.progress_message or "",
            "source_dataset_id": task.source_dataset_id,
            "target_dataset_id": task.target_dataset_id,
            "algorithm_id": task.algorithm_id,
            "error_message": task.error_message or "",
            "parameters": task.parameters_json or {},
            "payload": task.payload_json or {},
            "result": task.result_json or {},
            "created_at": to_local_isoformat(task.created_at),
        }

    def _serialize_task_log(self, item) -> dict:
        if isinstance(item, dict):
            return {
                "id": item.get("id"),
                "task_id": item.get("task_id"),
                "level": item.get("level", ""),
                "message": item.get("message", ""),
                "payload": item.get("payload_json") or item.get("payload") or {},
                "created_at": item.get("created_at") or "",
            }
        return {
            "id": item.id,
            "task_id": item.task_id,
            "level": item.level,
            "message": item.message,
            "payload": item.payload_json,
            "created_at": to_local_isoformat(item.created_at),
        }

    # ── MQTT 配置 ─────────────────────────────────────────────

    def get_mqtt_config(self) -> dict:
        """获取当前 MQTT 配置 (broker 地址和端口)"""
        try:
            host = self.facade.settings_service.get_setting("mqtt.broker_host")
            port = self.facade.settings_service.get_setting("mqtt.broker_port")
            return {
                "ok": True,
                "data": {
                    "broker_host": host or "debian10.local",
                    "broker_port": int(port) if port else 1883,
                },
            }
        except Exception as exc:
            return _normalize_error(exc)

    def update_mqtt_config(self, broker_host: str, broker_port: int) -> dict:
        """更新 MQTT 配置并持久化"""
        try:
            # 保存到设置
            self.facade.settings_service.update_setting("mqtt.broker_host", broker_host)
            self.facade.settings_service.update_setting("mqtt.broker_port", broker_port)
            self.facade.log_repository.add(
                self.facade.session_factory(),
                level="info",
                action="update_mqtt_config",
                resource_type="mqtt",
                message=f"MQTT config updated: {broker_host}:{broker_port}",
            )
            return {
                "ok": True,
                "data": {
                    "broker_host": broker_host,
                    "broker_port": broker_port,
                },
            }
        except Exception as exc:
            return _normalize_error(exc)
