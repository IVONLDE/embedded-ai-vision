from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from ._image_io import read_image, write_image


PARAMETERS = [
    {
        "name": "blur_kernel",
        "type": "int",
        "label": "模糊核大小",
        "default": 5,
        "min": 0,
        "max": 15,
        "options": [],
        "description": "传感器/光学模糊核大小，默认产生可见成像退化",
        "required": False,
    },
    {
        "name": "downsample",
        "type": "float",
        "label": "下采样比例",
        "default": 0.5,
        "min": 0.1,
        "max": 1.0,
        "options": [],
        "description": "先降采样再放回原尺寸，默认产生低清成像效果",
        "required": False,
    },
]


def run(payload: dict, context) -> dict:
    parameters = payload.get("parameters", {}) or {}
    output_dir = Path(payload.get("output", {}).get("output_dir") or ".")
    output_dir.mkdir(parents=True, exist_ok=True)

    samples = payload.get("input", {}).get("samples", []) or []
    if not samples:
        return {"ok": False, "error_code": "NO_INPUT_SAMPLES", "message": "未提供源样本。"}

    target_count = max(1, int(payload.get("target_count") or len(samples)))
    blur_kernel = _clamp_int(parameters.get("blur_kernel", 5), 0, 15)
    downsample = _clamp_float(parameters.get("downsample", 0.5), 0.1, 1.0)

    outputs = []
    for index in range(target_count):
        if context.is_cancel_requested():
            return {"ok": False, "error_code": "CANCELLED", "message": "任务已取消。"}

        sample = samples[index % len(samples)]
        source_path = Path(sample.get("sample_path") or sample.get("path") or sample.get("file_path") or "")
        img = read_image(source_path)
        if img is None:
            continue
        if len(img.shape) == 2:
            img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)

        out = img.astype(np.float32) / 255.0
        if blur_kernel > 1:
            kernel = blur_kernel if blur_kernel % 2 == 1 else blur_kernel + 1
            out = cv2.GaussianBlur(out, (kernel, kernel), 0)

        if downsample < 1.0:
            h, w = out.shape[:2]
            nh = max(1, int(h * downsample))
            nw = max(1, int(w * downsample))
            small = cv2.resize(out, (nw, nh), interpolation=cv2.INTER_AREA)
            out = cv2.resize(small, (w, h), interpolation=cv2.INTER_LINEAR)

        augmented = np.clip(out * 255.0, 0, 255).astype(np.uint8)
        output_path = output_dir / f"{source_path.stem}_imaging_{index:04d}{source_path.suffix or '.jpg'}"
        if not write_image(output_path, augmented):
            return {"ok": False, "error_code": "IMAGE_WRITE_ERROR", "message": f"Cannot write image: {output_path}"}

        outputs.append(
            {
                "source_sample_id": sample.get("id"),
                "output_path": str(output_path),
                "relative_path": output_path.name,
                "metadata": {
                    "method": "imaging_simulation",
                    "algorithm_key": payload.get("algorithm_key", "generation.image.imaging_simulation"),
                    "parameters": {"blur_kernel": blur_kernel, "downsample": downsample},
                },
                "status": "created",
            }
        )
        context.set_progress((index + 1) * 100 / target_count, f"成像模拟 {index + 1}/{target_count}")

    return {"ok": True, "outputs": outputs, "logs": []}


def _clamp_float(value, low, high):
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        parsed = low
    return max(low, min(parsed, high))


def _clamp_int(value, low, high):
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = low
    return max(low, min(parsed, high))
