from __future__ import annotations

import json
import shutil
from dataclasses import field
from .._compat import to_local_isoformat
from .._compat import slots_dataclass
from pathlib import Path

from ..errors import NotFoundError, ValidationError
from ..models import Dataset, Sample
from ..storage import FileIndexer
from .base import ServiceBase


def _normalize_manifest_label(label) -> dict:
    """将 manifest 中的 label 规范化为统一的 dict 格式，保留 bbox 等字段。"""
    if isinstance(label, dict):
        result = {
            "type": label.get("type", "classification"),
            "class_name": str(label.get("class_name", label.get("name", ""))),
            "source": "manifest",
        }
        bbox = label.get("bbox")
        if bbox and len(bbox) >= 4:
            result["bbox"] = [float(v) for v in bbox[:4]]
        class_id = label.get("class_id")
        if class_id is not None:
            result["class_id"] = int(class_id)
        # 保留其他字段
        for key in ("split", "confidence", "area"):
            val = label.get(key)
            if val is not None:
                result[key] = val
        return result
    return {"type": "classification", "class_name": str(label), "source": "manifest"}


@slots_dataclass
class DatasetService(ServiceBase):
    dataset_repository: object
    log_repository: object
    file_indexer: FileIndexer = field(default_factory=FileIndexer)
    _IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".gif", ".webp", ".tif", ".tiff"}
    _TRAINING_PARAMETER_ALLOWLIST = {
        "dataset",
        "backbone",
        "bs",
        "lr",
        "es",
        "train_class_num",
        "test_class_num",
        "p_value",
        "k_value",
        "resume",
        "method_name",
        "alpha",
        "gamma",
    }

    def create_dataset(self, name: str, modality: str, description: str = "") -> dict:
        clean_name = (name or "").strip()
        if not clean_name:
            raise ValidationError("Dataset name is required.")
        if not modality:
            raise ValidationError("Dataset modality is required.")

        with self.session_factory() as session:
            dataset = self.dataset_repository.create_dataset(
                session,
                name=clean_name,
                modality=modality,
                description=description or "",
                status="created",
                storage_path="",
            )
            dataset_dir = self._allocate_dataset_dir(dataset.id, clean_name)
            dataset.storage_path = str(dataset_dir)
            self.log_repository.add(
                session,
                level="info",
                action="create_dataset",
                resource_type="dataset",
                resource_id=str(dataset.id),
                message=f"Created dataset {clean_name}",
            )
            session.commit()
            return {"ok": True, "data": self._serialize_dataset(dataset)}

    def update_dataset(self, dataset_id: int, name: str, type_name: str) -> dict:
        with self.session_factory() as session:
            dataset = self._require_dataset(session, dataset_id, include_deleted=True)
            clean_name = (name or dataset.name).strip()
            if not clean_name:
                raise ValidationError("Dataset name is required.")
            duplicate = (
                session.query(Dataset)
                .filter(Dataset.id != dataset.id, Dataset.name == clean_name, Dataset.is_deleted.is_(False))
                .first()
            )
            if duplicate:
                raise ValidationError(f"Dataset name '{clean_name}' already exists.")
            self._rename_dataset_storage(session, dataset, clean_name)
            dataset.name = clean_name
            if type_name:
                dataset.modality = type_name
            self.log_repository.add(
                session,
                level="info",
                action="update_dataset",
                resource_type="dataset",
                resource_id=str(dataset.id),
                message=f"Updated dataset {dataset.name}",
            )
            session.commit()
            return {"ok": True, "data": self._serialize_dataset(dataset)}

    def delete_dataset(self, dataset_id: int) -> dict:
        with self.session_factory() as session:
            dataset = self._require_dataset(session, dataset_id, include_deleted=False)
            self.dataset_repository.soft_delete(dataset)
            dataset_dir = Path(dataset.storage_path) if dataset.storage_path else None
            if dataset_dir and dataset_dir.exists():
                shutil.rmtree(dataset_dir)
            dataset.storage_path = ""
            self.log_repository.add(
                session,
                level="info",
                action="delete_dataset",
                resource_type="dataset",
                resource_id=str(dataset.id),
                message=f"Deleted dataset {dataset.name} (files purged)",
            )
            session.commit()
            return {"ok": True, "data": self._serialize_dataset(dataset)}

    def purge_dataset_files(self, dataset_id: int) -> dict:
        with self.session_factory() as session:
            dataset = self._require_dataset(session, dataset_id, include_deleted=True)
            if dataset.status != "deleted":
                raise ValidationError("Dataset must be logically deleted before files can be purged.")
            dataset_dir = Path(dataset.storage_path) if dataset.storage_path else None
            if dataset_dir and dataset_dir.exists():
                shutil.rmtree(dataset_dir)
            dataset.storage_path = ""
            self.log_repository.add(
                session,
                level="info",
                action="purge_dataset_files",
                resource_type="dataset",
                resource_id=str(dataset.id),
                message=f"Purged dataset files for {dataset.name}",
            )
            session.commit()
            return {"ok": True, "data": self._serialize_dataset(dataset)}

    def get_dataset(self, dataset_id: int, include_deleted: bool = False) -> dict:
        with self.session_factory() as session:
            dataset = self._require_dataset(session, dataset_id, include_deleted=include_deleted)
            return {"ok": True, "data": self._serialize_dataset(dataset)}

    def get_datasets(self, page: int, page_size: int, status: str) -> dict:
        with self.session_factory() as session:
            total, items = self.dataset_repository.list_datasets(
                session,
                page=max(page, 1),
                page_size=max(page_size, 1),
                status=status or "",
                include_deleted=False,
            )
            return {
                "total": total,
                "items": [self._serialize_dataset(item) for item in items],
                "page": max(page, 1),
                "page_size": max(page_size, 1),
            }

    def list_datasets(self, page: int, page_size: int, status: str) -> dict:
        return self.get_datasets(page=page, page_size=page_size, status=status)

    def import_files(self, dataset_id: int, file_paths: list[str]) -> dict:
        imported_count = 0
        failed_count = 0
        errors: list[dict] = []
        with self.session_factory() as session:
            dataset = self._require_dataset(session, dataset_id, include_deleted=False)
            records = [{"source_path": Path(file_path), "relative_path": Path(file_path).name} for file_path in file_paths]
            for record in records:
                source = record["source_path"]
                if not source.is_file():
                    failed_count += 1
                    errors.append({"path": str(source), "reason": "missing_file"})
                    continue
                copied = self.file_indexer.copy_into_dataset(source, Path(dataset.storage_path) / "raw", record["relative_path"])
                sample = self.dataset_repository.create_sample(
                    session,
                    dataset_id=dataset.id,
                    source_sample_id=None,
                    name=copied.name,
                    modality=dataset.modality,
                    file_path=str(copied),
                    relative_path=Path(record["relative_path"]).as_posix(),
                    sha256=None,  # 导入时跳过 SHA256，后续可后台批量计算
                    mime_type=self.file_indexer.detect_mime_type(copied),
                    extension=copied.suffix.lower(),
                    size_bytes=copied.stat().st_size,
                    status="raw",
                    metadata_json={},
                    labels_json=[],
                )
                imported_count += 1
                self.log_repository.add(
                    session,
                    level="info",
                    action="import_file",
                    resource_type="sample",
                    resource_id=str(sample.id),
                    message=f"Imported file {copied.name} into dataset {dataset.name}",
                )
            self._refresh_dataset_stats(session, dataset)
            session.commit()
            return {"ok": True, "data": {"imported_count": imported_count, "failed_count": failed_count, "errors": errors}}

    def import_folder_with_stage(self, dataset_name: str, folder_path: str, stage: str = "test") -> dict:
        folder = Path(folder_path)
        if not folder.is_dir():
            raise ValidationError("Import folder does not exist.")
        modality = self._detect_modality_from_folder(folder)
        created = self.create_dataset(dataset_name, modality)
        dataset_id = created["data"]["id"]
        with self.session_factory() as session:
            dataset = self.dataset_repository.get_dataset(session, dataset_id)
            if dataset:
                dataset.status = stage
                session.commit()
        imported = self.import_folder(dataset_id, folder_path, include_subfolders=True)
        return {
            "ok": True,
            "data": {
                "dataset_id": dataset_id,
                "dataset_name": dataset_name,
                "imported_count": imported.get("data", {}).get("imported_count", 0),
            },
        }

    def _detect_modality_from_folder(self, folder: Path) -> str:
        from collections import Counter
        exts: Counter[str] = Counter()
        for f in folder.rglob("*"):
            if f.is_file():
                exts[f.suffix.lower()] += 1
        image_exts = {".jpg", ".jpeg", ".png", ".bmp", ".gif", ".tiff"}
        text_exts = {".txt", ".md", ".csv", ".json", ".xml", ".yaml"}
        audio_exts = {".wav", ".mp3", ".flac", ".ogg"}
        if any(e in image_exts for e in exts if exts[e] > 0):
            return "image"
        if any(e in text_exts for e in exts if exts[e] > 0):
            return "text"
        if any(e in audio_exts for e in exts if exts[e] > 0):
            return "audio"
        return "other"

    def import_folder(self, dataset_id: int, folder_path: str, include_subfolders: bool) -> dict:
        folder = Path(folder_path)
        if not folder.is_dir():
            raise ValidationError("Import folder does not exist.")

        # Build label lookup from manifest if present
        label_map: dict[str, list[dict]] = {}
        manifest_path = folder / "dataset_manifest.json"
        if manifest_path.is_file():
            import traceback
            try:
                with open(manifest_path, "r", encoding="utf-8") as f:
                    manifest = json.load(f)
                samples_raw = manifest.get("samples") or []
                # 支持两种格式: dict-of-dicts {"0": {...}} 或 list-of-dicts [{...}]
                entries = samples_raw.values() if isinstance(samples_raw, dict) else samples_raw
                for entry in entries:
                    rel = (entry.get("path") or "").lstrip("/\\")
                    raw_labels = entry.get("labels") or []
                    if isinstance(raw_labels, str):
                        raw_labels = [raw_labels]
                    if raw_labels:
                        label_map[rel] = [_normalize_manifest_label(l) for l in raw_labels]
            except Exception:
                import logging
                logging.getLogger("isg").warning(f"Failed to parse manifest: {traceback.format_exc()}")

        records = []
        yolo_records = [] if label_map else self._collect_yolo_detection_records(folder)
        if yolo_records:
            records = yolo_records
        elif include_subfolders:
            for path in folder.rglob("*"):
                if path.is_file() and path.name != "dataset_manifest.json":
                    rel = path.relative_to(folder).as_posix()
                    records.append({"source_path": path, "relative_path": rel})
        else:
            for path in folder.iterdir():
                if path.is_file() and path.name != "dataset_manifest.json":
                    rel = path.name
                    records.append({"source_path": path, "relative_path": rel})

        imported_count = 0
        failed_count = 0
        errors: list[dict] = []
        with self.session_factory() as session:
            dataset = self._require_dataset(session, dataset_id, include_deleted=False)
            for record in records:
                source = record["source_path"]
                if not source.is_file():
                    failed_count += 1
                    errors.append({"path": str(source), "reason": "missing_file"})
                    continue
                copied = self.file_indexer.copy_into_dataset(source, Path(dataset.storage_path) / "raw", record["relative_path"])
                rel_path = Path(record["relative_path"]).as_posix()
                labels = list(record.get("labels", [])) or label_map.get(rel_path, [])
                # 无manifest标签时，从子文件夹名推断标签
                if not labels and not yolo_records and "/" in rel_path:
                    inferred = rel_path.split("/")[0]
                    labels = [{"type": "classification", "class_name": inferred, "source": "folder_name"}]
                sample = self.dataset_repository.create_sample(
                    session,
                    dataset_id=dataset.id,
                    source_sample_id=None,
                    name=copied.name,
                    modality=dataset.modality,
                    file_path=str(copied),
                    relative_path=rel_path,
                    sha256=None,  # 导入时跳过 SHA256，后续可后台批量计算
                    mime_type=self.file_indexer.detect_mime_type(copied),
                    extension=copied.suffix.lower(),
                    size_bytes=copied.stat().st_size,
                    status="raw",
                    metadata_json={},
                    labels_json=labels,
                )
                imported_count += 1
                self.log_repository.add(
                    session,
                    level="info",
                    action="import_file",
                    resource_type="sample",
                    resource_id=str(sample.id),
                    message=f"Imported file {copied.name} into dataset {dataset.name}",
                    payload_json={"relative_path": record["relative_path"]},
                )
            # 复制 manifest JSON 到数据集目录
            if manifest_path.is_file():
                import shutil
                manifest_dest = Path(dataset.storage_path) / "raw" / "dataset_manifest.json"
                manifest_dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(manifest_path, manifest_dest)

            if label_map:
                extra = dict(dataset.extra_json or {})
                class_dist: dict[str, int] = {}
                for lbs in label_map.values():
                    for lb in lbs:
                        cn = lb["class_name"]
                        class_dist[cn] = class_dist.get(cn, 0) + 1
                extra["class_distribution"] = class_dist
                extra["label_mode"] = "manifest"
                dataset.extra_json = extra
            self._refresh_dataset_stats(session, dataset)
            session.commit()
            return {"ok": True, "data": {"imported_count": imported_count, "failed_count": failed_count, "errors": errors}}

    def import_dataset_bundle(self, payload: dict) -> dict:
        source_path = Path((payload or {}).get("source_path", "")).expanduser()
        if not source_path.exists():
            raise ValidationError("Source path does not exist.")

        if source_path.is_dir() and (source_path / "dataset_manifest.json").is_file():
            return self._import_from_manifest(source_path, payload)

        dataset_name = (payload or {}).get("dataset_name") or source_path.name
        dataset_name = (dataset_name or "").strip() or self._sanitize_name(source_path.name)
        description = (payload or {}).get("description", "") or ""
        modality = (payload or {}).get("modality", "") or ""
        if modality in {"", "auto"}:
            modality = self._infer_modality_from_path(source_path)

        label_path = self._optional_path((payload or {}).get("label_path", ""))
        test_path = self._optional_path((payload or {}).get("test_path", ""))
        test_label_path = self._optional_path((payload or {}).get("test_label_path", ""))
        test_dataset_name = (payload or {}).get("test_dataset_name", "") or f"{dataset_name}_test"
        test_dataset_name = (test_dataset_name or "").strip() or f"{dataset_name}_test"

        train_records, train_format = self._collect_import_records(source_path, label_path, split="train")
        if not train_records:
            raise ValidationError("Source dataset does not contain importable samples.")

        test_records: list[dict] = []
        test_format = ""
        if test_path is not None:
            test_records, test_format = self._collect_import_records(test_path, test_label_path, split="test")

        tags = list(dict.fromkeys([*((payload or {}).get("tags") or []), "imported", "raw"]))
        test_tags = list(dict.fromkeys([*((payload or {}).get("test_tags") or []), "imported", "test"]))

        with self.session_factory() as session:
            datasets = []
            train_dataset = self._store_imported_dataset(
                session,
                name=dataset_name,
                modality=modality,
                description=description,
                status="imported",
                parent_dataset_id=None,
                tags_json=tags,
                extra_json={
                    "dataset_role": "train",
                    "source_path": str(source_path),
                    "label_path": str(label_path) if label_path else "",
                    "import_format": train_format,
                    "sample_count": len(train_records),
                    "label_mode": "file" if label_path else "folder",
                    "multi_layer_folders": source_path.is_dir(),
                    "source_file_count": len(train_records),
                },
                records=train_records,
            )
            datasets.append(train_dataset)

            if test_path is not None:
                test_dataset = self._store_imported_dataset(
                    session,
                    name=test_dataset_name,
                    modality=modality,
                    description=description or f"Test split for {dataset_name}",
                    status="test",
                    parent_dataset_id=train_dataset["id"],
                    tags_json=test_tags,
                    extra_json={
                        "dataset_role": "test",
                        "source_path": str(test_path),
                        "label_path": str(test_label_path) if test_label_path else "",
                        "import_format": test_format,
                        "sample_count": len(test_records),
                        "label_mode": "file" if test_label_path else "folder",
                        "multi_layer_folders": test_path.is_dir(),
                    },
                    records=test_records,
                )
                datasets.append(test_dataset)

            session.commit()
            return {
                "ok": True,
                "data": {
                    "imported_count": len(datasets),
                    "datasets": datasets,
                    "train_dataset": train_dataset,
                    "test_dataset": datasets[1] if len(datasets) > 1 else None,
                    "source_path": str(source_path),
                },
            }

    def import_sonar_oltr_project(
        self,
        project_root: str = "",
        train_path: str = "",
        test_path: str = "",
        label_path: str = "",
        parameter_path: str = "",
        dataset_format: str = "auto",
    ) -> dict:
        root = Path(project_root).expanduser() if (project_root or "").strip() else None
        train = Path(train_path).expanduser() if (train_path or "").strip() else None
        test = Path(test_path).expanduser() if (test_path or "").strip() else None
        label = Path(label_path).expanduser() if (label_path or "").strip() else None
        parameters = self._load_training_parameters(parameter_path)

        specs = []
        if root and root.is_dir():
            specs = self._discover_sonar_oltr_specs(root, test)
        if not specs and train:
            specs = [self._build_manual_import_spec(root, train, test, label)]
        if not specs:
            raise ValidationError("Provide a Sonar-OLTR project root or a training set path.")

        datasets = []
        errors = []
        for spec in specs:
            records = spec["records"]
            if not records:
                errors.append({"dataset": spec["name"], "reason": "no_supported_samples"})
                continue
            datasets.append(self._create_labeled_image_dataset(spec, parameters, dataset_format))

            return {
                "ok": True,
                "data": {
                    "imported_count": len(datasets),
                    "failed_count": len(errors),
                "datasets": datasets,
                    "errors": errors,
                },
            }

    def _import_from_manifest(self, source_path: Path, payload: dict) -> dict:
        manifest_path = source_path / "dataset_manifest.json"
        with open(manifest_path, "r", encoding="utf-8") as f:
            manifest = json.load(f)

        dataset_name = (payload or {}).get("dataset_name") or manifest.get("dataset_name") or source_path.name
        dataset_name = (dataset_name or "").strip() or self._sanitize_name(source_path.name)
        description = (payload or {}).get("description", "") or manifest.get("description", "")
        modality = (payload or {}).get("modality") or manifest.get("modality") or ""
        if modality in {"", "auto"}:
            modality = self._infer_modality_from_path(source_path)

        samples_dict = manifest.get("samples", {})
        if not samples_dict:
            raise ValidationError("Manifest contains no samples.")

        train_records: list[dict] = []
        test_records: list[dict] = []
        for key, entry in samples_dict.items():
            rel_path = (entry.get("path") or "").lstrip("/\\")
            labels = entry.get("labels") or []
            if isinstance(labels, str):
                labels = [labels]
            split = entry.get("split", "train")
            full_path = source_path / rel_path
            if not full_path.is_file():
                continue
            labels_json = [_normalize_manifest_label(l) for l in labels]
            class_name = str(labels[0]) if labels else ""
            record = {
                "source_path": full_path,
                "relative_path": rel_path,
                "class_name": class_name,
                "labels": labels_json,
                "metadata": {"source_path": str(full_path), "label_source": "manifest", "split": split},
                "split": split,
                "sample_modality": self._guess_modality(full_path),
                "import_format": "manifest",
            }
            if split == "test":
                test_records.append(record)
            else:
                train_records.append(record)

        if not train_records and not test_records:
            raise ValidationError("No valid samples found in manifest (all paths missing).")
        if not train_records and test_records:
            train_records = test_records
            test_records = []

        with self.session_factory() as session:
            datasets = []
            train_dataset = self._store_imported_dataset(
                session,
                name=dataset_name,
                modality=modality,
                description=description,
                status="imported",
                parent_dataset_id=None,
                tags_json=["imported", "raw"],
                extra_json={
                    "dataset_role": "train",
                    "source_path": str(source_path),
                    "import_format": "manifest",
                    "sample_count": len(train_records),
                    "label_mode": "manifest",
                },
                records=train_records,
            )
            datasets.append(train_dataset)

            test_dataset = None
            if test_records:
                test_dataset_name = (payload or {}).get("test_dataset_name") or f"{dataset_name}_test"
                test_dataset = self._store_imported_dataset(
                    session,
                    name=test_dataset_name,
                    modality=modality,
                    description=f"Test split for {dataset_name}",
                    status="test",
                    parent_dataset_id=train_dataset["id"],
                    tags_json=["imported", "test"],
                    extra_json={
                        "dataset_role": "test",
                        "source_path": str(source_path),
                        "import_format": "manifest",
                        "sample_count": len(test_records),
                        "label_mode": "manifest",
                    },
                    records=test_records,
                )
                datasets.append(test_dataset)

            session.commit()
            return {
                "ok": True,
                "data": {
                    "imported_count": len(datasets),
                    "datasets": datasets,
                    "train_dataset": train_dataset,
                    "test_dataset": test_dataset,
                    "source_path": str(source_path),
                },
            }

    def _store_imported_dataset(
        self,
        session,
        *,
        name: str,
        modality: str,
        description: str,
        status: str,
        parent_dataset_id: int | None,
        tags_json: list[str],
        extra_json: dict,
        records: list[dict],
    ) -> dict:
        dataset = self.dataset_repository.create_dataset(
            session,
            name=name,
            modality=modality,
            description=description,
            status=status,
            parent_dataset_id=parent_dataset_id,
            storage_path="",
            tags_json=tags_json,
            extra_json=extra_json,
        )
        dataset.storage_path = str(self._allocate_dataset_dir(dataset.id, dataset.name))
        class_distribution: dict[str, int] = {}

        for idx, record in enumerate(records):
            source = record["source_path"]
            copied = self.file_indexer.copy_into_dataset(source, Path(dataset.storage_path) / "raw", record["relative_path"])
            labels = list(record.get("labels", []))
            for label in labels:
                class_name = label.get("class_name") or label.get("label") or ""
                if class_name:
                    class_distribution[class_name] = class_distribution.get(class_name, 0) + 1
            sample = self.dataset_repository.create_sample(
                session,
                dataset_id=dataset.id,
                source_sample_id=None,
                name=copied.name,
                modality=record.get("sample_modality") or modality,
                file_path=str(copied),
                relative_path=record["relative_path"],
                sha256=None,  # 导入时跳过 SHA256，后续可后台批量计算
                mime_type=self.file_indexer.detect_mime_type(copied),
                extension=copied.suffix.lower(),
                size_bytes=copied.stat().st_size,
                status="raw",
                metadata_json={
                    **record.get("metadata", {}),
                    "source_path": str(source),
                    "import_stage": status,
                    "import_format": record.get("import_format", ""),
                },
                labels_json=labels,
            )
            self.log_repository.add(
                session,
                level="info",
                action="import_sample",
                resource_type="sample",
                resource_id=str(sample.id),
                message=f"Imported file {copied.name} into dataset {dataset.name}",
                payload_json={
                    "relative_path": record["relative_path"],
                    "labels": labels,
                },
            )

            # 每 500 条 flush 一次，避免 session 内存膨胀
            if (idx + 1) % 500 == 0:
                session.flush()
                session.expire_all()

        extra_json = dict(extra_json or {})
        extra_json["class_distribution"] = class_distribution
        extra_json["sample_count"] = len(records)
        extra_json["dataset_stage"] = status
        dataset.extra_json = extra_json
        self._refresh_dataset_stats(session, dataset)
        self.log_repository.add(
            session,
            level="info",
            action="import_dataset_bundle",
            resource_type="dataset",
            resource_id=str(dataset.id),
            message=f"Imported dataset bundle {dataset.name}",
            payload_json={"sample_count": len(records), "status": status},
        )
        return self._serialize_dataset(dataset)

    def _collect_import_records(self, data_path: Path, label_path: Path | None, split: str) -> tuple[list[dict], str]:
        if data_path.is_file():
            records = [self._build_file_record(data_path, split=split, label_path=label_path)]
            return records, "single_file"

        if label_path and label_path.is_file():
            records = self._parse_path_label_file(label_path, data_path if data_path.is_dir() else label_path.parent, split)
            return records, "path_label_file"

        if data_path.is_dir():
            list_file = self._find_first_existing(data_path, ["train_abs.txt", "kfold_train.txt", "labels.txt", "annotations.txt"])
            if list_file:
                records = self._parse_path_label_file(list_file, data_path, split)
                return records, "path_label_file"
            yolo_records = self._collect_yolo_detection_records(data_path, default_split=split)
            if yolo_records:
                return yolo_records, "yolo_detection"
            records = self._infer_folder_tree_records(data_path, split=split)
            return records, "folder_tree"

        raise ValidationError("Import path does not exist.")

    def _collect_yolo_detection_records(self, folder: Path, default_split: str = "train") -> list[dict]:
        name_map = self._load_yolo_class_names(folder)
        pairs: list[tuple[Path, Path, str]] = []

        direct_images = folder / "images"
        direct_labels = folder / "labels"
        if direct_images.is_dir() and direct_labels.is_dir():
            pairs.append((direct_images, direct_labels, default_split))

        split_aliases = {
            "train": "train",
            "valid": "test",
            "val": "test",
            "test": "test",
        }
        for dirname, split in split_aliases.items():
            images_dir = folder / dirname / "images"
            labels_dir = folder / dirname / "labels"
            if images_dir.is_dir() and labels_dir.is_dir():
                pairs.append((images_dir, labels_dir, split))

        records: list[dict] = []
        seen_relative_paths: set[str] = set()
        found_label_file = False
        for images_dir, labels_dir, split in pairs:
            for source in sorted(path for path in images_dir.rglob("*") if path.is_file() and path.suffix.lower() in self._IMAGE_EXTENSIONS):
                rel_to_images = source.relative_to(images_dir)
                label_file = labels_dir / rel_to_images.with_suffix(".txt")
                labels = self._parse_yolo_label_file(label_file, split=split, name_map=name_map)
                if label_file.is_file():
                    found_label_file = True
                relative_path = source.relative_to(folder).as_posix()
                if relative_path in seen_relative_paths:
                    continue
                seen_relative_paths.add(relative_path)
                records.append(
                    {
                        "source_path": source,
                        "relative_path": relative_path,
                        "labels": labels,
                        "metadata": {
                            "source_path": str(source),
                            "label_source": str(label_file) if label_file.is_file() else "",
                        },
                        "split": split,
                        "sample_modality": "image",
                        "import_format": "yolo_detection",
                    }
                )
        return records if found_label_file else []

    def _parse_yolo_label_file(self, label_file: Path, *, split: str, name_map: dict[int, str]) -> list[dict]:
        if not label_file.is_file():
            return []
        labels: list[dict] = []
        for line_number, line in enumerate(label_file.read_text(encoding="utf-8").splitlines(), start=1):
            parts = line.strip().split()
            if len(parts) < 5:
                continue
            try:
                class_id = int(parts[0])
                bbox = [float(parts[1]), float(parts[2]), float(parts[3]), float(parts[4])]
            except (TypeError, ValueError):
                continue
            class_name = name_map.get(class_id, f"class_{class_id}")
            labels.append(
                {
                    "type": "detection",
                    "class_id": class_id,
                    "class_name": class_name,
                    "bbox": bbox,
                    "source": str(label_file),
                    "split": split,
                    "line_number": line_number,
                }
            )
        return labels

    def _load_yolo_class_names(self, folder: Path) -> dict[int, str]:
        data_yaml = self._find_first_existing(folder, ["data.yaml", "data.yml"])
        if not data_yaml:
            return {}
        try:
            import yaml
        except Exception:
            return {}
        try:
            payload = yaml.safe_load(data_yaml.read_text(encoding="utf-8")) or {}
        except Exception:
            return {}
        names = payload.get("names")
        if isinstance(names, dict):
            result = {}
            for key, value in names.items():
                try:
                    result[int(key)] = str(value)
                except (TypeError, ValueError):
                    continue
            return result
        if isinstance(names, list):
            return {idx: str(value) for idx, value in enumerate(names)}
        return {}

    def _build_file_record(self, path: Path, *, split: str, label_path: Path | None) -> dict:
        labels: list[dict] = []
        label_source = str(label_path) if label_path else "file"
        labels.append(
            {
                "type": "classification",
                "class_name": path.parent.name or path.stem,
                "class_path": path.parent.name or path.stem,
                "source": label_source,
                "split": split,
            }
        )
        return {
            "source_path": path,
            "relative_path": path.name,
            "labels": labels,
            "metadata": {"source_path": str(path)},
            "split": split,
            "sample_modality": self._guess_modality(path),
            "import_format": "single_file",
        }

    def _infer_folder_tree_records(self, folder: Path, split: str = "train") -> list[dict]:
        records = []
        ignored_names = {"train_abs.txt", "kfold_train.txt", "kfold_val.txt", "labels.txt", "annotations.txt", "annotations.json", "params.json"}
        for path in sorted(p for p in folder.rglob("*") if p.is_file()):
            if path.name in ignored_names:
                continue
            relative_path = path.relative_to(folder).as_posix()
            relative_parent = path.parent.relative_to(folder).as_posix()
            class_path = "" if relative_parent == "." else relative_parent
            class_name = path.parent.name if path.parent != folder else folder.name
            labels: list[dict] = []
            records.append(
                {
                    "source_path": path,
                    "relative_path": relative_path,
                    "class_name": class_name,
                    "labels": labels,
                    "metadata": {
                        "source_path": str(path),
                        "label_source": "folder_structure",
                        "class_path": class_path,
                        "class_name": class_name,
                    },
                    "split": split,
                    "sample_modality": self._guess_modality(path),
                    "import_format": "folder_tree",
                }
            )
        if split == "train":
            return self._apply_stable_split(records)
        return records

    def _guess_modality(self, path: Path) -> str:
        mime_type = self.file_indexer.detect_mime_type(path)
        extension = path.suffix.lower()
        if mime_type.startswith("image/") or extension in self._IMAGE_EXTENSIONS:
            return "image"
        if mime_type.startswith("audio/") or extension in {".wav", ".mp3", ".aac", ".flac", ".ogg", ".m4a"}:
            return "audio"
        if mime_type.startswith("text/") or extension in {".txt", ".csv", ".json", ".md", ".log", ".yaml", ".yml"}:
            return "text"
        return "other"

    def _infer_modality_from_path(self, path: Path) -> str:
        if path.is_file():
            return self._guess_modality(path)
        files = [item for item in path.rglob("*") if item.is_file()]
        if not files:
            return "other"
        counts: dict[str, int] = {}
        for file_path in files[:200]:
            modality = self._guess_modality(file_path)
            counts[modality] = counts.get(modality, 0) + 1
        return max(counts, key=counts.get) if counts else "other"

    def _optional_path(self, value: str) -> Path | None:
        if not (value or "").strip():
            return None
        path = Path(value).expanduser()
        return path if path.exists() else None

    def get_dataset_samples(self, dataset_id: int, page: int, page_size: int, status: str) -> dict:
        with self.session_factory() as session:
            self._require_dataset(session, dataset_id, include_deleted=True)
            total, items = self.dataset_repository.list_samples(
                session,
                dataset_id=dataset_id,
                page=max(page, 1),
                page_size=max(page_size, 1),
                status=status or "",
            )
            return {
                "total": total,
                "items": [self._serialize_sample(item) for item in items],
                "page": max(page, 1),
                "page_size": max(page_size, 1),
            }

    def list_samples(self, dataset_id: int, page: int, page_size: int, status: str) -> dict:
        return self.get_dataset_samples(dataset_id=dataset_id, page=page, page_size=page_size, status=status)

    def get_dataset_directory(self, dataset_id: int, path: str) -> dict:
        """返回指定路径下的子目录和文件列表"""
        with self.session_factory() as session:
            dataset = self._require_dataset(session, dataset_id, include_deleted=True)
            samples = self.dataset_repository.get_all_samples(session, dataset_id)
            dirs: set[str] = set()
            files: list[dict] = []
            prefix = path.strip("/") + "/" if path.strip("/") else ""
            for s in samples:
                rp = s.relative_path or ""
                if prefix and not rp.startswith(prefix):
                    continue
                if prefix:
                    rp = rp[len(prefix):]
                if "/" in rp:
                    dirs.add(rp.split("/")[0])
                elif rp:
                    files.append(self._serialize_sample(s))
            # 根目录下显示 manifest JSON
            if not path.strip("/"):
                manifest_file = Path(dataset.storage_path) / "raw" / "dataset_manifest.json"
                if manifest_file.is_file():
                    files.append({
                        "id": -1,
                        "name": "dataset_manifest.json",
                        "file_path": str(manifest_file),
                        "relative_path": "dataset_manifest.json",
                        "status": "manifest",
                        "size_bytes": manifest_file.stat().st_size,
                        "type": "json",
                        "labels": [],
                    })
            return {"ok": True, "data": {
                "path": path.strip("/"),
                "dirs": sorted(dirs),
                "files": files,
            }}

    def get_dataset_preview_samples(self, dataset_id: int, limit: int, status: str) -> dict:
        with self.session_factory() as session:
            self._require_dataset(session, dataset_id, include_deleted=True)
            total, items = self.dataset_repository.preview_samples(
                session,
                dataset_id=dataset_id,
                limit=max(limit, 0),
                status=status or "",
            )
            return {"total": total, "items": [self._serialize_sample(item) for item in items]}

    def preview_samples(self, dataset_id: int, limit: int, status: str) -> dict:
        return self.get_dataset_preview_samples(dataset_id=dataset_id, limit=limit, status=status)

    def preview_file_by_path(self, file_path: str) -> dict:
        """直接按文件路径预览文件内容，不依赖数据库样本记录。"""
        path = Path(file_path)
        if not path.is_file():
            return {"ok": True, "data": {
                "name": path.name,
                "file_path": str(path),
                "preview_kind": "text",
                "text_content": "",
                "error": f"文件不存在: {path}",
            }}
        ext = path.suffix.lower()
        if ext in {".jpg", ".jpeg", ".png", ".bmp", ".gif", ".webp", ".tif", ".tiff"}:
            preview_kind = "image"
        elif ext in {".wav", ".mp3", ".aac", ".flac", ".ogg", ".m4a"}:
            preview_kind = "audio"
        else:
            preview_kind = "text"

        payload = {
            "name": path.name,
            "file_path": str(path),
            "preview_kind": preview_kind,
            "text_content": "",
            "error": "",
        }
        if preview_kind in ("text",):
            try:
                payload["text_content"] = path.read_bytes()[:200 * 1024].decode("utf-8")
            except UnicodeDecodeError:
                payload["error"] = "无法以文本方式预览此文件（非 UTF-8 编码或二进制文件）。"
            except OSError as exc:
                payload["error"] = str(exc)
        return {"ok": True, "data": payload}

    def get_sample_preview(self, sample_id: int) -> dict:
        with self.session_factory() as session:
            sample = session.query(Sample).filter(Sample.id == sample_id).first()
            if sample is None:
                raise NotFoundError(f"Sample {sample_id} not found.")
            payload = self._serialize_sample(sample)
            preview_kind = self._preview_kind(sample)
            payload.update(
                {
                    "sample_id": sample.id,
                    "preview_kind": preview_kind,
                    "text_content": "",
                    "error": "",
                }
            )
            path = Path(sample.file_path)
            if not path.is_file():
                payload["error"] = f"Sample file does not exist: {path}"
                return {"ok": True, "data": payload}

            if preview_kind in ("text", "file"):
                try:
                    payload["text_content"] = path.read_bytes()[: 200 * 1024].decode("utf-8")
                    if preview_kind == "file":
                        payload["preview_kind"] = "text"
                except UnicodeDecodeError:
                    payload["error"] = "无法以文本方式预览此文件（非 UTF-8 编码或二进制文件）。"
                except OSError as exc:
                    payload["error"] = str(exc)
            return {"ok": True, "data": payload}

    def get_dataset_stats(self, dataset_id: int) -> dict:
        with self.session_factory() as session:
            dataset = self._require_dataset(session, dataset_id, include_deleted=True)
            total = self.dataset_repository.dataset_sample_count(session, dataset_id)
            modalities = self.dataset_repository.dataset_modality_breakdown(session, dataset_id)
            return {
                "ok": True,
                "data": {
                    "dataset_id": dataset.id,
                    "total_samples": total,
                    "size_bytes": dataset.size_bytes,
                    "modalities": modalities,
                },
            }

    def get_statistics(self, dataset_id: int) -> dict:
        return self.get_dataset_stats(dataset_id)

    def get_recent_activities(self, limit: int = 5) -> list[dict]:
        with self.session_factory() as session:
            items = self.log_repository.recent(session, limit=max(limit, 1))
            return [
                {
                    "id": item.id,
                    "level": item.level,
                    "action": item.action,
                    "resource_type": item.resource_type,
                    "resource_id": item.resource_id,
                    "message": item.message,
                }
                for item in items
            ]

    def get_system_stats(self) -> dict:
        with self.session_factory() as session:
            total_datasets = self.dataset_repository.count_active_datasets(session)
            total_samples = self.dataset_repository.count_active_samples(session)
            return {"ok": True, "data": {"total_datasets": total_datasets, "total_samples": total_samples}}

    def get_data_type_distribution(self) -> dict:
        with self.session_factory() as session:
            return {"ok": True, "data": self.dataset_repository.count_by_modality(session)}

    def _require_dataset(self, session, dataset_id: int, *, include_deleted: bool):
        dataset = self.dataset_repository.get_dataset(session, dataset_id, include_deleted=include_deleted)
        if not dataset:
            raise NotFoundError(f"Dataset {dataset_id} not found.")
        return dataset

    def _rename_dataset_storage(self, session, dataset, new_name: str) -> None:
        current_path = Path(dataset.storage_path) if dataset.storage_path else None
        if current_path is None:
            return

        target_path = self.paths.datasets_dir / f"{dataset.id}_{self._sanitize_name(new_name)}"
        if current_path == target_path:
            return

        if current_path.exists():
            if target_path.exists():
                raise ValidationError(f"Dataset directory already exists: {target_path}")
            current_path.rename(target_path)
        else:
            for subdir in [target_path, target_path / "raw", target_path / "cleaned", target_path / "generated", target_path / "preview"]:
                subdir.mkdir(parents=True, exist_ok=True)

        old_prefix = str(current_path).replace("\\", "/").rstrip("/")
        new_prefix = str(target_path).replace("\\", "/").rstrip("/")
        samples = self.dataset_repository.get_all_samples(session, dataset.id)
        for sample in samples:
            file_path = str(sample.file_path or "")
            normalized = file_path.replace("\\", "/")
            if not normalized.startswith(old_prefix):
                continue
            sample.file_path = new_prefix + normalized[len(old_prefix):]

        dataset.storage_path = str(target_path)

    def _allocate_dataset_dir(self, dataset_id: int, name: str) -> Path:
        root = self.paths.datasets_dir / f"{dataset_id}_{self._sanitize_name(name)}"
        for subdir in [root, root / "raw", root / "cleaned", root / "generated", root / "preview"]:
            subdir.mkdir(parents=True, exist_ok=True)
        return root

    def _sanitize_name(self, name: str) -> str:
        invalid = '<>:"/\\|?*'
        sanitized = "".join("_" if char in invalid else char for char in name).strip().strip(".")
        return sanitized or "dataset"

    def _refresh_dataset_stats(self, session, dataset) -> None:
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

    def _discover_sonar_oltr_specs(self, root: Path, explicit_test_path: Path | None) -> list[dict]:
        data_root = root / "data"
        if not data_root.is_dir():
            return []
        specs = []
        for dataset_dir in sorted(path for path in data_root.iterdir() if path.is_dir()):
            train_file = dataset_dir / "train_abs.txt"
            if not train_file.is_file():
                continue
            test_file = explicit_test_path if explicit_test_path and explicit_test_path.exists() else dataset_dir / "kfold_val.txt"
            records = self._parse_path_label_file(train_file, root, "train")
            split_files = {"train": str(train_file), "test": ""}
            split_method = "sonar_oltr_train_abs"
            if test_file and test_file.is_file():
                records.extend(self._parse_path_label_file(test_file, root, "test"))
                split_files["test"] = str(test_file)
                split_method = "sonar_oltr_kfold"
            else:
                records = self._apply_stable_split(records)
                split_method = "stable_8_2"
            specs.append(
                {
                    "name": dataset_dir.name,
                    "description": f"Imported Sonar-OLTR dataset {dataset_dir.name}",
                    "dataset_format": "sonar_oltr",
                    "source_root": str(root),
                    "records": records,
                    "split_files": split_files,
                    "split_method": split_method,
                }
            )
        return specs

    def _build_manual_import_spec(
        self,
        root: Path | None,
        train_path: Path,
        test_path: Path | None,
        label_path: Path | None,
    ) -> dict:
        source_root = root or train_path
        if label_path and label_path.is_file():
            records = self._parse_path_label_file(label_path, source_root, "train")
            split_files = {"train": str(label_path), "test": ""}
            dataset_format = "path_label_file"
        elif train_path.is_file():
            records = self._parse_path_label_file(train_path, source_root, "train")
            split_files = {"train": str(train_path), "test": ""}
            dataset_format = "path_label_file"
        elif train_path.is_dir():
            list_file = self._find_first_existing(train_path, ["train_abs.txt", "kfold_train.txt"])
            if list_file:
                records = self._parse_path_label_file(list_file, source_root, "train")
                split_files = {"train": str(list_file), "test": ""}
                dataset_format = "sonar_oltr" if (train_path / "train_abs.txt").exists() else "path_label_file"
            else:
                records = self._infer_folder_classification_records(train_path)
                split_files = {"train": str(train_path), "test": ""}
                dataset_format = "folder_classification"
        else:
            raise ValidationError("Training set path does not exist.")

        if test_path and test_path.exists():
            if test_path.is_file():
                records.extend(self._parse_path_label_file(test_path, source_root, "test"))
            elif test_path.is_dir():
                records.extend(self._infer_folder_classification_records(test_path, split="test"))
            split_files["test"] = str(test_path)
            split_method = "explicit_test_path"
        else:
            existing_test = self._find_first_existing(train_path if train_path.is_dir() else train_path.parent, ["kfold_val.txt"])
            if existing_test:
                records.extend(self._parse_path_label_file(existing_test, source_root, "test"))
                split_files["test"] = str(existing_test)
                split_method = "sonar_oltr_kfold"
            else:
                records = self._apply_stable_split(records)
                split_method = "stable_8_2"

        return {
            "name": train_path.stem if train_path.is_file() else train_path.name,
            "description": "Imported labeled underwater image dataset",
            "dataset_format": dataset_format,
            "source_root": str(source_root),
            "records": records,
            "split_files": split_files,
            "split_method": split_method,
        }

    def _parse_path_label_file(self, label_file: Path, project_root: Path | None, split: str) -> list[dict]:
        records = []
        for line_number, line in enumerate(label_file.read_text(encoding="utf-8").splitlines(), start=1):
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            parts = stripped.split()
            if len(parts) < 2:
                continue
            raw_path = Path(parts[0])
            resolved = self._resolve_labeled_sample_path(raw_path, label_file, project_root)
            if not resolved or not resolved.is_file() or resolved.suffix.lower() not in self._IMAGE_EXTENSIONS:
                continue
            try:
                class_id = int(parts[1])
            except (TypeError, ValueError):
                continue
            class_name = resolved.parent.name
            records.append(
                {
                    "source_path": resolved,
                    "relative_path": f"{class_name}/{resolved.name}",
                    "class_id": class_id,
                    "class_name": class_name,
                    "split": split,
                    "label_source": str(label_file),
                    "line_number": line_number,
                    "labels": [
                        {
                            "type": "classification",
                            "class_id": class_id,
                            "class_name": class_name,
                            "class_path": class_name,
                            "source": str(label_file),
                            "split": split,
                            "line_number": line_number,
                        }
                    ],
                    "metadata": {
                        "label_source": str(label_file),
                        "line_number": line_number,
                        "class_name": class_name,
                    },
                    "sample_modality": "image",
                    "import_format": "path_label_file",
                }
            )
        return records

    def _infer_folder_classification_records(self, folder: Path, split: str = "train") -> list[dict]:
        records = []
        class_dirs = sorted(path for path in folder.iterdir() if path.is_dir())
        for class_id, class_dir in enumerate(class_dirs):
            for source in sorted(path for path in class_dir.rglob("*") if path.is_file() and path.suffix.lower() in self._IMAGE_EXTENSIONS):
                records.append(
                    {
                        "source_path": source,
                        "relative_path": source.relative_to(folder).as_posix(),
                        "class_id": class_id,
                        "class_name": class_dir.name,
                        "split": split,
                        "label_source": "folder_name",
                        "line_number": 0,
                    }
                )
        return records

    def _apply_stable_split(self, records: list[dict]) -> list[dict]:
        if len(records) <= 1:
            return records
        ordered = sorted(records, key=lambda item: (item["class_name"], str(item["source_path"])))
        test_count = max(1, round(len(ordered) * 0.2))
        train_count = max(1, len(ordered) - test_count)
        for index, record in enumerate(ordered):
            record["split"] = "train" if index < train_count else "test"
        return ordered

    def _resolve_labeled_sample_path(self, raw_path: Path, label_file: Path, project_root: Path | None) -> Path | None:
        if raw_path.is_absolute():
            return raw_path
        candidates = [
            label_file.parent / raw_path,
        ]
        if project_root:
            candidates.extend(
                [
                    project_root / raw_path,
                    project_root / "code" / raw_path,
                    project_root / "data" / raw_path,
                ]
            )
        for candidate in candidates:
            resolved = candidate.resolve()
            if resolved.is_file():
                return resolved
        return None

    def _find_first_existing(self, folder: Path, names: list[str]) -> Path | None:
        for name in names:
            candidate = folder / name
            if candidate.is_file():
                return candidate
        return None

    def _create_labeled_image_dataset(self, spec: dict, parameters: dict, requested_format: str) -> dict:
        with self.session_factory() as session:
            records = self._deduplicate_records(spec["records"])
            class_distribution: dict[str, int] = {}
            for record in records:
                class_distribution[record["class_name"]] = class_distribution.get(record["class_name"], 0) + 1
            class_map = {
                str(record["class_id"]): record["class_name"]
                for record in sorted(records, key=lambda item: (item["class_id"], item["class_name"]))
            }
            dataset = self.dataset_repository.create_dataset(
                session,
                name=spec["name"],
                modality="image",
                description=spec.get("description", ""),
                status="imported",
                parent_dataset_id=None,
                storage_path="",
                tags_json=["underwater", "sonar_oltr", "labeled"],
                extra_json={
                    "dataset_format": spec["dataset_format"] if requested_format in {"", "auto"} else requested_format,
                    "source_root": spec.get("source_root", ""),
                    "split_files": spec.get("split_files", {}),
                    "split_method": spec.get("split_method", ""),
                    "class_map": class_map,
                    "class_distribution": class_distribution,
                    "sample_count": len(records),
                    "training_parameters": parameters,
                    "recommended_training": {
                        "script": "code/plud.py",
                        "analysis_script": "code/analyse_result.py",
                        "optional_execution": True,
                    },
                },
            )
            dataset.storage_path = str(self._allocate_dataset_dir(dataset.id, dataset.name))
            for record in records:
                source = record["source_path"]
                copied = self.file_indexer.copy_into_dataset(source, Path(dataset.storage_path) / "raw", record["relative_path"])
                label = {
                    "type": "classification",
                    "class_id": record["class_id"],
                    "class_name": record["class_name"],
                    "source": record["label_source"],
                    "split": record["split"],
                }
                sample = self.dataset_repository.create_sample(
                    session,
                    dataset_id=dataset.id,
                    source_sample_id=None,
                    name=copied.name,
                    modality="image",
                    file_path=str(copied),
                    relative_path=copied.relative_to(Path(dataset.storage_path) / "raw").as_posix(),
                    sha256=None,  # 导入时跳过 SHA256，后续可后台批量计算
                    mime_type=self.file_indexer.detect_mime_type(copied),
                    extension=copied.suffix.lower(),
                    size_bytes=copied.stat().st_size,
                    status="raw",
                    metadata_json={
                        "source_path": str(source),
                        "dataset_format": spec["dataset_format"],
                        "split": record["split"],
                        "label_source": record["label_source"],
                    },
                    labels_json=[label],
                )
                self.log_repository.add(
                    session,
                    level="info",
                    action="import_labeled_sample",
                    resource_type="sample",
                    resource_id=str(sample.id),
                    message=f"Imported labeled sample {copied.name} into dataset {dataset.name}",
                    payload_json={"class_name": record["class_name"], "split": record["split"]},
                )
            self._refresh_dataset_stats(session, dataset)
            self.log_repository.add(
                session,
                level="info",
                action="import_sonar_oltr_project",
                resource_type="dataset",
                resource_id=str(dataset.id),
                message=f"Imported labeled dataset {dataset.name}",
                payload_json={"sample_count": len(records), "dataset_format": spec["dataset_format"]},
            )
            session.commit()
            return self._serialize_dataset(dataset)

    def _deduplicate_records(self, records: list[dict]) -> list[dict]:
        deduped: dict[Path, dict] = {}
        for record in records:
            key = record["source_path"].resolve()
            if key not in deduped or record.get("split") == "test":
                deduped[key] = record
        return list(deduped.values())

    def _load_training_parameters(self, parameter_path: str) -> dict:
        if not (parameter_path or "").strip():
            return {}
        path = Path(parameter_path).expanduser()
        if not path.is_file():
            raise ValidationError("Training parameter file does not exist.")
        if path.suffix.lower() != ".json":
            return {"parameter_file": str(path), "note": "Only JSON parameters are parsed automatically."}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValidationError(f"Training parameter file is not valid JSON: {exc.msg}") from exc
        if not isinstance(data, dict):
            raise ValidationError("Training parameter file must contain a JSON object.")
        return {key: data[key] for key in self._TRAINING_PARAMETER_ALLOWLIST if key in data}

    def _serialize_dataset(self, dataset) -> dict:
        status = (dataset.status or "").lower()
        tags = list(dataset.tags_json or [])
        return {
            "id": dataset.id,
            "name": dataset.name,
            "modality": dataset.modality,
            "description": dataset.description,
            "status": dataset.status,
            "stage": "generated" if status == "generated" or "generated" in {str(tag).lower() for tag in tags} else ("cleaned" if status == "cleaned" or "cleaned" in {str(tag).lower() for tag in tags} else "raw"),
            "parent_dataset_id": dataset.parent_dataset_id,
            "storage_path": dataset.storage_path,
            "total_samples": dataset.total_samples,
            "size_bytes": dataset.size_bytes,
            "tags": tags,
            "extra": dataset.extra_json or {},
        }

    def _serialize_sample(self, sample) -> dict:
        return {
            "id": sample.id,
            "dataset_id": sample.dataset_id,
            "name": sample.name,
            "modality": sample.modality,
            "file_path": sample.file_path,
            "relative_path": sample.relative_path,
            "source_sample_id": sample.source_sample_id,
            "size_bytes": sample.size_bytes,
            "status": sample.status,
            "mime_type": sample.mime_type,
            "extension": sample.extension,
            "metadata": sample.metadata_json or {},
            "labels": sample.labels_json or [],
            "updated_at": to_local_isoformat(sample.updated_at),
        }

    def _preview_kind(self, sample) -> str:
        mime_type = (sample.mime_type or "").lower()
        extension = (sample.extension or "").lower()
        # 扩展名优先，mime_type 次之，模态兜底
        if extension in {".jpg", ".jpeg", ".png", ".bmp", ".gif", ".webp", ".tif", ".tiff"} or mime_type.startswith("image/"):
            return "image"
        if extension in {".wav", ".mp3", ".aac", ".flac", ".ogg", ".m4a"} or mime_type.startswith("audio/"):
            return "audio"
        if extension in {".txt", ".csv", ".json", ".md", ".log", ".yaml", ".yml", ".xml", ".py", ".js", ".html", ".css", ".cfg", ".ini", ".toml"} or mime_type.startswith("text/"):
            return "text"
        # 不依赖 modality 兜底：未知扩展名返回 "file"
        # 防止 .npy/.cache 等非媒体文件被误判为图片导致 QML 解码错误
        return "file"
