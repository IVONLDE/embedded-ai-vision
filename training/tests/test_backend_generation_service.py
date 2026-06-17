from pathlib import Path

import cv2
import numpy as np
import pytest


def build_services(tmp_path):
    from backend import BackendPaths, BackendServiceFacade, create_backend_engine, create_session_factory, initialize_backend_database

    paths = BackendPaths(tmp_path / "backend-root")
    engine = create_backend_engine(paths.database_path)
    initialize_backend_database(engine)
    session_factory = create_session_factory(engine)
    facade = BackendServiceFacade.build(paths=paths, session_factory=session_factory)
    return facade, paths


def create_image_dataset(facade, tmp_path, name="source-image-ds"):
    source_file = tmp_path / f"{name}.jpg"
    image = np.full((16, 16, 3), 127, dtype=np.uint8)
    ok, encoded = cv2.imencode(".jpg", image)
    assert ok is True
    source_file.write_bytes(encoded.tobytes())
    dataset = facade.dataset_service.create_dataset(name, "image", "")
    facade.dataset_service.import_files(dataset["data"]["id"], [str(source_file)])
    return dataset


def create_agl_generation_algorithm(service):
    return service.create_algorithm(
        {
            "key": "agl.image.geometric",
            "name": "AGL Geometric Transformation",
            "category": "generation",
            "modality": "image",
            "entry_type": "python_function",
            "module_path": "backend.plugins.builtin.agl_generation",
            "callable_name": "run",
            "input_contract": {"dataset_required": True, "sample_required": True},
            "output_contract": {"produces": ["generated_samples"]},
            "parameters": [],
        }
    )["data"]["id"]


def create_custom_generation_algorithm(service, tmp_path, key, body):
    plugin_file = tmp_path / f"{key}.py"
    plugin_file.write_text(body, encoding="utf-8")
    return service.create_algorithm(
        {
            "key": key,
            "name": key,
            "category": "generation",
            "modality": "image",
            "entry_type": "python_function",
            "script_path": str(plugin_file),
            "callable_name": "run",
            "input_contract": {"dataset_required": True, "sample_required": True},
            "output_contract": {"produces": ["generated_samples"]},
            "parameters": [],
        }
    )["data"]["id"]


def test_generation_service_creates_task_and_auto_target_dataset(tmp_path):
    facade, _paths = build_services(tmp_path)
    source_dataset = create_image_dataset(facade, tmp_path)
    algorithm_id = create_agl_generation_algorithm(facade.algorithm_service)

    created = facade.generation_service.create_task(
        source_dataset["data"]["id"],
        0,
        [algorithm_id],
        {"旋转角度": 10, "缩放比例": 1.0},
        2,
    )
    task = facade.task_repository.get_task(created["data"]["task_id"])
    target_dataset = facade.dataset_service.get_dataset(created["data"]["target_dataset_id"])

    assert created["ok"] is True
    assert task["status"] == "pending"
    assert task["title"] == f"生成任务_{source_dataset['data']['name']}_#{created['data']['task_id']}"
    assert task["target_dataset_id"] == target_dataset["data"]["id"]
    assert target_dataset["data"]["modality"] == "image"


def test_generation_service_runs_agl_algorithm_and_persists_outputs(tmp_path):
    facade, _paths = build_services(tmp_path)
    source_dataset = create_image_dataset(facade, tmp_path, name="run-image-ds")
    algorithm_id = create_agl_generation_algorithm(facade.algorithm_service)

    created = facade.generation_service.create_task(
        source_dataset["data"]["id"],
        0,
        [algorithm_id],
        {"旋转角度": 15, "缩放比例": 1.0, "水平翻转": False, "垂直翻转": False},
        2,
    )
    task_id = created["data"]["task_id"]
    target_dataset_id = created["data"]["target_dataset_id"]

    facade.task_manager.start(task_id)
    result = facade.generation_service.run_task(task_id)
    task = facade.task_repository.get_task(task_id)
    outputs = facade.generation_service.list_outputs(task_id, None, 1, 20)
    samples = facade.dataset_service.list_samples(target_dataset_id, 1, 20, "generated")

    assert result["ok"] is True
    assert result["data"]["generated_count"] == 2
    assert task["status"] == "completed"
    assert outputs["total"] == 2
    assert samples["total"] == 2
    for item in outputs["items"]:
        assert item["algorithm_id"] == algorithm_id
        assert Path(item["output_path"]).is_file()
        assert item["source_sample"]["status"] == "raw"
        assert item["output_sample"]["status"] == "generated"


