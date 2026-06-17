from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from ._image_io import read_image, write_image


PARAMETERS = [
    {
        "name": "texture_strength",
        "type": "float",
        "label": "纹理增强强度",
        "default": 0.5,
        "min": 0.0,
        "max": 1.0,
        "options": [],
        "description": "高频纹理增强混合强度",
        "required": False,
    },
    {
        "name": "detail_sigma",
        "type": "float",
        "label": "细节半径",
        "default": 1.2,
        "min": 0.1,
        "max": 10.0,
        "options": [],
        "description": "高频细节提取的高斯模糊半径",
        "required": False,
    },
    {
        "name": "detail_gain",
        "type": "float",
        "label": "细节增益",
        "default": 1.0,
        "min": 0.1,
        "max": 5.0,
        "options": [],
        "description": "高频纹理增强系数",
        "required": False,
    },
]


def run(payload: dict, context) -> dict:
    """纹理增强：通过高频细节提取与局部对比度增强模拟纹理增强效果。"""
    parameters = payload.get("parameters", {}) or {}
    output_dir = Path(payload.get("output", {}).get("output_dir") or ".")
    output_dir.mkdir(parents=True, exist_ok=True)

    samples = payload.get("input", {}).get("samples", []) or []
    if not samples:
        return {"ok": False, "error_code": "NO_INPUT_SAMPLES", "message": "未提供源样本。"}

    target_count = max(1, int(payload.get("target_count") or len(samples)))
    texture_strength = float(parameters.get("texture_strength", parameters.get("纹理增强强度", 0.5)) or 0.5)
    detail_sigma = float(parameters.get("detail_sigma", parameters.get("细节半径", 1.2)) or 1.2)
    detail_gain = float(parameters.get("detail_gain", parameters.get("细节增益", 1.0)) or 1.0)

    outputs = []
    for index in range(target_count):
        if context.is_cancel_requested():
            return {"ok": False, "error_code": "CANCELLED", "message": "任务已取消。"}

        sample = samples[index % len(samples)]
        source_path = Path(sample.get("sample_path") or sample.get("path") or sample.get("file_path") or "")
        image = read_image(source_path)
        if image is None:
            continue

        if len(image.shape) == 2:
            image = cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)

        base = image.astype(np.float32) / 255.0
        detail = _extract_detail_map(base, detail_sigma)
        enhanced = np.clip(base + detail * detail_gain * texture_strength, 0.0, 1.0)

        gray = cv2.cvtColor((enhanced * 255.0).astype(np.uint8), cv2.COLOR_BGR2GRAY)
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        local = clahe.apply(gray).astype(np.float32) / 255.0
        local = cv2.cvtColor(local.astype(np.float32), cv2.COLOR_GRAY2BGR)
        out = np.clip(enhanced * (1.0 - texture_strength * 0.35) + local * (texture_strength * 0.35), 0.0, 1.0)
        out = (out * 255.0).astype(np.uint8)

        output_path = output_dir / f"{source_path.stem}_texture_{index:04d}{source_path.suffix or '.jpg'}"
        if not write_image(output_path, out):
            return {"ok": False, "error_code": "IMAGE_WRITE_ERROR", "message": f"Cannot write image: {output_path}"}

        outputs.append(
            {
                "source_sample_id": sample.get("id"),
                "output_path": str(output_path),
                "relative_path": output_path.name,
                "metadata": {
                    "method": "texture_enhancement",
                    "algorithm_key": payload.get("algorithm_key", "generation.image.texture_enhancement"),
                    "parameters": {
                        "texture_strength": texture_strength,
                        "detail_sigma": detail_sigma,
                        "detail_gain": detail_gain,
                    },
                },
                "status": "created",
            }
        )
        context.set_progress((index + 1) * 100 / target_count, f"纹理增强 {index + 1}/{target_count}")

    return {"ok": True, "outputs": outputs, "logs": []}


def _extract_detail_map(base: np.ndarray, sigma: float) -> np.ndarray:
    blur = cv2.GaussianBlur(base, (0, 0), sigmaX=max(0.1, sigma), sigmaY=max(0.1, sigma))
    detail = base - blur
    return detail
