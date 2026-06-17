from pathlib import Path

import pytest


_SMALL_PNG_BYTES = (
    b"\x89PNG\r\n\x1a\n"
    b"\x00\x00\x00\rIHDR"
    b"\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00"
    b"\x90wS\xde"
    b"\x00\x00\x00\x0cIDATx\x9cc\xf8\xcf\xc0\x00\x00\x03\x01\x01\x00"
    b"\xc9\xfe\x92\xef"
    b"\x00\x00\x00\x00IEND\xaeB`\x82"
)


def build_services(tmp_path):
    from backend import BackendPaths, BackendServiceFacade, create_backend_engine, create_session_factory, initialize_backend_database

    paths = BackendPaths(tmp_path / "backend-root")
    engine = create_backend_engine(paths.database_path)
    initialize_backend_database(engine)
    session_factory = create_session_factory(engine)
    facade = BackendServiceFacade.build(paths=paths, session_factory=session_factory)
    return facade, paths


def create_algorithm(service, tmp_path, key="clean_demo", *, category="cleaning", body=None):
    plugin_file = tmp_path / f"{key}.py"
    plugin_file.write_text(
        body
        or (
            "def run(payload, context):\n"
            "    context.log('info', 'clean-plugin-start', {'task_id': payload['task_id']})\n"
            "    context.set_progress(100.0, 'done')\n"
            "    return {'ok': True, 'suggestions': [], 'logs': []}\n"
        ),
        encoding="utf-8",
    )
    return service.create_algorithm(
        {
            "key": key,
            "name": key,
            "category": category,
            "modality": "text",
            "entry_type": "python_function",
            "script_path": str(plugin_file),
            "callable_name": "run",
            "input_contract": {"dataset_required": True},
            "output_contract": {"produces": ["suggestions"]},
            "parameters": [],
        }
    )["data"]["id"]


def create_text_dataset(facade, tmp_path, name="clean-ds"):
    source_file = tmp_path / f"{name}.txt"
    source_file.write_text("hello cleaning", encoding="utf-8")
    dataset = facade.dataset_service.create_dataset(name, "text", "")
    facade.dataset_service.import_files(dataset["data"]["id"], [str(source_file)])
    return dataset


def test_cleaning_service_validates_dataset_and_algorithm_list_boundary(tmp_path):
    from backend.errors import NotFoundError, ValidationError

    facade, _paths = build_services(tmp_path)
    dataset = create_text_dataset(facade, tmp_path, name="valid-ds")
    valid_algorithm_id = create_algorithm(facade.algorithm_service, tmp_path, key="valid_clean")
    invalid_algorithm_id = create_algorithm(facade.algorithm_service, tmp_path, key="invalid_generation", category="generation")

    with pytest.raises(NotFoundError):
        facade.cleaning_service.create_task(9999, [valid_algorithm_id], {})

    with pytest.raises(ValidationError):
        facade.cleaning_service.create_task(dataset["data"]["id"], [valid_algorithm_id, invalid_algorithm_id], {})

    created = facade.cleaning_service.create_task(dataset["data"]["id"], [valid_algorithm_id], {"algorithm_ids": []})
    task = facade.task_repository.get_task(created["data"]["task_id"])
    assert task["title"] == f"清洗任务_{dataset['data']['name']}_#{created['data']['task_id']}"
    assert task["parameters_json"]["algorithm_ids"] == [valid_algorithm_id]
    assert task["payload_json"]["algorithm_ids"] == [valid_algorithm_id]

    facade.dataset_service.delete_dataset(dataset["data"]["id"])
    with pytest.raises(ValidationError):
        facade.cleaning_service.create_task(dataset["data"]["id"], [valid_algorithm_id], {})


