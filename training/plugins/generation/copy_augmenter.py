from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

import cv2

from ._image_io import read_image, write_image


PARAMETERS = []


def run(payload: dict[str, Any], context: Any) -> dict[str, Any]:
    """复制源样本，生成内容相同的增强副本。"""
    parameters = payload.get("parameters", {}) or {}
    input_data = payload.get("input", {}) or {}
    output_data = payload.get("output", {}) or {}

    output_dir_value = output_data.get("output_dir")
    if not output_dir_value:
        return {"ok": False, "error_code": "VALIDATION_ERROR", "message": "output_dir is required."}

    samples = list(input_data.get("samples", []) or [])
    if not samples:
        return {"ok": False, "error_code": "NO_INPUT_SAMPLES", "message": "No source samples provided."}

    target_count = int(payload.get("target_count") or len(samples))
    if target_count <= 0:
        return {"ok": False, "error_code": "VALIDATION_ERROR", "message": "target_count must be greater than zero."}

    output_dir = Path(output_dir_value)
    output_dir.mkdir(parents=True, exist_ok=True)

    outputs: list[dict[str, Any]] = []
    for index in range(target_count):
        if context.is_cancel_requested():
            return {"ok": False, "error_code": "CANCELLED", "message": "Generation cancelled."}

        sample = samples[index % len(samples)]
        source_path = Path(sample.get("sample_path") or sample.get("path") or sample.get("file_path") or "")
        if not source_path.is_file():
            return {
                "ok": False,
                "error_code": "SOURCE_FILE_NOT_FOUND",
                "message": f"Cannot read source sample: {source_path}",
            }

        target = output_dir / f"{source_path.stem}_copy_aug_{index:04d}{source_path.suffix or '.dat'}"
        changed = _write_augmented_copy(source_path, target)
        outputs.append(
            {
                "source_sample_id": sample.get("id"),
                "output_path": str(target),
                "relative_path": target.name,
                "metadata": {
                    "method": "copy",
                    "algorithm_key": payload.get("algorithm_key", "generation.copy_augmenter"),
                    "parameters": parameters,
                    "augmented_copy": changed,
                },
                "status": "created",
            }
        )
        context.set_progress((index + 1) * 100 / target_count, f"Generated {index + 1}/{target_count}")

    return {"ok": True, "outputs": outputs, "logs": []}


def _write_augmented_copy(source_path: Path, target: Path) -> bool:
    if source_path.suffix.lower() in {".bmp", ".jpeg", ".jpg", ".png", ".tif", ".tiff", ".webp"}:
        img = read_image(source_path)
        if img is None:
            shutil.copy2(source_path, target)
            return False
        h, w = img.shape[:2]
        center = (w / 2.0, h / 2.0)
        matrix = cv2.getRotationMatrix2D(center, 2.5, 1.0)
        rotated = cv2.warpAffine(img, matrix, (w, h), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)
        enhanced = cv2.convertScaleAbs(rotated, alpha=1.12, beta=8)
        blur = cv2.GaussianBlur(enhanced, (0, 0), 1.0)
        out = cv2.addWeighted(enhanced, 1.25, blur, -0.25, 0)
        return bool(write_image(target, out))

    if source_path.suffix.lower() in {".txt", ".md", ".csv", ".json", ".xml", ".yaml", ".yml"}:
        text = source_path.read_text(encoding="utf-8", errors="ignore")
        target.write_text(text + "\n# augmented copy\n", encoding="utf-8")
        return True

    shutil.copy2(source_path, target)
    return False
