import sys
from pathlib import Path


def build_algorithm_service(tmp_path):
    from backend import BackendPaths, create_backend_engine, create_session_factory, initialize_backend_database
    from backend.repositories import AlgorithmRepository, LogRepository
    from backend.services import AlgorithmService

    paths = BackendPaths(tmp_path / "backend-root")
    engine = create_backend_engine(paths.database_path)
    initialize_backend_database(engine)
    session_factory = create_session_factory(engine)
    service = AlgorithmService(
        paths=paths,
        session_factory=session_factory,
        algorithm_repository=AlgorithmRepository(session_factory),
        log_repository=LogRepository(session_factory),
    )
    return service


def test_algorithm_service_creates_lists_and_toggles_algorithm(tmp_path):
    service = build_algorithm_service(tmp_path)
    plugin_file = tmp_path / "demo_plugin.py"
    plugin_file.write_text(
        "def run(payload, context):\n    return {'ok': True, 'logs': []}\n",
        encoding="utf-8",
    )

    payload = {
        "key": "image_blur_detector",
        "name": "Image Blur Detector",
        "category": "cleaning",
        "modality": "image",
        "entry_type": "python_function",
        "script_path": str(plugin_file),
        "callable_name": "run",
        "input_contract": {"dataset_required": True},
        "output_contract": {"produces": ["suggestions"]},
        "parameters": [
            {
                "name": "threshold",
                "label": "Threshold",
                "type": "float",
                "required": True,
                "default_value": 100.0,
                "min_value": 0,
                "max_value": 1000,
            }
        ],
    }

    created = service.create_algorithm(payload)
    listed = service.get_algorithms(category="cleaning", modality="image")
    disabled = service.set_algorithm_enabled(created["data"]["id"], False)
    listed_after_disable = service.get_algorithms(category="cleaning", modality="image")

    assert created["ok"] is True
    assert listed[0]["key"] == "image_blur_detector"
    assert disabled["data"]["status"] == "disabled"
    assert listed_after_disable[0]["status"] == "disabled"


def test_algorithm_service_includes_multimodal_algorithms_for_modality_filter(tmp_path):
    service = build_algorithm_service(tmp_path)
    base_payload = {
        "category": "cleaning",
        "entry_type": "python_function",
        "module_path": "plugins.cleaning.demo",
        "callable_name": "run",
        "input_contract": {"dataset_required": True},
        "output_contract": {"produces": ["suggestions"]},
        "parameters": [],
    }
    service.create_algorithm({**base_payload, "key": "cleaning.image", "name": "Image Cleaner", "modality": "image"})
    service.create_algorithm({**base_payload, "key": "cleaning.multi", "name": "Common Cleaner", "modality": "multimodal"})
    service.create_algorithm({**base_payload, "key": "cleaning.text", "name": "Text Cleaner", "modality": "text"})

    listed = service.get_algorithms(category="cleaning", modality="image")

    assert {item["key"] for item in listed} == {"cleaning.image", "cleaning.multi"}


def test_algorithm_service_validates_python_script_entry(tmp_path):
    service = build_algorithm_service(tmp_path)
    plugin_file = tmp_path / "valid_plugin.py"
    plugin_file.write_text(
        "def run(payload, context):\n    return {'ok': True, 'artifacts': []}\n",
        encoding="utf-8",
    )

    created = service.create_algorithm(
        {
            "key": "eval_demo",
            "name": "Eval Demo",
            "category": "evaluation",
            "modality": "text",
            "entry_type": "python_function",
            "script_path": str(plugin_file),
            "callable_name": "run",
            "input_contract": {"dataset_required": True},
            "output_contract": {"produces": ["metrics"]},
            "parameters": [],
        }
    )

    validated = service.validate_algorithm(created["data"]["id"])

    assert validated["ok"] is True
    assert validated["data"]["callable_name"] == "run"


def test_algorithm_service_persists_evaluation_resource_contract(tmp_path):
    service = build_algorithm_service(tmp_path)
    plugin_file = tmp_path / "eval_with_contract.py"
    plugin_file.write_text(
        "def run(payload, context):\n    return {'ok': True, 'metrics': {}}\n",
        encoding="utf-8",
    )

    created = service.create_algorithm(
        {
            "key": "eval_contract",
            "name": "Eval Contract",
            "category": "evaluation",
            "modality": "image",
            "entry_type": "python_function",
            "script_path": str(plugin_file),
            "callable_name": "run",
            "input_contract": {
                "dataset_path": "input.dataset.path",
                "label_path": "input.label.path",
                "supports_training": True,
            },
            "output_contract": {"produces": ["metrics"]},
            "runtime_artifact_path": str(tmp_path / "runtime"),
            "dataset_path": str(tmp_path / "dataset"),
            "label_path": str(tmp_path / "labels.txt"),
            "model_path": str(tmp_path / "model.pt"),
            "parameters": [],
        }
    )

    algorithm = created["data"]

    assert algorithm["category"] == "evaluation"
    assert algorithm["input_contract"]["supports_training"] is True
    assert algorithm["validation_rules"]["dataset_path"].endswith("dataset")
    assert algorithm["validation_rules"]["label_path"].endswith("labels.txt")
    assert algorithm["validation_rules"]["model_path"].endswith("model.pt")


def test_algorithm_service_supports_module_path_updates(tmp_path):
    service = build_algorithm_service(tmp_path)
    plugin_dir = tmp_path / "plugins"
    plugin_dir.mkdir()
    module_file = plugin_dir / "module_plugin.py"
    module_file.write_text(
        "def run(payload, context):\n    return {'ok': True, 'outputs': []}\n",
        encoding="utf-8",
    )
    sys.path.insert(0, str(plugin_dir))
    try:
        created = service.create_algorithm(
            {
                "key": "gen_demo",
                "name": "Gen Demo",
                "category": "generation",
                "modality": "image",
                "entry_type": "python_function",
                "module_path": "module_plugin",
                "callable_name": "run",
                "input_contract": {"dataset_required": True},
                "output_contract": {"produces": ["outputs"]},
                "parameters": [],
            }
        )

        updated = service.update_algorithm(
            created["data"]["id"],
            {
                "name": "Generation Demo",
                "modality": "multimodal",
            },
        )
        validated = service.validate_algorithm(created["data"]["id"])

        assert updated["data"]["name"] == "Generation Demo"
        assert updated["data"]["modality"] == "multimodal"
        assert validated["ok"] is True
    finally:
        sys.path.remove(str(plugin_dir))