def test_cleaning_service_runs_plugin_and_writes_suggestions_and_logs(tmp_path):
    facade, _paths = build_services(tmp_path)
    dataset = create_text_dataset(facade, tmp_path, name="run-ds")
    algorithm_id = create_algorithm(
        facade.algorithm_service,
        tmp_path,
        key="suggest_clean",
        body=(
            "def run(payload, context):\n"
            "    sample = payload['input']['samples'][0]\n"
            "    context.log('info', 'plugin-ran', {'sample_id': sample['id']})\n"
            "    context.set_progress(100.0, 'done')\n"
            "    return {'ok': True, 'suggestions': [{'sample_id': sample['id'], 'issue_type': 'typo', 'suggested_action': 'review', 'confidence': 0.9, 'message': 'Check text', 'details': {'kind': 'demo'}}], 'logs': []}\n"
        ),
    )

    task_id = facade.cleaning_service.create_task(dataset["data"]["id"], [algorithm_id], {})["data"]["task_id"]
    facade.task_manager.start(task_id)
    result = facade.cleaning_service.run_task(task_id)
    task = facade.task_repository.get_task(task_id)
    suggestions = facade.cleaning_service.list_suggestions(task_id, None, 1, 20)
    handled = facade.cleaning_service.handle_suggestion(suggestions["items"][0]["id"], "approve")
    logs = facade.task_repository.list_task_logs(task_id, page=1, page_size=20)

    assert result["ok"] is True
    assert task["status"] == "completed"
    assert suggestions["total"] == 1
    assert handled["ok"] is True
    assert logs["total"] >= 2
    assert any(item["message"] == "plugin-ran" for item in logs["items"])


def test_task_manager_cancel_is_cooperative_for_running_task(tmp_path):
    from backend.errors import ValidationError

    facade, _paths = build_services(tmp_path)
    dataset = create_text_dataset(facade, tmp_path, name="cancel-ds")
    algorithm_id = create_algorithm(
        facade.algorithm_service,
        tmp_path,
        key="cancel_clean",
        body=(
            "def run(payload, context):\n"
            "    if context.is_cancel_requested():\n"
            "        context.log('warning', 'cancel-seen', {})\n"
            "        return {'ok': False, 'error_code': 'CANCELLED', 'message': 'cancelled by request'}\n"
            "    return {'ok': True, 'suggestions': [], 'logs': []}\n"
        ),
    )
    task_id = facade.cleaning_service.create_task(dataset["data"]["id"], [algorithm_id], {})["data"]["task_id"]

    facade.task_manager.start(task_id)
    cancel_result = facade.task_manager.cancel(task_id)
    before_run = facade.task_repository.get_task(task_id)
    result = facade.cleaning_service.run_task(task_id)
    after_run = facade.task_repository.get_task(task_id)

    assert cancel_result["data"]["status"] == "cancellation_requested"
    assert before_run["status"] == "running"
    assert result["ok"] is False
    assert result["error_code"] == "CANCELLED"
    assert after_run["status"] == "cancelled"

    pending_task_id = facade.cleaning_service.create_task(dataset["data"]["id"], [algorithm_id], {})["data"]["task_id"]
    pending_cancel = facade.task_manager.cancel(pending_task_id)
    assert pending_cancel["data"]["status"] == "cancelled"
    with pytest.raises(ValidationError):
        facade.task_manager.start(pending_task_id)
    with pytest.raises(ValidationError):
        facade.cleaning_service.run_task(pending_task_id)


def test_task_manager_missing_task_raises_not_found(tmp_path):
    from backend.errors import NotFoundError

    facade, _paths = build_services(tmp_path)

    with pytest.raises(NotFoundError):
        facade.task_manager.start(999)

    with pytest.raises(NotFoundError):
        facade.task_manager.cancel(999)


def test_task_repository_filters_tasks_and_returns_logs(tmp_path):
    facade, _paths = build_services(tmp_path)
    dataset = create_text_dataset(facade, tmp_path, name="filter-ds")
    algorithm_id = create_algorithm(facade.algorithm_service, tmp_path, key="filter_clean")
    task_id = facade.cleaning_service.create_task(dataset["data"]["id"], [algorithm_id], {})["data"]["task_id"]

    facade.task_manager.start(task_id)
    tasks_page = facade.task_repository.list_tasks(task_type="cleaning", status="running", page=1, page_size=10)
    logs_page = facade.task_repository.list_task_logs(task_id, page=1, page_size=10)
    running_ids = facade.task_manager.get_running_task_ids()

    assert tasks_page["total"] == 1
    assert tasks_page["items"][0]["id"] == task_id
    assert logs_page["total"] >= 1
    assert task_id in running_ids


