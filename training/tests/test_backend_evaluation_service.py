from pathlib import Path

import pytest


def build_services(tmp_path):
    from backend import BackendPaths, BackendServiceFacade, create_backend_engine, create_session_factory, initialize_backend_database

    paths = BackendPaths(tmp_path / "backend-root")
    engine = create_backend_engine(paths.database_path)
    initialize_backend_database(engine)
    session_factory = create_session_factory(engine)
    facade = BackendServiceFacade.build(paths=paths, session_factory=session_factory)
    return facade, paths


def create_text_dataset(facade, tmp_path, name):
    source_file = tmp_path / f"{name}.txt"
    source_file.write_text(f"hello {name}", encoding="utf-8")
    dataset = facade.dataset_service.create_dataset(name, "text", "")
    facade.dataset_service.import_files(dataset["data"]["id"], [str(source_file)])
    return dataset


def create_evaluation_algorithm(service, tmp_path, key="text_eval", body=None):
    plugin_file = tmp_path / f"{key}.py"
    plugin_file.write_text(
        body
        or (
            "def run(payload, context):\n"
            "    baseline = payload['input']['baseline_dataset']['samples']\n"
            "    target = payload['input']['target_dataset']['samples']\n"
            "    context.set_progress(100.0, 'done')\n"
            "    return {'ok': True, 'model_name': 'demo-evaluator', 'metrics': {'baseline_count': len(baseline), 'target_count': len(target)}, 'summary': 'ok', 'artifacts': []}\n"
        ),
        encoding="utf-8",
    )
    return service.create_algorithm(
        {
            "key": key,
            "name": key,
            "category": "evaluation",
            "modality": "text",
            "entry_type": "python_function",
            "script_path": str(plugin_file),
            "callable_name": "run",
            "input_contract": {"dataset_required": True},
            "output_contract": {"produces": ["evaluation_results"]},
            "parameters": [],
        }
    )["data"]["id"]


def test_evaluation_service_lists_seed_scenarios(tmp_path):
    from backend.models import EvaluationScenario

    facade, _paths = build_services(tmp_path)

    scenarios = facade.evaluation_service.list_scenarios("")
    with facade.session_factory() as session:
        persisted_count = session.query(EvaluationScenario).count()

    assert [item["name"] for item in scenarios] == [
        "水下目标检测与识别",
        "舰船目标识别与跟踪",
        "系统健康状态预估与故障诊断",
        "智能决策与指挥控制",
        "多模态数据融合",
    ]
    assert [item["key"] for item in scenarios] == [
        "underwater_target_detection_recognition",
        "ship_target_recognition_tracking",
        "system_health_fault_diagnosis",
        "intelligent_decision_command_control",
        "multimodal_data_fusion",
    ]
    assert not any(item["key"].startswith("seed.") for item in scenarios)
    assert persisted_count == 5


def test_evaluation_service_retires_legacy_seed_scenarios(tmp_path):
    from backend.models import EvaluationScenario

    facade, _paths = build_services(tmp_path)
    with facade.session_factory() as session:
        session.add(
            EvaluationScenario(
                key="seed.image.default",
                name="Seed Image Evaluation",
                modality="image",
                description="legacy",
                baseline_models_json=[],
                metric_schema_json=[],
                status="seeded",
            )
        )
        session.commit()

    scenarios = facade.evaluation_service.list_scenarios("")
    with facade.session_factory() as session:
        legacy = session.query(EvaluationScenario).filter(EvaluationScenario.key == "seed.image.default").first()

    assert "Seed Image Evaluation" not in [item["name"] for item in scenarios]
    assert legacy.status == "retired"


def test_evaluation_service_runs_and_exports_report(tmp_path):
    facade, _paths = build_services(tmp_path)
    baseline = create_text_dataset(facade, tmp_path, "baseline")
    target = create_text_dataset(facade, tmp_path, "target")
    algorithm_id = create_evaluation_algorithm(facade.algorithm_service, tmp_path)
    scenario = facade.evaluation_service.list_scenarios("")[0]

    created = facade.evaluation_service.create_task(
        scenario["id"],
        baseline["data"]["id"],
        target["data"]["id"],
        algorithm_id,
        {"threshold": 1},
    )
    task_id = created["data"]["task_id"]
    report_path = tmp_path / "report.json"

    facade.task_manager.start(task_id)
    run_result = facade.evaluation_service.run_task(task_id)
    results = facade.evaluation_service.get_results(task_id)
    export_result = facade.evaluation_service.export_report(task_id, str(report_path))
    task = facade.task_repository.get_task(task_id)

    assert run_result["ok"] is True
    assert task["status"] == "completed"
    assert results["data"]["items"][0]["model_name"] == "demo-evaluator"
    assert report_path.is_file()
    assert export_result["ok"] is True