def test_generation_service_cancels_before_agl_run(tmp_path):
    facade, _paths = build_services(tmp_path)
    source_dataset = create_image_dataset(facade, tmp_path, name="cancel-image-ds")
    algorithm_id = create_agl_generation_algorithm(facade.algorithm_service)

    created = facade.generation_service.create_task(
        source_dataset["data"]["id"],
        0,
        [algorithm_id],
        {"旋转角度": 5, "缩放比例": 1.0},
        3,
    )
    task_id = created["data"]["task_id"]

    facade.task_manager.start(task_id)
    cancel_result = facade.task_manager.cancel(task_id)
    run_result = facade.generation_service.run_task(task_id)
    task = facade.task_repository.get_task(task_id)

    assert cancel_result["data"]["status"] == "cancellation_requested"
    assert run_result["ok"] is False
    assert run_result["error_code"] == "CANCELLED"
    assert task["status"] == "cancelled"


def test_generation_service_rejects_empty_source_dataset(tmp_path):
    from backend.errors import ValidationError

    facade, _paths = build_services(tmp_path)
    empty_dataset = facade.dataset_service.create_dataset("empty-image-ds", "image", "")
    algorithm_id = create_agl_generation_algorithm(facade.algorithm_service)

    with pytest.raises(ValidationError):
        facade.generation_service.create_task(empty_dataset["data"]["id"], 0, [algorithm_id], {}, 1)


def test_generation_service_fails_when_plugin_returns_too_few_outputs(tmp_path):
    facade, _paths = build_services(tmp_path)
    source_dataset = create_image_dataset(facade, tmp_path, name="few-outputs-ds")
    algorithm_id = create_custom_generation_algorithm(
        facade.algorithm_service,
        tmp_path,
        "few_outputs_generation",
        (
            "from pathlib import Path\n"
            "def run(payload, context):\n"
            "    out = Path(payload['output']['output_dir']) / 'only-one.txt'\n"
            "    out.write_text('one', encoding='utf-8')\n"
            "    sample = payload['input']['samples'][0]\n"
            "    return {'ok': True, 'outputs': [{'source_sample_id': sample['id'], 'output_path': str(out), 'relative_path': 'same-name.txt', 'metadata': {}}]}\n"
        ),
    )

    created = facade.generation_service.create_task(source_dataset["data"]["id"], 0, [algorithm_id], {}, 2)
    task_id = created["data"]["task_id"]
    target_dataset_id = created["data"]["target_dataset_id"]

    facade.task_manager.start(task_id)
    result = facade.generation_service.run_task(task_id)
    task = facade.task_repository.get_task(task_id)
    outputs = facade.generation_service.list_outputs(task_id, None, 1, 20)
    samples = facade.dataset_service.list_samples(target_dataset_id, 1, 20, "generated")

    assert result["ok"] is False
    assert result["error_code"] == "INSUFFICIENT_OUTPUTS"
    assert task["status"] == "failed"
    assert outputs["total"] == 0
    assert samples["total"] == 0