def test_cleaning_suggestion_actions_and_algorithm_provenance(tmp_path):
    facade, _paths = build_services(tmp_path)
    dataset = create_text_dataset(facade, tmp_path, name="multi-algo-ds")
    algorithm_a = create_algorithm(
        facade.algorithm_service,
        tmp_path,
        key="algo_a",
        body=(
            "def run(payload, context):\n"
            "    sample = payload['input']['samples'][0]\n"
            "    return {'ok': True, 'suggestions': [{'sample_id': sample['id'], 'algorithm_id': 999999, 'issue_type': 'a', 'suggested_action': 'review', 'confidence': 0.5, 'message': 'A', 'details': {}}]}\n"
        ),
    )
    algorithm_b = create_algorithm(
        facade.algorithm_service,
        tmp_path,
        key="algo_b",
        body=(
            "def run(payload, context):\n"
            "    sample = payload['input']['samples'][0]\n"
            "    return {'ok': True, 'suggestions': [{'sample_id': sample['id'], 'issue_type': 'b', 'suggested_action': 'review', 'confidence': 0.6, 'message': 'B', 'details': {}}]}\n"
        ),
    )

    task_id = facade.cleaning_service.create_task(dataset["data"]["id"], [algorithm_a, algorithm_b], {})["data"]["task_id"]
    facade.task_manager.start(task_id)
    facade.cleaning_service.run_task(task_id)
    suggestions = facade.cleaning_service.list_suggestions(task_id, None, 1, 20)

    by_issue = {item["issue_type"]: item for item in suggestions["items"]}
    assert by_issue["a"]["algorithm_id"] == algorithm_a
    assert by_issue["b"]["algorithm_id"] == algorithm_b

    approved = facade.cleaning_service.handle_suggestion(by_issue["a"]["id"], "approve")
    rejected = facade.cleaning_service.handle_suggestion(by_issue["b"]["id"], "reject")

    assert approved["data"]["status"] == "approved"
    assert rejected["data"]["status"] == "rejected"


def test_cleaning_apply_creates_cleaned_sample_and_is_not_repeatable(tmp_path):
    from backend.errors import ValidationError

    facade, _paths = build_services(tmp_path)
    dataset = create_text_dataset(facade, tmp_path, name="apply-ds")
    algorithm_id = create_algorithm(
        facade.algorithm_service,
        tmp_path,
        key="apply_clean",
        body=(
            "from pathlib import Path\n"
            "def run(payload, context):\n"
            "    sample = payload['input']['samples'][0]\n"
            "    repaired = Path(payload['output']['output_dir']) / 'repaired.txt'\n"
            "    repaired.write_text('hello cleaned', encoding='utf-8')\n"
            "    return {'ok': True, 'suggestions': [\n"
            "        {'sample_id': sample['id'], 'issue_type': 'repairable', 'suggested_action': 'repair', 'confidence': 0.9, 'message': 'repair me', 'details': {'output_file_path': str(repaired)}}\n"
            "    ]}\n"
        ),
    )

    task_id = facade.cleaning_service.create_task(dataset["data"]["id"], [algorithm_id], {})["data"]["task_id"]
    facade.task_manager.start(task_id)
    facade.cleaning_service.run_task(task_id)
    suggestions = facade.cleaning_service.list_suggestions(task_id, None, 1, 20)
    suggestion = suggestions["items"][0]

    applied_repair = facade.cleaning_service.handle_suggestion(suggestion["id"], "apply")
    dataset_samples = facade.dataset_service.list_samples(dataset["data"]["id"], 1, 20, "")
    by_status = {}
    for item in dataset_samples["items"]:
        by_status.setdefault(item["status"], []).append(item)

    assert applied_repair["data"]["status"] == "applied"
    assert applied_repair["data"]["output_sample_id"] is not None
    assert len(by_status["cleaned"]) == 1
    with pytest.raises(ValidationError):
        facade.cleaning_service.handle_suggestion(suggestion["id"], "apply")


