from pathlib import Path


def build_dataset_service(tmp_path):
    from backend import BackendPaths, create_backend_engine, create_session_factory, initialize_backend_database
    from backend.repositories import DatasetRepository, LogRepository
    from backend.services import DatasetService

    paths = BackendPaths(tmp_path / "backend-root")
    engine = create_backend_engine(paths.database_path)
    initialize_backend_database(engine)
    session_factory = create_session_factory(engine)
    service = DatasetService(
        paths=paths,
        session_factory=session_factory,
        dataset_repository=DatasetRepository(session_factory),
        log_repository=LogRepository(session_factory),
    )
    return service, paths


def test_dataset_service_creates_dataset_and_imports_files(tmp_path):
    service, paths = build_dataset_service(tmp_path)
    source_file = tmp_path / "sample.txt"
    source_file.write_text("hello dataset service", encoding="utf-8")

    created = service.create_dataset("demo", "text", "demo dataset")
    dataset_id = created["data"]["id"]

    imported = service.import_files(dataset_id, [str(source_file)])
    datasets = service.get_datasets(page=1, page_size=20, status="")
    datasets_v2 = service.list_datasets(page=1, page_size=20, status="")
    samples = service.get_dataset_samples(dataset_id, page=1, page_size=20, status="")
    samples_v2 = service.list_samples(dataset_id, page=1, page_size=20, status="")
    preview = service.get_dataset_preview_samples(dataset_id, limit=5, status="")
    preview_v2 = service.preview_samples(dataset_id, limit=5, status="")
    stats = service.get_dataset_stats(dataset_id)
    stats_v2 = service.get_statistics(dataset_id)

    assert created["ok"] is True
    assert imported["ok"] is True
    assert imported["data"]["imported_count"] == 1
    assert datasets["total"] == 1
    assert datasets_v2["items"][0]["id"] == dataset_id
    assert datasets["items"][0]["name"] == "demo"
    assert samples["total"] == 1
    assert samples_v2["items"][0]["name"] == "sample.txt"
    assert samples["items"][0]["name"] == "sample.txt"
    assert samples["items"][0]["status"] == "raw"
    assert preview["total"] == 1
    assert preview_v2["items"][0]["name"] == "sample.txt"
    assert preview["items"][0]["dataset_id"] == dataset_id
    assert preview["items"][0]["relative_path"] == "sample.txt"
    assert stats["data"]["total_samples"] == 1
    assert stats_v2["data"]["size_bytes"] == stats["data"]["size_bytes"]
    assert stats["data"]["modalities"]["text"] == 1
    dataset_root = Path(created["data"]["storage_path"])
    assert dataset_root.name.startswith(f"{dataset_id}_demo")
    assert (dataset_root / "raw").is_dir()
    assert (dataset_root / "cleaned").is_dir()
    assert (dataset_root / "generated").is_dir()
    assert (dataset_root / "preview").is_dir()
    assert preview["items"][0]["file_path"].replace("\\", "/").endswith("raw/sample.txt")


def test_dataset_service_delete_purges_files(tmp_path):
    service, _paths = build_dataset_service(tmp_path)
    source_file = tmp_path / "delete-me.txt"
    source_file.write_text("delete path", encoding="utf-8")

    created = service.create_dataset("to-delete", "text", "")
    dataset_id = created["data"]["id"]
    service.import_files(dataset_id, [str(source_file)])
    before_delete = service.get_dataset(dataset_id)
    dataset_dir = Path(before_delete["data"]["storage_path"])

    deleted = service.delete_dataset(dataset_id)
    after_delete = service.get_dataset(dataset_id, include_deleted=True)
    listed = service.get_datasets(page=1, page_size=20, status="")

    assert deleted["ok"] is True
    assert after_delete["data"]["status"] == "deleted"
    assert not dataset_dir.exists()
    assert after_delete["data"]["storage_path"] == ""
    assert listed["total"] == 0
    assert service.get_data_type_distribution()["data"] == {}


