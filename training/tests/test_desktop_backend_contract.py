from pathlib import Path


class _FakeImportBridge:
    def __init__(self):
        self.refreshed = False

    def ensure_default_settings(self):
        pass

    def seed_default_algorithms(self):
        pass

    def import_folder(self, dataset_id, folder_path, include_subfolders):
        return {"ok": True, "data": {"imported_count": 16, "failed_count": 0, "errors": []}}

    def get_datasets(self, page, page_size, status):
        self.refreshed = True
        return {"items": [], "total": 0, "page": page, "page_size": page_size}


def test_backend_bridge_imports_without_qt_runtime():
    from backend.qt.bridge import BackendBridge

    assert BackendBridge is not None


def test_backend_service_import_folder_returns_qml_status_and_refreshes(monkeypatch):
    import main

    fake_bridge = _FakeImportBridge()
    monkeypatch.setattr(main, "_build_backend", lambda: fake_bridge)
    service = main.BackendService()

    result = service.importFolder(7, "C:/data/ship_data", True)

    assert result["status"] == "success"
    assert result["data"]["imported_count"] == 16
    assert fake_bridge.refreshed is True


def test_data_manage_import_dialog_derives_name_from_selected_path():
    qml = Path("ui/views/DataManageView.qml").read_text(encoding="utf-8")

    assert 'if (inputName.text.trim() === "") return' not in qml
    assert "datasetNameFromPath" in qml
    assert "finalName = root.datasetNameFromPath(path)" in qml


def test_data_manage_defaults_and_file_detail_dialog_preview():
    qml = Path("ui/views/DataManageView.qml").read_text(encoding="utf-8")

    assert 'property string currentStage: "raw"' in qml
    assert "id: stageCombo" in qml
    assert "currentIndex: 1" in qml
    assert "id: importModeCombo" in qml
    assert 'model: ["导入文件", "导入文件夹"]' in qml
    assert "currentIndex: 1" in qml
    assert "id: inputType" in qml
    assert "id: samplePreviewDialog" in qml
    assert "function openSamplePreview(sample)" in qml
    assert "samplePreviewDialog.open()" in qml
    assert "source: root.previewSource" in qml
    assert "root.expandedSampleId" not in qml
    assert 'Label { text: "预览"' not in qml
    assert 'text: "预览"' not in qml


def test_data_clean_view_loads_cleaning_algorithms_from_backend_configuration():
    qml = Path("ui/views/DataCleanView.qml").read_text(encoding="utf-8")

    assert "backendService.getCleaningStrategies" in qml
    assert "cleaningAlgorithmGroups" in qml
    assert "algorithm_ids" in qml
    assert 'm: ["重复样本去重", "模糊/低质检测"]' not in qml


def test_data_clean_detail_view_shows_algorithms_images_and_colored_decisions():
    qml = Path("ui/views/DataCleanView.qml").read_text(encoding="utf-8")
    detail_view = qml.split('visible: root.viewMode === "fileDetail"', 1)[1]

    assert "function cleaningTaskTitle" in qml
    assert 'projectName: root.cleaningTaskTitle(task, sourceName)' in qml
    assert "Cleaning task for dataset" not in qml
    assert 'Text { text: "⚙️ 清洗参数"' not in detail_view
    assert "function normalizeAlgorithmIds" in qml
    assert "payload.algorithm_ids" in qml
    assert "algorithmIdsText" in qml
    assert "parametersJsonText" in qml
    assert "function decisionAccentColor" in qml
    assert "function decisionBackgroundColor" in qml
    assert "Image {" in detail_view
    assert "source: root.localFileUrl(samplePath)" in detail_view
    assert 'text: "清洗决策"' in detail_view
    assert 'text: "配置参数"' in detail_view
    assert "detailParameterItems" in detail_view
    assert detail_view.count("Layout.alignment: Qt.AlignVCenter") >= 3


def test_data_clean_running_progress_and_failure_popup():
    qml = Path("ui/views/DataCleanView.qml").read_text(encoding="utf-8")

    assert "property string cleaningErrorMessage" in qml
    assert "function showCleaningFailure" in qml
    assert "id: cleaningFailurePopup" in qml
    assert "root.showCleaningFailure(message)" in qml
    assert 'task.status === "failed"' in qml
    assert "task.error_message" in qml
    assert "runningHistoryProgress" in qml
    assert "width: parent.width * Math.max(0, Math.min(1, (model.progress || 0) / 100.0))" in qml