def test_cleaning_task_can_be_stored_as_new_cleaned_dataset(tmp_path):
    facade, _paths = build_services(tmp_path)
    dataset = facade.dataset_service.create_dataset("source-for-store", "text", "")
    keep_file = tmp_path / "keep.txt"
    drop_file = tmp_path / "drop.txt"
    repair_file = tmp_path / "repair.txt"
    keep_file.write_text("keep original", encoding="utf-8")
    drop_file.write_text("drop original", encoding="utf-8")
    repair_file.write_text("repair original", encoding="utf-8")
    facade.dataset_service.import_files(dataset["data"]["id"], [str(keep_file), str(drop_file), str(repair_file)])

    algorithm_id = create_algorithm(
        facade.algorithm_service,
        tmp_path,
        key="store_clean",
        body=(
            "from pathlib import Path\n"
            "def run(payload, context):\n"
            "    by_name = {sample['name']: sample for sample in payload['input']['samples']}\n"
            "    repaired = Path(payload['output']['output_dir']) / 'repair_cleaned.txt'\n"
            "    repaired.write_text('repair cleaned', encoding='utf-8')\n"
            "    return {'ok': True, 'suggestions': [\n"
            "        {'sample_id': by_name['drop.txt']['id'], 'issue_type': 'duplicate', 'suggested_action': 'delete', 'confidence': 0.95, 'message': 'drop it', 'details': {}},\n"
            "        {'sample_id': by_name['repair.txt']['id'], 'issue_type': 'repairable', 'suggested_action': 'repair', 'confidence': 0.9, 'message': 'repair it', 'details': {'output_file_path': str(repaired)}}\n"
            "    ]}\n"
        ),
    )

    task_id = facade.cleaning_service.create_task(dataset["data"]["id"], [algorithm_id], {"threshold": 0.42})["data"]["task_id"]
    facade.task_manager.start(task_id)
    facade.cleaning_service.run_task(task_id)

    stored = facade.cleaning_service.store_cleaned_dataset(task_id, "source-for-store-cleaned")
    stored_dataset_id = stored["data"]["dataset"]["id"]
    stored_samples = facade.dataset_service.list_samples(stored_dataset_id, 1, 20, "")
    task = facade.task_repository.get_task(task_id)

    assert stored["ok"] is True
    assert stored["data"]["source_dataset_id"] == dataset["data"]["id"]
    assert stored["data"]["stored_count"] == 2
    assert stored["data"]["skipped_count"] == 1
    assert stored["data"]["dataset"]["status"] == "cleaned"
    assert stored["data"]["dataset"]["parent_dataset_id"] == dataset["data"]["id"]
    assert "cleaned" in stored["data"]["dataset"]["tags"]
    assert task["target_dataset_id"] == stored_dataset_id
    assert task["result_json"]["stored_dataset_id"] == stored_dataset_id
    assert task["result_json"]["stored_dataset_path"] == stored["data"]["dataset"]["storage_path"]
    assert task["source_dataset_name"] == "source-for-store"
    assert task["target_dataset_name"] == "source-for-store-cleaned"
    assert task["target_dataset_path"] == stored["data"]["dataset"]["storage_path"]
    assert {item["name"] for item in stored_samples["items"]} == {"keep.txt", "repair.txt"}
    assert all(item["status"] == "cleaned" for item in stored_samples["items"])
    repaired = next(item for item in stored_samples["items"] if item["name"] == "repair.txt")
    assert Path(repaired["file_path"]).read_text(encoding="utf-8") == "repair cleaned"


def test_cleaning_monitor_items_include_keep_delete_and_parameters(tmp_path):
    facade, _paths = build_services(tmp_path)
    dataset = facade.dataset_service.create_dataset("monitor-source", "text", "")
    keep_file = tmp_path / "keep.txt"
    drop_file = tmp_path / "drop.txt"
    keep_file.write_text("keep original", encoding="utf-8")
    drop_file.write_text("drop original", encoding="utf-8")
    facade.dataset_service.import_files(dataset["data"]["id"], [str(keep_file), str(drop_file)])

    algorithm_id = create_algorithm(
        facade.algorithm_service,
        tmp_path,
        key="monitor_clean",
        body=(
            "def run(payload, context):\n"
            "    by_name = {sample['name']: sample for sample in payload['input']['samples']}\n"
            "    assert payload['parameters']['threshold'] == 0.88\n"
            "    return {'ok': True, 'suggestions': [\n"
            "        {'sample_id': by_name['drop.txt']['id'], 'issue_type': 'duplicate', 'suggested_action': 'delete', 'confidence': 0.95, 'message': 'duplicate sample', 'details': {}}\n"
            "    ]}\n"
        ),
    )

    task_id = facade.cleaning_service.create_task(dataset["data"]["id"], [algorithm_id], {"threshold": 0.88})["data"]["task_id"]
    facade.task_manager.start(task_id)
    facade.cleaning_service.run_task(task_id)

    listed = facade.cleaning_service.list_suggestions(task_id, None, 1, 20)
    monitor_by_name = {item["sample_name"]: item for item in listed["monitor_items"]}

    assert listed["parameters"]["threshold"] == 0.88
    assert monitor_by_name["drop.txt"]["suggestion_id"] > 0
    assert monitor_by_name["keep.txt"]["suggestion_id"] == -1
    assert monitor_by_name["drop.txt"]["issue_type"] == "duplicate"
    assert monitor_by_name["drop.txt"]["operation"] == "delete"
    assert monitor_by_name["drop.txt"]["operation_label"] == "删除"
    assert monitor_by_name["keep.txt"]["issue_type"] == "none"
    assert monitor_by_name["keep.txt"]["operation"] == "keep"
    assert monitor_by_name["keep.txt"]["operation_label"] == "保留"