def test_dataset_service_rejects_purge_for_active_dataset(tmp_path):
    service, _paths = build_dataset_service(tmp_path)
    created = service.create_dataset("active", "text", "")
    dataset_id = created["data"]["id"]

    try:
        service.purge_dataset_files(dataset_id)
        assert False, "purge should require a logically deleted dataset"
    except Exception as exc:
        assert "deleted" in str(exc).lower()


def test_dataset_service_reports_recent_activity_and_system_stats(tmp_path):
    service, _paths = build_dataset_service(tmp_path)
    source_file = tmp_path / "activity.txt"
    source_file.write_text("activity", encoding="utf-8")

    created = service.create_dataset("activity-demo", "text", "")
    dataset_id = created["data"]["id"]
    service.import_files(dataset_id, [str(source_file)])

    activities = service.get_recent_activities(limit=10)
    stats = service.get_system_stats()
    distribution = service.get_data_type_distribution()

    assert activities
    assert any(item["resource_type"] == "dataset" for item in activities)
    assert stats["data"]["total_datasets"] == 1
    assert stats["data"]["total_samples"] == 1
    assert distribution["data"]["text"] == 1


def test_dataset_service_import_folder_keeps_relative_paths(tmp_path):
    service, _paths = build_dataset_service(tmp_path)
    folder = tmp_path / "nested"
    nested = folder / "part-a"
    nested.mkdir(parents=True)
    source_file = nested / "sample.txt"
    source_file.write_text("nested data", encoding="utf-8")

    created = service.create_dataset("folder-demo", "text", "")
    dataset_id = created["data"]["id"]
    imported = service.import_folder(dataset_id, str(folder), include_subfolders=True)
    samples = service.get_dataset_samples(dataset_id, page=1, page_size=20, status="")

    assert imported["ok"] is True
    assert imported["data"]["imported_count"] == 1
    assert samples["items"][0]["relative_path"] == "part-a/sample.txt"
    assert "raw/part-a/sample.txt" in samples["items"][0]["file_path"].replace("\\", "/")


def test_dataset_service_import_folder_parses_yolo_bbox_labels(tmp_path):
    service, _paths = build_dataset_service(tmp_path)
    folder = tmp_path / "yolo"
    (folder / "train" / "images").mkdir(parents=True)
    (folder / "train" / "labels").mkdir(parents=True)
    (folder / "data.yaml").write_text("names:\n  0: ship\n", encoding="utf-8")
    (folder / "train" / "images" / "sample.jpg").write_bytes(b"image")
    (folder / "train" / "labels" / "sample.txt").write_text("0 0.5 0.5 0.2 0.3\n", encoding="utf-8")

    created = service.create_dataset("yolo-folder", "image", "")
    dataset_id = created["data"]["id"]
    imported = service.import_folder(dataset_id, str(folder), include_subfolders=True)
    samples = service.get_dataset_samples(dataset_id, page=1, page_size=20, status="")

    assert imported["ok"] is True
    assert imported["data"]["imported_count"] == 1
    assert samples["total"] == 1
    assert samples["items"][0]["relative_path"] == "train/images/sample.jpg"
    assert samples["items"][0]["labels"][0]["type"] == "detection"
    assert samples["items"][0]["labels"][0]["class_id"] == 0
    assert samples["items"][0]["labels"][0]["class_name"] == "ship"
    assert samples["items"][0]["labels"][0]["bbox"] == [0.5, 0.5, 0.2, 0.3]