def test_evaluation_service_cancels_before_plugin_execution(tmp_path):
    facade, _paths = build_services(tmp_path)
    baseline = create_text_dataset(facade, tmp_path, "baseline-cancel")
    target = create_text_dataset(facade, tmp_path, "target-cancel")
    algorithm_id = create_evaluation_algorithm(
        facade.algorithm_service,
        tmp_path,
        key="cancel_eval",
        body=(
            "def run(payload, context):\n"
            "    if context.is_cancel_requested():\n"
            "        return {'ok': False, 'error_code': 'CANCELLED', 'message': 'cancelled'}\n"
            "    return {'ok': True, 'model_name': 'demo', 'metrics': {}, 'summary': '', 'artifacts': []}\n"
        ),
    )
    scenario = facade.evaluation_service.list_scenarios("")[0]

    created = facade.evaluation_service.create_task(
        scenario["id"],
        baseline["data"]["id"],
        target["data"]["id"],
        algorithm_id,
        {},
    )
    task_id = created["data"]["task_id"]

    facade.task_manager.start(task_id)
    cancel_result = facade.task_manager.cancel(task_id)
    run_result = facade.evaluation_service.run_task(task_id)
    task = facade.task_repository.get_task(task_id)

    assert cancel_result["data"]["status"] == "cancellation_requested"
    assert run_result["ok"] is False
    assert run_result["error_code"] == "CANCELLED"
    assert task["status"] == "cancelled"


def test_evaluation_service_rejects_modality_mismatch(tmp_path):
    from backend.errors import ValidationError

    facade, _paths = build_services(tmp_path)
    baseline = create_text_dataset(facade, tmp_path, "baseline-mismatch")
    target = facade.dataset_service.create_dataset("image-target", "image", "")
    algorithm_id = create_evaluation_algorithm(facade.algorithm_service, tmp_path, key="mismatch_eval")
    scenario = facade.evaluation_service.list_scenarios("")[0]

    with pytest.raises(ValidationError):
        facade.evaluation_service.create_task(
            scenario["id"],
            baseline["data"]["id"],
            target["data"]["id"],
            algorithm_id,
            {},
        )


def test_evaluation_service_keeps_explicit_empty_results_empty(tmp_path):
    facade, _paths = build_services(tmp_path)
    baseline = create_text_dataset(facade, tmp_path, "baseline-empty-results")
    target = create_text_dataset(facade, tmp_path, "target-empty-results")
    algorithm_id = create_evaluation_algorithm(
        facade.algorithm_service,
        tmp_path,
        key="empty_results_eval",
        body="def run(payload, context):\n    return {'ok': True, 'results': []}\n",
    )
    scenario = facade.evaluation_service.list_scenarios("")[0]

    created = facade.evaluation_service.create_task(
        scenario["id"],
        baseline["data"]["id"],
        target["data"]["id"],
        algorithm_id,
        {},
    )
    task_id = created["data"]["task_id"]

    facade.task_manager.start(task_id)
    run_result = facade.evaluation_service.run_task(task_id)
    results = facade.evaluation_service.get_results(task_id)

    assert run_result["ok"] is True
    assert run_result["data"]["result_count"] == 0
    assert results["data"]["items"] == []


def test_seeded_multi_agent_simulation_evaluator_runs_and_exports_report(tmp_path):
    from backend.seed_data import DEFAULT_ALGORITHMS

    facade, _paths = build_services(tmp_path)
    baseline = create_text_dataset(facade, tmp_path, "multi-agent-baseline")
    target = create_text_dataset(facade, tmp_path, "multi-agent-target")
    for payload in DEFAULT_ALGORITHMS:
        facade.algorithm_service.create_algorithm(dict(payload))

    algorithms = {item["key"]: item for item in facade.algorithm_service.get_algorithms("evaluation", "")}
    algorithm_id = algorithms["evaluation.multi_agent_simulation"]["id"]
    scenario = facade.evaluation_service.list_scenarios("")[0]

    created = facade.evaluation_service.create_task(
        scenario["id"],
        baseline["data"]["id"],
        target["data"]["id"],
        algorithm_id,
        {"agent_count": 4},
    )
    task_id = created["data"]["task_id"]
    report_path = tmp_path / "multi-agent-report.json"

    facade.task_manager.start(task_id)
    run_result = facade.evaluation_service.run_task(task_id)
    results = facade.evaluation_service.get_results(task_id)
    exported = facade.evaluation_service.export_report(task_id, str(report_path))

    metrics = results["data"]["items"][0]["metrics"]
    assert run_result["ok"] is True
    assert exported["ok"] is True
    assert report_path.is_file()
    assert metrics["coordination_score"] >= 0
    assert metrics["coverage_score"] >= 0
    assert metrics["response_score"] >= 0
    assert metrics["overall_score"] >= 0
    assert results["data"]["items"][0]["summary"]