def test_cleaning_suggestions_include_source_and_output_sample_payloads(tmp_path):
    facade, _paths = build_services(tmp_path)
    dataset = create_text_dataset(facade, tmp_path, name="serialize-clean-ds")
    algorithm_id = create_algorithm(
        facade.algorithm_service,
        tmp_path,
        key="serialize_clean",
        body=(
            "from pathlib import Path\n"
            "def run(payload, context):\n"
            "    sample = payload['input']['samples'][0]\n"
            "    repaired = Path(payload['output']['output_dir']) / 'fixed.txt'\n"
            "    repaired.write_text('fixed', encoding='utf-8')\n"
            "    return {'ok': True, 'suggestions': [\n"
            "        {'sample_id': sample['id'], 'issue_type': 'repairable', 'suggested_action': 'repair', 'confidence': 0.7, 'message': 'repair me', 'details': {'output_file_path': str(repaired)}}\n"
            "    ]}\n"
        ),
    )

    task_id = facade.cleaning_service.create_task(dataset["data"]["id"], [algorithm_id], {})["data"]["task_id"]
    facade.task_manager.start(task_id)
    facade.cleaning_service.run_task(task_id)

    listed = facade.cleaning_service.list_suggestions(task_id, None, 1, 20)
    suggestion = listed["items"][0]
    applied = facade.cleaning_service.handle_suggestion(suggestion["id"], "apply")["data"]

    assert suggestion["sample"]["name"].endswith(".txt")
    assert suggestion["output_sample"] is None
    assert applied["output_sample"]["status"] == "cleaned"


def test_builtin_duplicate_detector_finds_duplicates_from_imported_file_hashes(tmp_path):
    facade, _paths = build_services(tmp_path)
    dataset = facade.dataset_service.create_dataset("duplicate-ds", "text", "")

    first = tmp_path / "dup_a.txt"
    second = tmp_path / "dup_b.txt"
    third = tmp_path / "unique.txt"
    first.write_text("same payload", encoding="utf-8")
    second.write_text("same payload", encoding="utf-8")
    third.write_text("different payload", encoding="utf-8")
    facade.dataset_service.import_files(dataset["data"]["id"], [str(first), str(second), str(third)])

    algorithm_id = facade.algorithm_service.create_algorithm(
        {
            "key": "builtin_duplicate_detector",
            "name": "Builtin Duplicate Detector",
            "category": "cleaning",
            "modality": "multimodal",
            "entry_type": "python_function",
            "module_path": "plugins.cleaning.duplicate_detector",
            "callable_name": "run",
            "input_contract": {"dataset_required": True, "sample_required": True},
            "output_contract": {"produces": ["suggestions"]},
            "parameters": [],
        }
    )["data"]["id"]

    task_id = facade.cleaning_service.create_task(dataset["data"]["id"], [algorithm_id], {})["data"]["task_id"]
    facade.task_manager.start(task_id)
    run_result = facade.cleaning_service.run_task(task_id)
    suggestions = facade.cleaning_service.list_suggestions(task_id, None, 1, 20)

    assert run_result["ok"] is True
    assert suggestions["total"] == 1
    assert suggestions["items"][0]["issue_type"] == "duplicate"
    assert suggestions["items"][0]["details"]["sha256"]


