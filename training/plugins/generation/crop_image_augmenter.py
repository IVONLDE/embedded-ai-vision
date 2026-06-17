from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from ._image_io import read_image, write_image

PARAMETERS = [
    {
        "name": 'crop_ratio',
        "type": 'float',
        "label": '剪切比例',
        "default": 0.8,
        "min": 0.3,
        "max": 0.95,
        "options": [],
        "description": '保留原图的面积比例 (0.8=保留80%区域)',
        "required": False,
    },
    {
        "name": 'crop_mode',
        "type": 'string',
        "label": '裁剪模式',
        "default": 'random',
        "min": None,
        "max": None,
        "options": ['random', 'center'],
        "description": 'random=随机位置裁剪, center=中心裁剪',
        "required": False,
    },
]


def run(payload: dict, context) -> dict:
    parameters = payload.get("parameters", {}) or {}
    output_dir = Path(payload.get("output", {}).get("output_dir") or ".")
    output_dir.mkdir(parents=True, exist_ok=True)

    samples = payload.get("input", {}).get("samples", []) or []
    if not samples:
        return {"ok": False, "error_code": "NO_INPUT_SAMPLES", "message": "No source samples provided."}

    target_count = max(1, int(payload.get("target_count") or len(samples)))
    crop_ratio = float(parameters.get("crop_ratio", 0.8))
    crop_mode = str(parameters.get("crop_mode", "random"))

    outputs = []
    for index in range(target_count):
        if context.is_cancel_requested():
            return {"ok": False, "error_code": "CANCELLED", "message": "Generation cancelled."}

        sample = samples[index % len(samples)]
        source_path = Path(sample.get("sample_path") or sample.get("path") or sample.get("file_path") or "")
        image = read_image(source_path)
        if image is None:
            continue

        h, w = image.shape[:2]
        crop_w = max(1, int(w * crop_ratio))
        crop_h = max(1, int(h * crop_ratio))

        if crop_mode == "center":
            x = (w - crop_w) // 2
            y = (h - crop_h) // 2
        else:
            x = np.random.randint(0, max(1, w - crop_w + 1))
            y = np.random.randint(0, max(1, h - crop_h + 1))

        cropped = image[y:y + crop_h, x:x + crop_w].copy()
        output_path = output_dir / f"{Path(source_path).stem}_crop_{index:04d}{Path(source_path).suffix or '.jpg'}"
        if not write_image(output_path, cropped):
            return {"ok": False, "error_code": "IMAGE_WRITE_ERROR", "message": f"Cannot write image: {output_path}"}

        outputs.append({
            "source_sample_id": sample.get("id"),
            "output_path": str(output_path),
            "relative_path": output_path.name,
            "metadata": {"method": "crop", "crop_ratio": crop_ratio, "crop_mode": crop_mode,
                         "algorithm_key": payload.get("algorithm_key", "generation.image.crop")},
            "status": "created",
        })
        context.set_progress((index + 1) * 100 / target_count, f"Crop {index + 1}/{target_count}")

    return {"ok": True, "outputs": outputs, "logs": []}
