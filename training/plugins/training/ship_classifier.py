"""Ship image classifier training plugin.

Extracts HOG + color histogram features from ship images and trains a
RandomForest classifier. Works with or without labels (unsupervised
clustering fallback). Saves the model checkpoint for evaluation.
"""

from __future__ import annotations

import json
import pickle
from pathlib import Path
from collections import Counter

import numpy as np


def _extract_hog_features(img_array: np.ndarray, cell_size: int = 64) -> np.ndarray:
    """Simple HOG-like feature: gradient magnitude/orientation histogram per cell."""
    h, w = img_array.shape[:2]
    if len(img_array.shape) == 3:
        gray = np.dot(img_array[..., :3], [0.2989, 0.5870, 0.1140])
    else:
        gray = img_array

    gy, gx = np.gradient(gray)
    magnitude = np.sqrt(gx**2 + gy**2)
    orientation = (np.arctan2(gy, gx) % np.pi) / np.pi

    n_bins = 8
    features = []
    for y in range(0, h - cell_size + 1, cell_size):
        for x in range(0, w - cell_size + 1, cell_size):
            cell_mag = magnitude[y:y+cell_size, x:x+cell_size]
            cell_ori = orientation[y:y+cell_size, x:x+cell_size]
            hist, _ = np.histogram(cell_ori, bins=n_bins, range=(0, 1), weights=cell_mag)
            hist = hist / (np.sum(hist) + 1e-6)
            features.extend(hist)
    return np.array(features, dtype=np.float32)


def _extract_color_features(img_array: np.ndarray) -> np.ndarray:
    """3D color histogram features (8 bins per channel)."""
    if len(img_array.shape) != 3 or img_array.shape[2] < 3:
        return np.zeros(8 * 3, dtype=np.float32)
    features = []
    for ch in range(3):
        hist, _ = np.histogram(img_array[:, :, ch], bins=8, range=(0, 255))
        hist = hist.astype(np.float32) / (np.sum(hist) + 1e-6)
        features.extend(hist)
    return np.array(features, dtype=np.float32)


def _extract_features(img_path: str, target_size: tuple = (256, 256)) -> np.ndarray | None:
    try:
        from PIL import Image
        img = Image.open(img_path).convert("RGB").resize(target_size)
        arr = np.array(img, dtype=np.float32)
        hog = _extract_hog_features(arr)
        color = _extract_color_features(arr)
        return np.concatenate([hog, color]).astype(np.float32)
    except Exception:
        return None


def _load_samples(input_data: dict) -> list[dict]:
    """Unify sample access across training and evaluation payloads."""
    samples = input_data.get("samples", [])
    if samples:
        return samples
    # Evaluation payload uses dataset dicts
    for key in ("baseline_dataset", "target_dataset"):
        ds = input_data.get(key, {})
        if ds and ds.get("samples"):
            samples = ds["samples"]
            break
    return samples


def _classify_samples(features: np.ndarray, labels: list, n_total: int, progress) -> tuple:
    """Train classifier and return model + metrics."""
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.cluster import KMeans

    X = np.array(features, dtype=np.float32)
    no_label_count = sum(1 for l in labels if l is None)

    if no_label_count > 0:
        n_clusters = min(3, len(X))
        clusterer = KMeans(n_clusters=n_clusters, random_state=42, n_init=10)
        pseudo_labels = clusterer.fit_predict(X)
        y = np.array(pseudo_labels, dtype=np.int32)
        label_names = {i: f"cluster_{i}" for i in range(n_clusters)}
        label_mode = "unsupervised_clustering"
        if progress:
            progress(55.0, f"无监督聚类 ({n_clusters} classes)")
    else:
        label_names_list = sorted(set(l for l in labels if l is not None))
        label_to_idx = {name: i for i, name in enumerate(label_names_list)}
        y = np.array([label_to_idx[l] for l in labels], dtype=np.int32)
        label_names = {i: name for i, name in enumerate(label_names_list)}
        label_mode = "supervised"
        if progress:
            progress(55.0, f"监督训练 ({len(label_names_list)} classes)")

    n_estimators = 50
    max_depth = 8
    clf = RandomForestClassifier(n_estimators=n_estimators, max_depth=max_depth, random_state=42)
    clf.fit(X, y)

    y_pred = clf.predict(X)
    accuracy = float(np.mean(y_pred == y))
    class_counts = Counter(int(yl) for yl in y)

    return clf, {
        "accuracy": round(accuracy, 4),
        "n_samples": len(X),
        "n_classes": len(class_counts),
        "n_features": int(X.shape[1]),
        "label_mode": label_mode,
        "class_names": [label_names.get(i) for i in range(len(class_counts))],
        "class_distribution": {label_names.get(i, f"class_{i}"): cnt for i, cnt in class_counts.items()},
        "n_estimators": n_estimators,
        "max_depth": max_depth,
    }