def test_resolution_cleaner_filters_non_compliant_images_when_storing_dataset(tmp_path):
    facade, _paths = build_services(tmp_path)
    dataset = facade.dataset_service.create_dataset("image-filter-ds", "image", "")

    small_image = tmp_path / "too_small.png"
    large_image = tmp_path / "good.png"
    small_image.write_bytes(_SMALL_PNG_BYTES)
    large_image.write_bytes(_SMALL_PNG_BYTES)

    dataset_id = dataset["data"]["id"]
    facade.dataset_service.import_files(dataset_id, [str(small_image), str(large_image)])

    imported_samples = facade.dataset_service.list_samples(dataset_id, 1, 20, "")["items"]
    sample_by_name = {item["name"]: item for item in imported_samples}
    large_sample_path = Path(sample_by_name["good.png"]["file_path"])
    patched_large = large_sample_path.read_bytes()
    patched_large = patched_large[:16] + b"\x00\x00\x03\x20\x00\x00\x02\x58" + patched_large[24:]
    large_sample_path.write_bytes(patched_large)

    algorithm_id = facade.algorithm_service.create_algorithm(
        {
            "key": "user.desktop_image_resolution_cleaner",
            "name": "桌面图片分辨率过滤",
            "category": "cleaning",
            "modality": "image",
            "entry_type": "python_function",
            "module_path": "plugins.user.desktop_image_resolution_cleaner",
            "callable_name": "run",
            "input_contract": {"dataset_required": True, "sample_required": True},
            "output_contract": {"produces": ["suggestions"]},
            "parameters": [
                {"name": "min_width", "label": "最小宽度", "type": "integer", "required": False, "default_value": 640},
                {"name": "min_height", "label": "最小高度", "type": "integer", "required": False, "default_value": 480},
                {"name": "min_file_kb", "label": "最小文件大小(KB)", "type": "integer", "required": False, "default_value": 0},
            ],
        }
    )["data"]["id"]

    task_id = facade.cleaning_service.create_task(
        dataset_id,
        [algorithm_id],
        {"min_width": 640, "min_height": 480, "min_file_kb": 0},
    )["data"]["task_id"]
    facade.task_manager.start(task_id)
    run_result = facade.cleaning_service.run_task(task_id)
    suggestions = facade.cleaning_service.list_suggestions(task_id, None, 1, 20)
    stored = facade.cleaning_service.store_cleaned_dataset(task_id, "image-filter-ds-cleaned")
    stored_samples = facade.dataset_service.list_samples(stored["data"]["dataset"]["id"], 1, 20, "")

    assert run_result["ok"] is True
    assert suggestions["total"] == 1
    assert suggestions["items"][0]["suggested_action"] == "delete"
    assert suggestions["items"][0]["sample"]["name"] == "too_small.png"
    assert stored["data"]["stored_count"] == 1
    assert stored["data"]["skipped_count"] == 1
    assert [item["name"] for item in stored_samples["items"]] == ["good.png"]


def write_pgm(path, pixels):
    height = len(pixels)
    width = len(pixels[0])
    data = bytes(value for row in pixels for value in row)
    path.write_bytes(f"P5\n{width} {height}\n255\n".encode("ascii") + data)


def test_image_near_duplicate_cleaning_plugin_detects_perceptual_duplicates(tmp_path):
    from plugins.cleaning.image_near_duplicate_detector import run

    base_pixels = [[(x * 24 + y * 3) % 256 for x in range(10)] for y in range(10)]
    near_pixels = [row[:] for row in base_pixels]
    near_pixels[4][4] = min(255, near_pixels[4][4] + 2)
    unique_pixels = [[255 - value for value in row] for row in base_pixels]

    base = tmp_path / "base.pgm"
    near = tmp_path / "near.pgm"
    unique = tmp_path / "unique.pgm"
    write_pgm(base, base_pixels)
    write_pgm(near, near_pixels)
    write_pgm(unique, unique_pixels)

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
            "modality": "image",
            "parameters": {"hamming_threshold": 4, "min_confidence": 0.75},
            "input": {
                "samples": [
                    {"id": 1, "sample_path": str(base), "path": str(base), "sample_type": "image"},
                    {"id": 2, "sample_path": str(near), "path": str(near), "sample_type": "image"},
                    {"id": 3, "sample_path": str(unique), "path": str(unique), "sample_type": "image"},
                ]
            },
        },
        Context(),
    )

    assert result["ok"] is True
    assert len(result["suggestions"]) == 1
    suggestion = result["suggestions"][0]
    assert suggestion["sample_id"] == 2
    assert suggestion["issue_type"] == "near_duplicate_image"
    assert suggestion["suggested_action"] == "delete"
    assert suggestion["confidence"] >= 0.75
    assert suggestion["details"]["processing_result"] == "near_duplicate_detected"
    assert suggestion["details"]["duplicate_of_sample_id"] == 1