def test_generation_service_persists_final_relative_path_after_name_collision(tmp_path):
    facade, _paths = build_services(tmp_path)
    source_dataset = create_image_dataset(facade, tmp_path, name="collision-ds")
    algorithm_id = create_custom_generation_algorithm(
        facade.algorithm_service,
        tmp_path,
        "collision_generation",
        (
            "from pathlib import Path\n"
            "def run(payload, context):\n"
            "    sample = payload['input']['samples'][0]\n"
            "    outputs = []\n"
            "    for index in range(int(payload['target_count'])):\n"
            "        out = Path(payload['output']['output_dir']) / f'generated-{index}.txt'\n"
            "        out.write_text(f'value-{index}', encoding='utf-8')\n"
            "        outputs.append({'source_sample_id': sample['id'], 'output_path': str(out), 'relative_path': 'duplicate.txt', 'metadata': {}})\n"
            "    return {'ok': True, 'outputs': outputs}\n"
        ),
    )

    created = facade.generation_service.create_task(source_dataset["data"]["id"], 0, [algorithm_id], {}, 2)
    task_id = created["data"]["task_id"]
    target_dataset_id = created["data"]["target_dataset_id"]

    facade.task_manager.start(task_id)
    result = facade.generation_service.run_task(task_id)
    samples = facade.dataset_service.list_samples(target_dataset_id, 1, 20, "generated")
    relative_paths = sorted(item["relative_path"] for item in samples["items"])

    assert result["ok"] is True
    assert relative_paths == ["duplicate.txt", "duplicate_1.txt"]


def test_generation_service_preserves_source_labels_for_augmented_samples(tmp_path):
    from backend.models import Sample

    facade, _paths = build_services(tmp_path)
    source_dataset = create_image_dataset(facade, tmp_path, name="labeled-source")
    source_sample = facade.dataset_service.list_samples(source_dataset["data"]["id"], 1, 20, "")["items"][0]
    with facade.session_factory() as session:
        row = session.query(Sample).filter(Sample.id == source_sample["id"]).first()
        row.labels_json = [
            {
                "type": "classification",
                "class_id": 3,
                "class_name": "tire",
                "source": "train_abs.txt",
                "split": "train",
            }
        ]
        session.commit()

    algorithm_id = create_custom_generation_algorithm(
        facade.algorithm_service,
        tmp_path,
        "label_inheritance_generation",
        (
            "from pathlib import Path\n"
            "def run(payload, context):\n"
            "    sample = payload['input']['samples'][0]\n"
            "    out = Path(payload['output']['output_dir']) / 'augmented.jpg'\n"
            "    out.write_bytes(Path(sample['path']).read_bytes())\n"
            "    return {'ok': True, 'outputs': [{'source_sample_id': sample['id'], 'output_path': str(out), 'relative_path': 'augmented.jpg', 'metadata': {'method': 'unit-test'}}]}\n"
        ),
    )

    created = facade.generation_service.create_task(source_dataset["data"]["id"], 0, [algorithm_id], {}, 1)
    task_id = created["data"]["task_id"]
    target_dataset_id = created["data"]["target_dataset_id"]
    facade.task_manager.start(task_id)
    result = facade.generation_service.run_task(task_id)
    samples = facade.dataset_service.list_samples(target_dataset_id, 1, 20, "generated")

    assert result["ok"] is True
    assert samples["items"][0]["source_sample_id"] == source_sample["id"]
    assert samples["items"][0]["labels"][0]["class_id"] == 3
    assert samples["items"][0]["labels"][0]["class_name"] == "tire"


def test_geometric_image_augmenter_plugin_outputs_augmented_path_and_metadata(tmp_path):
    from plugins.generation.geometric_image_augmenter import run

    source = tmp_path / "source.jpg"
    image = np.zeros((18, 18, 3), dtype=np.uint8)
    image[4:14, 6:12] = (255, 255, 255)
    ok, encoded = cv2.imencode(".jpg", image)
    assert ok is True
    source.write_bytes(encoded.tobytes())

    class Context:
        def __init__(self):
            self.progress = []

        def is_cancel_requested(self):
            return False

        def set_progress(self, value, message):
            self.progress.append((value, message))

        def log(self, level, message, payload=None):
            pass

    result = run(
        {
            "algorithm_key": "generation.image.geometric_transform",
            "parameters": {
                "rotation_degrees": 12,
                "scale": 1.0,
                "translate_x_pct": 5,
                "translate_y_pct": -3,
                "flip_horizontal": True,
            },
            "target_count": 1,
            "input": {"samples": [{"id": 7, "sample_path": str(source), "path": str(source), "name": "source.jpg"}]},
            "output": {"output_dir": str(tmp_path / "generated")},
        },
        Context(),
    )

    assert result["ok"] is True
    assert len(result["outputs"]) == 1
    output = result["outputs"][0]
    assert Path(output["output_path"]).is_file()
    assert output["source_sample_id"] == 7
    assert output["metadata"]["algorithm_key"] == "generation.image.geometric_transform"
    assert output["metadata"]["augmented_sample_path"] == output["output_path"]
    assert output["metadata"]["parameters"]["rotation_degrees"] == 12