def test_sample_generation_detail_view_shows_algorithms_parameters_and_compact_results():
    qml = Path("ui/views/SampleGenView.qml").read_text(encoding="utf-8")
    detail_view = qml.split('visible: root.viewMode === "fileDetail"', 1)[1]

    assert 'Text { text: "⚙️ 生成参数"' not in detail_view
    assert "function normalizeAlgorithmIds" in qml
    assert "payload.algorithm_ids" in qml
    assert "algorithmIdsText" in qml
    assert "parametersJsonText" in qml
    assert 'text: "配置参数"' in detail_view
    assert "detailParameterItems" in detail_view
    assert "source: root.localFileUrl(generatedPath)" in detail_view
    assert "Layout.preferredWidth: 58" in detail_view
    assert 'text: "生成结果详情"' in detail_view
    assert detail_view.count("Layout.alignment: Qt.AlignVCenter") >= 4


def test_sample_generation_history_shows_generated_dataset_name():
    qml = Path("ui/views/SampleGenView.qml").read_text(encoding="utf-8")

    assert 'text: "生成数据集: "' in qml
    assert "model.generatedDataset ||" in qml
    assert "function generationTaskTitle" in qml
    assert 'projectName: root.generationTaskTitle(task, sourceName)' in qml
    assert "Generation task for dataset" not in qml


def test_sample_generation_running_progress_and_failure_popup():
    qml = Path("ui/views/SampleGenView.qml").read_text(encoding="utf-8")

    assert "property string generationErrorMessage" in qml
    assert "function showGenerationFailure" in qml
    assert "id: generationFailurePopup" in qml
    assert "root.showGenerationFailure(message)" in qml
    assert 'task.status === "failed"' in qml
    assert "task.error_message" in qml
    assert "runningGenerationProgress" in qml
    assert "width: parent.width * Math.max(0, Math.min(1, (model.progress || 0) / 100.0))" in qml


def test_default_backend_facade_can_create_dataset(tmp_path):
    from backend import (
        BackendPaths,
        BackendServiceFacade,
        create_backend_engine,
        create_session_factory,
        initialize_backend_database,
    )
    from backend.qt.bridge import BackendBridge

    root = tmp_path / "backend-root"
    paths = BackendPaths(root=root)
    engine = create_backend_engine(paths.database_path)
    initialize_backend_database(engine)
    facade = BackendServiceFacade.build(
        paths=paths,
        session_factory=create_session_factory(engine),
    )
    bridge = BackendBridge(facade=facade)

    result = bridge.create_dataset("contract-demo", "text", "")

    assert result["ok"] is True
    assert Path(result["data"]["storage_path"]).exists()


def test_bridge_dataset_payload_has_qml_compatibility_fields(tmp_path):
    from backend import (
        BackendPaths,
        BackendServiceFacade,
        create_backend_engine,
        create_session_factory,
        initialize_backend_database,
    )
    from backend.qt.bridge import BackendBridge

    paths = BackendPaths(root=tmp_path / "backend-root")
    engine = create_backend_engine(paths.database_path)
    initialize_backend_database(engine)
    bridge = BackendBridge(
        BackendServiceFacade.build(paths=paths, session_factory=create_session_factory(engine))
    )
    bridge.create_dataset("payload-demo", "text", "")

    page = bridge.get_datasets(1, 20, "")

    assert page["items"][0]["type"] == "文本"
    assert page["items"][0]["sampleCount"] == 0
    assert page["items"][0]["size"] == "0 B"


def test_bridge_normalizes_chinese_modality_labels(tmp_path):
    from backend import (
        BackendPaths,
        BackendServiceFacade,
        create_backend_engine,
        create_session_factory,
        initialize_backend_database,
    )
    from backend.qt.bridge import BackendBridge

    paths = BackendPaths(root=tmp_path / "backend-root")
    engine = create_backend_engine(paths.database_path)
    initialize_backend_database(engine)
    bridge = BackendBridge(
        BackendServiceFacade.build(paths=paths, session_factory=create_session_factory(engine))
    )

    created = bridge.create_dataset("image-demo", "图像", "")
    page = bridge.get_datasets(1, 20, "")

    assert created["ok"] is True
    assert page["items"][0]["modality"] == "image"
    assert page["items"][0]["type"] == "图像"