def test_dataset_service_import_dataset_bundle_supports_labels_and_optional_test_set(tmp_path):
    service, _paths = build_dataset_service(tmp_path)
    train_root = tmp_path / "train"
    test_root = tmp_path / "test"
    (train_root / "deep" / "class_a").mkdir(parents=True)
    (test_root / "class_b").mkdir(parents=True)
    train_file = train_root / "deep" / "class_a" / "a.png"
    test_file = test_root / "class_b" / "b.png"
    train_file.write_bytes(b"\x89PNG\r\n\x1a\n")
    test_file.write_bytes(b"\x89PNG\r\n\x1a\n")
    label_file = tmp_path / "labels.txt"
    label_file.write_text(f"{train_file} 7\n", encoding="utf-8")

    imported = service.import_dataset_bundle(
        {
            "dataset_name": "bundle-train",
            "source_path": str(train_root),
            "label_path": str(label_file),
            "test_path": str(test_root),
            "modality": "auto",
        }
    )

    assert imported["ok"] is True
    assert imported["data"]["imported_count"] == 2
    train_dataset = imported["data"]["train_dataset"]
    test_dataset = imported["data"]["test_dataset"]
    assert train_dataset["stage"] == "raw"
    assert train_dataset["tags"] == ["imported", "raw"]
    assert train_dataset["extra"]["label_mode"] == "file"
    assert test_dataset["stage"] == "test"
    assert test_dataset["parent_dataset_id"] == train_dataset["id"]

    train_samples = service.get_dataset_samples(train_dataset["id"], page=1, page_size=20, status="")
    test_samples = service.get_dataset_samples(test_dataset["id"], page=1, page_size=20, status="")
    assert train_samples["items"][0]["labels"][0]["class_id"] == 7
    assert train_samples["items"][0]["labels"][0]["source"] == str(label_file)
    assert test_samples["items"][0]["labels"][0]["class_name"] == "class_b"


def test_dataset_service_import_dataset_bundle_parses_yolo_detection_records(tmp_path):
    service, _paths = build_dataset_service(tmp_path)
    source_root = tmp_path / "bundle-yolo"
    (source_root / "images").mkdir(parents=True)
    (source_root / "labels").mkdir(parents=True)
    (source_root / "data.yaml").write_text("names:\n- ship\n", encoding="utf-8")
    (source_root / "images" / "a.jpg").write_bytes(b"image-a")
    (source_root / "labels" / "a.txt").write_text("0 0.25 0.75 0.5 0.1\n", encoding="utf-8")

    imported = service.import_dataset_bundle({"dataset_name": "bundle-yolo", "source_path": str(source_root), "modality": "auto"})
    dataset = imported["data"]["train_dataset"]
    samples = service.get_dataset_samples(dataset["id"], page=1, page_size=20, status="")

    assert imported["ok"] is True
    assert imported["data"]["imported_count"] == 1
    assert dataset["extra"]["import_format"] == "yolo_detection"
    assert samples["total"] == 1
    assert samples["items"][0]["labels"][0]["type"] == "detection"
    assert samples["items"][0]["labels"][0]["bbox"] == [0.25, 0.75, 0.5, 0.1]


def test_dataset_service_import_dataset_bundle_allows_empty_test_set(tmp_path):
    service, _paths = build_dataset_service(tmp_path)
    source_root = tmp_path / "source"
    (source_root / "class_a").mkdir(parents=True)
    (source_root / "class_a" / "a.txt").write_text("sample", encoding="utf-8")

    imported = service.import_dataset_bundle({"dataset_name": "bundle", "source_path": str(source_root)})

    assert imported["ok"] is True
    assert imported["data"]["imported_count"] == 1
    assert imported["data"]["test_dataset"] is None
    assert imported["data"]["train_dataset"]["stage"] == "raw"


