from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from ._image_io import read_image, write_image


PARAMETERS = [
    {
        "name": "alpha",
        "type": "float",
        "label": "线性倍率",
        "default": 1.6,
        "min": 0.2,
        "max": 3.0,
        "options": [],
        "description": "像素线性变换倍率，控制整体对比度",
        "required": False,
    },
    {
        "name": "beta",
        "type": "float",
        "label": "线性偏置",
        "default": 35.0,
        "min": -100.0,
        "max": 100.0,
        "options": [],
        "description": "像素线性变换偏置，控制整体亮度",
        "required": False,
    },
    {
        "name": "gamma",
        "type": "float",
        "label": "伽马校正",
        "default": 1.1,
        "min": 0.2,
        "max": 3.0,
        "options": [],
        "description": "线性变换后的伽马校正，1.0 表示不校正",
        "required": False,
    },
]


def run(payload: dict, context) -> dict:
    """图像线性变化：alpha * image + beta，并支持可选 gamma 校正。"""
    parameters = payload.get("parameters", {}) or {}
    output_dir = Path(payload.get("output", {}).get("output_dir") or ".")
    output_dir.mkdir(parents=True, exist_ok=True)

    samples = payload.get("input", {}).get("samples", []) or []
    samples = [sample for sample in samples if _is_image_sample(sample)]
    if not samples:
        return {"ok": False, "error_code": "NO_INPUT_SAMPLES", "message": "未提供图像源样本。"}

    target_count = max(1, int(payload.get("target_count") or len(samples)))
    alpha = _clamp_float(parameters.get("alpha", 1.6), 0.2, 3.0)
    beta = _clamp_float(parameters.get("beta", 35.0), -100.0, 100.0)
    gamma = _clamp_float(parameters.get("gamma", 1.1), 0.2, 3.0)

    outputs = []
    for index in range(target_count):
        if context.is_cancel_requested():
            return {"ok": False, "error_code": "CANCELLED", "message": "任务已取消。"}

        sample = samples[index % len(samples)]
        source_path = _sample_path(sample)
        img = read_image(source_path)
        if img is None:
            continue
        if len(img.shape) == 2:
            img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)

        out = img.astype(np.float32) * alpha + beta
        out = np.clip(out, 0, 255) / 255.0
        if gamma != 1.0:
            out = np.power(out, 1.0 / gamma)
        augmented = np.clip(out * 255.0, 0, 255).astype(np.uint8)

        output_path = output_dir / f"{source_path.stem}_linear_{index:04d}{source_path.suffix or '.jpg'}"
        if not write_image(output_path, augmented):
            return {"ok": False, "error_code": "IMAGE_WRITE_ERROR", "message": f"Cannot write image: {output_path}"}

        outputs.append(
            {
                "source_sample_id": sample.get("id"),
                "output_path": str(output_path),
                "relative_path": output_path.name,
                "metadata": {
                    "method": "linear_transform",
                    "algorithm_key": payload.get("algorithm_key", "generation.image.linear_transform"),
                    "parameters": {
                        "alpha": alpha,
                        "beta": beta,
                        "gamma": gamma,
                    },
                },
                "status": "created",
            }
        )
        context.set_progress((index + 1) * 100 / target_count, f"线性变化 {index + 1}/{target_count}")

    return {"ok": True, "outputs": outputs, "logs": []}


def _sample_path(sample):
    return Path(sample.get("sample_path") or sample.get("path") or sample.get("file_path") or "")


def _is_image_sample(sample):
    return _sample_path(sample).suffix.lower() in {".bmp", ".jpeg", ".jpg", ".png", ".tif", ".tiff", ".webp"}


def _clamp_float(value, low, high):
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        parsed = low
    return max(low, min(parsed, high))