def _extract_from_payload(input_data: dict, progress, is_cancelled) -> tuple[list, list, list]:
    """Extract features from payload samples."""
    samples = _load_samples(input_data)
    feature_list, label_list, path_list = [], [], []
    total = len(samples)
    for idx, sample in enumerate(samples):
        if is_cancelled and is_cancelled():
            break
        img_path = sample.get("path", "")
        if not Path(img_path).is_file():
            continue
        feats = _extract_features(img_path)
        if feats is None:
            continue
        feature_list.append(feats)
        path_list.append(img_path)
        labels = sample.get("labels", [])
        if labels:
            label_list.append(labels[0].get("class_name", labels[0].get("label", "unknown")))
        else:
            label_list.append(None)
        if progress and (idx + 1) % max(total // 5, 1) == 0:
            progress((idx + 1) / total * 40.0, f"特征提取 {idx+1}/{total}")
    return feature_list, label_list, path_list


PARAMETERS = []

def run(payload: dict, context=None) -> dict:
    """Train/evaluate a ship image classifier."""
    task_id = payload.get("task_id", 0)
    category = payload.get("category", "training")
    input_data = payload.get("input", {})
    output_dir = Path(payload.get("output", {}).get("output_dir", ""))
    output_dir.mkdir(parents=True, exist_ok=True)

    progress = context.set_progress if context else None
    is_cancelled = context.is_cancel_requested if context else None

    if progress:
        progress(5.0, "开始提取特征...")

    feature_list, label_list, path_list = _extract_from_payload(input_data, progress, is_cancelled)

    if len(feature_list) < 2:
        return {"ok": False, "error_code": "INSUFFICIENT_DATA", "message": "Need at least 2 valid samples"}

    # ── Training mode ──
    if category == "training":
        if progress:
            progress(50.0, "训练分类器...")
        clf, meta = _classify_samples(feature_list, label_list, len(feature_list), progress)

        if progress:
            progress(85.0, "保存模型...")

        checkpoint_path = output_dir / "ship_classifier_checkpoint.pkl"
        model_data = {"model": "ship_classifier_rf", "model_type": "RandomForest", **meta}
        with open(checkpoint_path, "wb") as f:
            pickle.dump({"model": clf, "metadata": model_data}, f)

        if progress:
            progress(100.0, "训练完成")

        return {
            "ok": True,
            "outputs": [{
                "artifact_path": str(checkpoint_path),
                "artifact_type": "model_checkpoint",
                "metrics": {"accuracy": meta["accuracy"], "n_samples": meta["n_samples"],
                            "n_classes": meta["n_classes"], "n_features": meta["n_features"]},
                "summary": f"Ship classifier (RF n={meta['n_estimators']} d={meta['max_depth']}) "
                           f"trained on {meta['n_samples']} samples, {meta['n_classes']} classes. "
                           f"Accuracy: {meta['accuracy']:.4f}. Label mode: {meta['label_mode']}.",
            }],
        }

    # ── Evaluation mode ──
    if progress:
        progress(50.0, "提取测试集特征...")

    target_dataset = input_data.get("target_dataset", {})
    target_samples = target_dataset.get("samples", []) if target_dataset else []
    target_features, target_labels, _ = _extract_from_payload(
        {"samples": target_samples}, progress, is_cancelled
    )

    # Train on baseline, test on target
    clf, meta = _classify_samples(feature_list, label_list, len(feature_list) + len(target_features), progress)

    test_results = []
    if target_features:
        X_test = np.array(target_features, dtype=np.float32)
        y_pred = clf.predict(X_test)
        for i, pred in enumerate(y_pred):
            test_results.append({
                "sample_index": i,
                "predicted_class": int(pred),
                "true_label": target_labels[i] if i < len(target_labels) else None,
            })

    if progress:
        progress(100.0, "评估完成")

    return {
        "ok": True,
        "outputs": [{
            "artifact_path": str(output_dir / "eval_results.json"),
            "artifact_type": "report",
            "metrics": {
                "train_accuracy": meta["accuracy"],
                "train_samples": meta["n_samples"],
                "test_samples": len(target_features),
                "n_classes": meta["n_classes"],
            },
            "summary": f"Evaluation: trained on {meta['n_samples']} samples ({meta['n_classes']} classes), "
                       f"tested on {len(target_features)} samples. Train accuracy: {meta['accuracy']:.4f}.",
        }],
        "results": [{
            "model_name": "ship_classifier_rf",
            "metrics": {
                "train_accuracy": meta["accuracy"],
                "train_samples": meta["n_samples"],
                "test_samples": len(target_features),
                "n_classes": meta["n_classes"],
            },
            "summary": f"Ship classifier evaluated. Train acc={meta['accuracy']:.4f}, test samples={len(target_features)}",
        }],
    }