def test_dataset_service_imports_sonar_oltr_project_with_labels_and_split_metadata(tmp_path):
    service, _paths = build_dataset_service(tmp_path)
    project_root = tmp_path / "Sonar-OLTR-main"
    code_dir = project_root / "code"
    dataset_dir = project_root / "data" / "NKSID"
    class_a = dataset_dir / "big_propeller"
    class_b = dataset_dir / "tire"
    code_dir.mkdir(parents=True)
    class_a.mkdir(parents=True)
    class_b.mkdir(parents=True)
    (class_a / "img_001.jpg").write_bytes(b"image-a")
    (class_b / "img_002.jpg").write_bytes(b"image-b")
    (class_b / "img_003.jpg").write_bytes(b"image-c")
    (dataset_dir / "train_abs.txt").write_text(
        "../data/NKSID/big_propeller/img_001.jpg 0\n"
        "../data/NKSID/tire/img_002.jpg 1\n",
        encoding="utf-8",
    )
    (dataset_dir / "kfold_val.txt").write_text("../data/NKSID/tire/img_003.jpg 1\n", encoding="utf-8")

    imported = service.import_sonar_oltr_project(str(project_root), "", "", "", "")

    assert imported["ok"] is True
    assert imported["data"]["imported_count"] == 1
    dataset = imported["data"]["datasets"][0]
    assert dataset["name"] == "NKSID"
    assert dataset["status"] == "imported"
    assert dataset["tags"] == ["underwater", "sonar_oltr", "labeled"]
    assert dataset["extra"]["dataset_format"] == "sonar_oltr"
    assert dataset["extra"]["split_files"]["train"].endswith("train_abs.txt")
    assert dataset["extra"]["split_files"]["test"].endswith("kfold_val.txt")
    assert dataset["extra"]["class_distribution"] == {"big_propeller": 1, "tire": 2}

    samples = service.get_dataset_samples(dataset["id"], page=1, page_size=20, status="")
    labels_by_name = {item["name"]: item["labels"][0] for item in samples["items"]}
    assert samples["total"] == 3
    assert labels_by_name["img_001.jpg"]["class_id"] == 0
    assert labels_by_name["img_001.jpg"]["class_name"] == "big_propeller"
    assert labels_by_name["img_003.jpg"]["split"] == "test"


def test_dataset_service_skips_malformed_label_rows_but_keeps_valid_samples(tmp_path):
    service, _paths = build_dataset_service(tmp_path)
    project_root = tmp_path / "Sonar-OLTR-main"
    dataset_dir = project_root / "data" / "NKSID"
    class_dir = dataset_dir / "tire"
    class_dir.mkdir(parents=True)
    (class_dir / "img_001.jpg").write_bytes(b"image")
    label_file = dataset_dir / "train_abs.txt"
    label_file.write_text(
        "../data/NKSID/tire/img_001.jpg 1\n"
        "../data/NKSID/tire/img_001.jpg not-a-number\n",
        encoding="utf-8",
    )

    imported = service.import_sonar_oltr_project(str(project_root), "", "", "", "")
    dataset = imported["data"]["datasets"][0]
    samples = service.get_dataset_samples(dataset["id"], page=1, page_size=20, status="")

    assert imported["ok"] is True
    assert samples["total"] == 1
    assert samples["items"][0]["labels"][0]["class_id"] == 1


def test_dataset_service_reports_invalid_json_parameter_file_as_validation_error(tmp_path):
    from backend.errors import ValidationError

    service, _paths = build_dataset_service(tmp_path)
    params = tmp_path / "params.json"
    params.write_text("{bad json", encoding="utf-8")

    try:
        service.import_sonar_oltr_project("", str(tmp_path), "", "", str(params))
        assert False, "invalid JSON parameters should be a validation error"
    except ValidationError as exc:
        assert "parameter" in str(exc).lower()


def test_dataset_service_imports_generic_folder_labels_and_stable_split(tmp_path):
    service, _paths = build_dataset_service(tmp_path)
    train_root = tmp_path / "train"
    (train_root / "alpha").mkdir(parents=True)
    (train_root / "beta").mkdir(parents=True)
    for index in range(5):
        (train_root / "alpha" / f"a{index}.jpg").write_bytes(b"a")
    for index in range(5):
        (train_root / "beta" / f"b{index}.jpg").write_bytes(b"b")

    imported = service.import_sonar_oltr_project("", str(train_root), "", "", "")
    dataset = imported["data"]["datasets"][0]
    samples = service.get_dataset_samples(dataset["id"], page=1, page_size=20, status="")
    splits = {item["labels"][0]["split"] for item in samples["items"]}
    class_names = {item["labels"][0]["class_name"] for item in samples["items"]}

    assert imported["ok"] is True
    assert dataset["extra"]["dataset_format"] == "folder_classification"
    assert dataset["extra"]["split_method"] == "stable_8_2"
    assert splits == {"train", "test"}
    assert class_names == {"alpha", "beta"}