def test_image_near_duplicate_cleaning_algorithm_is_seeded_and_runs_through_backend(tmp_path):
    from backend.seed_data import DEFAULT_ALGORITHMS

    facade, _paths = build_services(tmp_path)
    dataset = facade.dataset_service.create_dataset("near-duplicate-images", "image", "")
    first = tmp_path / "image_a.pgm"
    second = tmp_path / "image_b.pgm"
    base_pixels = [[(x * 20 + y * 5) % 256 for x in range(10)] for y in range(10)]
    near_pixels = [row[:] for row in base_pixels]
    near_pixels[5][5] = min(255, near_pixels[5][5] + 1)
    write_pgm(first, base_pixels)
    write_pgm(second, near_pixels)
    facade.dataset_service.import_files(dataset["data"]["id"], [str(first), str(second)])

    for payload in DEFAULT_ALGORITHMS:
        facade.algorithm_service.create_algorithm(dict(payload))
    algorithms = {item["key"]: item for item in facade.algorithm_service.get_algorithms("cleaning", "")}
    algorithm_id = algorithms["cleaning.image_near_duplicate_detector"]["id"]

    task_id = facade.cleaning_service.create_task(
        dataset["data"]["id"],
        [algorithm_id],
        {"hamming_threshold": 4, "min_confidence": 0.75},
    )["data"]["task_id"]
    facade.task_manager.start(task_id)
    run_result = facade.cleaning_service.run_task(task_id)
    suggestions = facade.cleaning_service.list_suggestions(task_id, None, 1, 20)

    assert run_result["ok"] is True
    assert suggestions["total"] == 1
    item = suggestions["items"][0]
    assert item["issue_type"] == "near_duplicate_image"
    assert item["confidence"] >= 0.75
    assert item["suggested_action"] == "delete"
    assert item["details"]["processing_result"] == "near_duplicate_detected"


def test_seeded_image_denoise_algorithm_exposes_noise_threshold_only(tmp_path):
    from backend.seed_data import DEFAULT_ALGORITHMS

    facade, _paths = build_services(tmp_path)
    for payload in DEFAULT_ALGORITHMS:
        facade.algorithm_service.create_algorithm(dict(payload))

    algorithms = {item["key"]: item for item in facade.algorithm_service.get_algorithms("cleaning", "image")}
    resolution = algorithms["cleaning.image_resolution_filter"]
    denoise = algorithms["cleaning.image_denoise"]
    deblur = algorithms["cleaning.image_deblur"]

    assert [item["name"] for item in resolution["parameters"]] == ["min_width", "min_height", "min_file_kb"]
    assert [item["name"] for item in denoise["parameters"]] == ["noise_threshold", "min_confidence", "median_kernel_size"]
    assert denoise["parameters"][0]["default_value"] == 12.0
    assert denoise["parameters"][1]["default_value"] == 0.2
    assert denoise["parameters"][2]["default_value"] == 3
    assert denoise["output_contract"]["artifact_types"] == []
    assert [item["name"] for item in deblur["parameters"]] == ["blur_threshold", "min_confidence", "laplacian_ksize"]
    assert deblur["output_contract"]["artifact_types"] == []