@pytest.mark.parametrize(
    ("module_name", "algorithm_key"),
    [
        ("plugins.generation.color_space_image_augmenter", "generation.image.color_space"),
        ("plugins.generation.clarity_image_augmenter", "generation.image.clarity"),
        ("plugins.generation.imaging_simulation_image_augmenter", "generation.image.imaging_simulation"),
    ],
)
def test_image_generation_plugins_read_unicode_paths(tmp_path, module_name, algorithm_key):
    import importlib

    source_dir = tmp_path / "NKSID_清洗版_去噪"
    source_dir.mkdir()
    source = source_dir / "样本.jpg"
    image = np.full((18, 18, 3), 127, dtype=np.uint8)
    ok, encoded = cv2.imencode(".jpg", image)
    assert ok is True
    source.write_bytes(encoded.tobytes())

    class Context:
        def is_cancel_requested(self):
            return False

        def set_progress(self, value, message):
            pass

        def log(self, level, message, payload=None):
            pass

    result = importlib.import_module(module_name).run(
        {
            "algorithm_key": algorithm_key,
            "parameters": {},
            "target_count": 1,
            "input": {"samples": [{"id": 7, "sample_path": str(source), "path": str(source), "name": source.name}]},
            "output": {"output_dir": str(tmp_path / "生成结果")},
        },
        Context(),
    )

    assert result["ok"] is True
    assert len(result["outputs"]) == 1
    assert Path(result["outputs"][0]["output_path"]).is_file()


def test_seeded_geometric_generation_algorithm_runs_through_backend(tmp_path):
    from backend.seed_data import DEFAULT_ALGORITHMS

    facade, _paths = build_services(tmp_path)
    source_dataset = create_image_dataset(facade, tmp_path, name="geometric-source")
    for payload in DEFAULT_ALGORITHMS:
        facade.algorithm_service.create_algorithm(dict(payload))
    algorithms = {item["key"]: item for item in facade.algorithm_service.get_algorithms("generation", "image")}
    algorithm_id = algorithms["generation.image.geometric_transform"]["id"]

    created = facade.generation_service.create_task(
        source_dataset["data"]["id"],
        0,
        [algorithm_id],
        {"rotation_degrees": 15, "scale": 0.95, "translate_x_pct": 2, "translate_y_pct": 0},
        2,
    )
    task_id = created["data"]["task_id"]
    target_dataset_id = created["data"]["target_dataset_id"]

    facade.task_manager.start(task_id)
    result = facade.generation_service.run_task(task_id)
    outputs = facade.generation_service.list_outputs(task_id, None, 1, 20)
    samples = facade.dataset_service.list_samples(target_dataset_id, 1, 20, "generated")
    target_dataset = facade.dataset_service.get_dataset(target_dataset_id)

    assert result["ok"] is True
    assert result["data"]["generated_count"] == 2
    assert target_dataset["data"]["status"] == "generated"
    assert target_dataset["data"]["parent_dataset_id"] == source_dataset["data"]["id"]
    assert "generated" in target_dataset["data"]["tags"]
    assert outputs["parameters"]["rotation_degrees"] == 15
    assert outputs["total"] == 2
    assert samples["total"] == 2
    for item in outputs["items"]:
        assert item["metadata"]["method"] == "geometric_transform"
        assert Path(item["output_path"]).is_file()
def test_generation_plugins_use_python39_compatible_optional_annotations():
    for plugin_path in Path("plugins/generation").glob("*.py"):
        source = plugin_path.read_text(encoding="utf-8")

        assert " | None" not in source