def test_dataset_payload_includes_lineage_tags_extra_and_sample_preview_contract(tmp_path):
    from backend.models import Dataset

    service, _paths = build_dataset_service(tmp_path)
    source_file = tmp_path / "preview.txt"
    source_file.write_text("hello preview", encoding="utf-8")

    created = service.create_dataset("preview-demo", "text", "")
    dataset_id = created["data"]["id"]
    service.import_files(dataset_id, [str(source_file)])
    sample = service.get_dataset_samples(dataset_id, page=1, page_size=20, status="")["items"][0]

    with service.session_factory() as session:
        dataset = session.query(Dataset).filter(Dataset.id == dataset_id).first()
        dataset.status = "cleaned"
        dataset.parent_dataset_id = 123
        dataset.tags_json = ["cleaned"]
        dataset.extra_json = {"source": "unit-test"}
        session.commit()

    dataset_payload = service.get_dataset(dataset_id)["data"]
    preview = service.get_sample_preview(sample["id"])

    assert dataset_payload["parent_dataset_id"] == 123
    assert dataset_payload["tags"] == ["cleaned"]
    assert dataset_payload["extra"] == {"source": "unit-test"}
    assert preview["ok"] is True
    assert preview["data"]["sample_id"] == sample["id"]
    assert preview["data"]["preview_kind"] == "text"
    assert preview["data"]["text_content"] == "hello preview"
    assert preview["data"]["error"] == ""


def test_sample_preview_detects_image_audio_unknown_and_text_decode_errors(tmp_path):
    service, _paths = build_dataset_service(tmp_path)
    image_file = tmp_path / "image.png"
    image_file.write_bytes(b"\x89PNG\r\n\x1a\n")
    audio_file = tmp_path / "sound.wav"
    audio_file.write_bytes(b"RIFF\x24\x00\x00\x00WAVEfmt ")
    binary_file = tmp_path / "payload.bin"
    binary_file.write_bytes(b"\x00\x01\x02")
    bad_text_file = tmp_path / "bad.txt"
    bad_text_file.write_bytes(b"\xff\xfe\xfa")

    image_ds = service.create_dataset("image-preview", "image", "")["data"]["id"]
    audio_ds = service.create_dataset("audio-preview", "audio", "")["data"]["id"]
    other_ds = service.create_dataset("other-preview", "other", "")["data"]["id"]
    text_ds = service.create_dataset("bad-text-preview", "text", "")["data"]["id"]
    service.import_files(image_ds, [str(image_file)])
    service.import_files(audio_ds, [str(audio_file)])
    service.import_files(other_ds, [str(binary_file)])
    service.import_files(text_ds, [str(bad_text_file)])

    image_sample = service.get_dataset_samples(image_ds, 1, 20, "")["items"][0]
    audio_sample = service.get_dataset_samples(audio_ds, 1, 20, "")["items"][0]
    other_sample = service.get_dataset_samples(other_ds, 1, 20, "")["items"][0]
    bad_text_sample = service.get_dataset_samples(text_ds, 1, 20, "")["items"][0]

    assert service.get_sample_preview(image_sample["id"])["data"]["preview_kind"] == "image"
    assert service.get_sample_preview(audio_sample["id"])["data"]["preview_kind"] == "audio"
    assert service.get_sample_preview(other_sample["id"])["data"]["preview_kind"] == "file"
    bad_preview = service.get_sample_preview(bad_text_sample["id"])["data"]
    assert bad_preview["preview_kind"] == "text"
    assert bad_preview["text_content"] == ""
    assert bad_preview["error"]