def test_image_denoise_plugin_returns_delete_for_noisy_sample(monkeypatch):
    from plugins.cleaning import image_denoise

    class DummyPath:
        def __init__(self, raw):
            self.raw = raw

        def is_file(self):
            return True

        def __str__(self):
            return self.raw

    class Context:
        def is_cancel_requested(self):
            return False

        def set_progress(self, value, message):
            self.progress = (value, message)

    monkeypatch.setattr(image_denoise, "_sample_path", lambda sample: DummyPath(sample["sample_path"]))
    monkeypatch.setattr(image_denoise, "_noise_score", lambda path, kernel_size: 18.0)

    result = image_denoise.run(
        {
            "parameters": {"noise_threshold": 12.0, "min_confidence": 0.2, "median_kernel_size": 5},
            "input": {"samples": [{"id": 7, "sample_path": "C:/tmp/noisy.png"}]},
        },
        Context(),
    )

    assert result["ok"] is True
    assert len(result["suggestions"]) == 1
    assert result["suggestions"][0]["suggested_action"] == "delete"
    assert result["suggestions"][0]["details"]["processing_result"] == "filtered_out"
    assert result["suggestions"][0]["details"]["median_kernel_size"] == 5


def test_cleaning_apply_delete_marks_source_and_blocks_later_repair(tmp_path):
    from backend.errors import ValidationError

    facade, _paths = build_services(tmp_path)
    dataset = create_text_dataset(facade, tmp_path, name="apply-delete-ds")
    algorithm_id = create_algorithm(
        facade.algorithm_service,
        tmp_path,
        key="apply_delete_clean",
        body=(
            "from pathlib import Path\n"
            "def run(payload, context):\n"
            "    sample = payload['input']['samples'][0]\n"
            "    repaired = Path(payload['output']['output_dir']) / 'repaired.txt'\n"
            "    repaired.write_text('hello cleaned', encoding='utf-8')\n"
            "    return {'ok': True, 'suggestions': [\n"
            "        {'sample_id': sample['id'], 'issue_type': 'drop', 'suggested_action': 'delete', 'confidence': 0.8, 'message': 'delete me', 'details': {}},\n"
            "        {'sample_id': sample['id'], 'issue_type': 'repairable', 'suggested_action': 'repair', 'confidence': 0.9, 'message': 'repair me', 'details': {'output_file_path': str(repaired)}}\n"
            "    ]}\n"
        ),
    )

    task_id = facade.cleaning_service.create_task(dataset["data"]["id"], [algorithm_id], {})["data"]["task_id"]
    facade.task_manager.start(task_id)
    facade.cleaning_service.run_task(task_id)
    suggestions = facade.cleaning_service.list_suggestions(task_id, None, 1, 20)
    by_issue = {item["issue_type"]: item for item in suggestions["items"]}

    applied_delete = facade.cleaning_service.handle_suggestion(by_issue["drop"]["id"], "apply")
    assert applied_delete["data"]["status"] == "applied"

    dataset_samples = facade.dataset_service.list_samples(dataset["data"]["id"], 1, 20, "")
    assert any(item["status"] == "deleted" and item["id"] == by_issue["drop"]["sample_id"] for item in dataset_samples["items"])

    with pytest.raises(ValidationError):
        facade.cleaning_service.handle_suggestion(by_issue["repairable"]["id"], "apply")


def test_cleaning_apply_repair_requires_artifact_details(tmp_path):
    from backend.errors import ValidationError

    facade, _paths = build_services(tmp_path)
    dataset = create_text_dataset(facade, tmp_path, name="apply-missing-artifact-ds")
    algorithm_id = create_algorithm(
        facade.algorithm_service,
        tmp_path,
        key="apply_missing_artifact_clean",
        body=(
            "def run(payload, context):\n"
            "    sample = payload['input']['samples'][0]\n"
            "    return {'ok': True, 'suggestions': [{'sample_id': sample['id'], 'issue_type': 'repairable', 'suggested_action': 'repair', 'confidence': 0.9, 'message': 'repair me', 'details': {}}]}\n"
        ),
    )

    task_id = facade.cleaning_service.create_task(dataset["data"]["id"], [algorithm_id], {})["data"]["task_id"]
    facade.task_manager.start(task_id)
    facade.cleaning_service.run_task(task_id)
    suggestions = facade.cleaning_service.list_suggestions(task_id, None, 1, 20)

    with pytest.raises(ValidationError):
        facade.cleaning_service.handle_suggestion(suggestions["items"][0]["id"], "apply")


def test_image_cleaning_plugins_use_python39_compatible_optional_annotations():
    for plugin_path in [
        Path("plugins/cleaning/image_deblur.py"),
        Path("plugins/cleaning/image_denoise.py"),
    ]:
        source = plugin_path.read_text(encoding="utf-8")

        assert " | None" not in source
        assert "Optional[" in source