def test_bridge_get_algorithms_keeps_empty_modality_as_unfiltered_query(tmp_path):
    from backend import (
        BackendPaths,
        BackendServiceFacade,
        create_backend_engine,
        create_session_factory,
        initialize_backend_database,
    )
    from backend.qt.bridge import BackendBridge
    from backend.seed_data import DEFAULT_ALGORITHMS

    paths = BackendPaths(root=tmp_path / "backend-root")
    engine = create_backend_engine(paths.database_path)
    initialize_backend_database(engine)
    facade = BackendServiceFacade.build(paths=paths, session_factory=create_session_factory(engine))
    bridge = BackendBridge(facade=facade)

    for payload in DEFAULT_ALGORITHMS:
        facade.algorithm_service.create_algorithm(dict(payload))

    algorithms = bridge.get_algorithms("", "")

    assert {item["key"] for item in algorithms} >= {
        "cleaning.duplicate_detector",
        "cleaning.image_near_duplicate_detector",
        "generation.copy_augmenter",
        "generation.image.geometric_transform",
        "evaluation.sample_count_comparator",
        "evaluation.multi_agent_simulation",
    }


def test_seed_default_algorithms_merges_legacy_resolution_cleaner(tmp_path):
    from backend import (
        BackendPaths,
        BackendServiceFacade,
        create_backend_engine,
        create_session_factory,
        initialize_backend_database,
    )
    from backend.qt.bridge import BackendBridge

    paths = BackendPaths(root=tmp_path / "backend-root")
    engine = create_backend_engine(paths.database_path)
    initialize_backend_database(engine)
    facade = BackendServiceFacade.build(paths=paths, session_factory=create_session_factory(engine))
    bridge = BackendBridge(facade=facade)

    facade.algorithm_service.create_algorithm(
        {
            "key": "图片低分辨率清洗",
            "name": "图片低分辨率清洗",
            "category": "cleaning",
            "modality": "image",
            "entry_type": "python_function",
            "script_path": str(paths.plugins_dir / "user" / "desktop_image_resolution_cleaner.py"),
            "callable_name": "run",
            "input_contract": {"dataset_required": True, "sample_required": True},
            "output_contract": {"produces": ["suggestions"]},
            "parameters": [],
        }
    )

    bridge.seed_default_algorithms()
    algorithms = bridge.get_algorithms("cleaning", "image")

    resolution_algorithms = [item for item in algorithms if item["name"] == "图片低分辨率清洗"]
    assert len(resolution_algorithms) == 1
    assert resolution_algorithms[0]["key"] == "cleaning.image_resolution_filter"


def test_bridge_get_task_logs_serializes_repository_dict_rows(tmp_path):
    from backend import (
        BackendPaths,
        BackendServiceFacade,
        create_backend_engine,
        create_session_factory,
        initialize_backend_database,
    )
    from backend.qt.bridge import BackendBridge
    from backend.seed_data import DEFAULT_ALGORITHMS

    source_dir = tmp_path / "source"
    source_dir.mkdir()
    (source_dir / "dup_a.txt").write_text("same payload", encoding="utf-8")
    (source_dir / "dup_b.txt").write_text("same payload", encoding="utf-8")

    paths = BackendPaths(root=tmp_path / "backend-root")
    engine = create_backend_engine(paths.database_path)
    initialize_backend_database(engine)
    facade = BackendServiceFacade.build(paths=paths, session_factory=create_session_factory(engine))
    bridge = BackendBridge(facade=facade)

    for payload in DEFAULT_ALGORITHMS:
        facade.algorithm_service.create_algorithm(dict(payload))

    created = bridge.create_dataset("logs-demo", "text", "")
    dataset_id = created["data"]["id"]
    imported = bridge.import_files(
        dataset_id,
        [str(source_dir / "dup_a.txt"), str(source_dir / "dup_b.txt")],
    )
    assert imported["ok"] is True

    algorithms = {item["key"]: item for item in bridge.get_algorithms("", "")}
    task = bridge.create_cleaning_task(dataset_id, [algorithms["cleaning.duplicate_detector"]["id"]], {})
    task_id = task["data"]["task_id"]

    started = bridge.run_cleaning_task(task_id)
    assert started["ok"] is True

    logs = bridge.get_task_logs(task_id, 1, 20)

    assert logs["total"] >= 1
    assert logs["items"][0]["task_id"] == task_id
    assert isinstance(logs["items"][0]["payload"], dict)
    assert "created_at" in logs["items"][0]
