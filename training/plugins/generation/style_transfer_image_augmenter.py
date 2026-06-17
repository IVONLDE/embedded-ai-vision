from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from ._image_io import read_image, write_image


PARAMETERS = [
    {
        "name": 'strength',
        "type": 'float',
        "label": '风格强度',
        "default": 0.7,
        "min": 0.0,
        "max": 1.0,
        "options": [],
        "description": '风格化叠加强度，0为原图，1为纯边缘',
        "required": False,
    },
]


def run(payload: dict, context) -> dict:
    """风格迁移增强：使用边缘检测叠加模拟风格化效果。"""
    parameters = payload.get("parameters", {}) or {}
    output_dir = Path(payload.get("output", {}).get("output_dir") or ".")
    output_dir.mkdir(parents=True, exist_ok=True)

    samples = payload.get("input", {}).get("samples", []) or []
    if not samples:
        return {"ok": False, "error_code": "NO_INPUT_SAMPLES", "message": "未提供源样本。"}

    target_count = max(1, int(payload.get("target_count") or len(samples)))
    strength = float(parameters.get("strength", parameters.get("风格强度", 0.7)) or 0.7)

    outputs = []
    for index in range(target_count):
        if context.is_cancel_requested():
            return {"ok": False, "error_code": "CANCELLED", "message": "任务已取消"}

        sample = samples[index % len(samples)]
        source_path = Path(sample.get("sample_path") or sample.get("path") or sample.get("file_path") or "")
        image = read_image(source_path)
        if image is None:
            continue

        # 转换为灰度并提取边缘
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        edges = cv2.Canny(gray, 100, 200)
        edges = cv2.cvtColor(edges, cv2.COLOR_GRAY2BGR)

        # 按强度混合原图与边缘，模拟风格迁移
        augmented = cv2.addWeighted(image, 1.0 - strength, edges, strength, 0)

        output_path = output_dir / f"{source_path.stem}_style_{index:04d}{source_path.suffix or '.jpg'}"
        if not write_image(output_path, augmented):
            return {"ok": False, "error_code": "IMAGE_WRITE_ERROR", "message": f"Cannot write image: {output_path}"}

        outputs.append({
            "source_sample_id": sample.get("id"),
            "output_path": str(output_path),
            "relative_path": output_path.name,
            "metadata": {
                "method": "style_transfer",
                "algorithm_key": payload.get("algorithm_key", "generation.image.style_transfer"),
                "parameters": {"strength": strength},
            },
            "status": "created",
        })
        context.set_progress((index + 1) * 100 / target_count, f"风格迁移 {index + 1}/{target_count}")

    return {"ok": True, "outputs": outputs, "logs": []}
