from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from ._image_io import read_image, write_image


PARAMETERS = [
    {
        "name": "stretch_low_pct",
        "type": "float",
        "label": "灰度拉伸下限百分位",
        "default": 2.0,
        "min": 0.0,
        "max": 49.0,
        "options": [],
        "description": "用于灰度拉伸的低端百分位阈值",
        "required": False,
    },
    {
        "name": "stretch_high_pct",
        "type": "float",
        "label": "灰度拉伸上限百分位",
        "default": 98.0,
        "min": 51.0,
        "max": 100.0,
        "options": [],
        "description": "用于灰度拉伸的高端百分位阈值",
        "required": False,
    },
    {
        "name": "clahe_clip",
        "type": "float",
        "label": "CLAHE剪切限制",
        "default": 2.0,
        "min": 0.0,
        "max": 10.0,
        "options": [],
        "description": "CLAHE 的剪切阈值",
        "required": False,
    },
    {
        "name": "clahe_tile",
        "type": "int",
        "label": "CLAHE网格大小",
        "default": 8,
        "min": 2,
        "max": 32,
        "options": [],
        "description": "CLAHE 的 tileGridSize",
        "required": False,
    },
]


def run(payload: dict, context) -> dict:
    """温度校准：灰度拉伸与 CLAHE 增强。"""
    parameters = payload.get("parameters", {}) or {}
    output_dir = Path(payload.get("output", {}).get("output_dir") or ".")
    output_dir.mkdir(parents=True, exist_ok=True)

    samples = payload.get("input", {}).get("samples", []) or []
    if not samples:
        return {"ok": False, "error_code": "NO_INPUT_SAMPLES", "message": "未提供源样本。"}

    target_count = max(1, int(payload.get("target_count") or len(samples)))
    stretch_low_pct = float(parameters.get("stretch_low_pct", parameters.get("灰度拉伸下限百分位", 2.0)) or 2.0)
    stretch_high_pct = float(parameters.get("stretch_high_pct", parameters.get("灰度拉伸上限百分位", 98.0)) or 98.0)
    clahe_clip = float(parameters.get("clahe_clip", parameters.get("CLAHE剪切限制", 2.0)) or 2.0)
    clahe_tile = int(parameters.get("clahe_tile", parameters.get("CLAHE网格大小", 8)) or 8)

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
            gray = image
            base_bgr = cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
        else:
            base_bgr = image
            gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)

        stretched = _gray_stretch(gray, stretch_low_pct, stretch_high_pct)
        clahe = cv2.createCLAHE(clipLimit=max(0.1, clahe_clip), tileGridSize=(max(2, clahe_tile), max(2, clahe_tile)))
        clahe_gray = clahe.apply(stretched)

        # 保持三通道输出，方便后续前端/后端统一处理
        out = cv2.cvtColor(clahe_gray, cv2.COLOR_GRAY2BGR)

        # 用轻微的原图细节回填一点颜色，避免过于“灰”
        if len(base_bgr.shape) == 3:
            detail = cv2.GaussianBlur(base_bgr, (0, 0), 1.0)
            out = cv2.addWeighted(out, 0.85, detail, 0.15, 0)

        output_path = output_dir / f"{source_path.stem}_tempcal_{index:04d}{source_path.suffix or '.jpg'}"
        if not write_image(output_path, out):
            return {"ok": False, "error_code": "IMAGE_WRITE_ERROR", "message": f"Cannot write image: {output_path}"}

        outputs.append(
            {
                "source_sample_id": sample.get("id"),
                "output_path": str(output_path),
                "relative_path": output_path.name,
                "metadata": {
                    "method": "temperature_calibration",
                    "algorithm_key": payload.get("algorithm_key", "generation.image.temperature_calibration"),
                    "parameters": {
                        "stretch_low_pct": stretch_low_pct,
                        "stretch_high_pct": stretch_high_pct,
                        "clahe_clip": clahe_clip,
                        "clahe_tile": clahe_tile,
                    },
                },
                "status": "created",
            }
        )
        context.set_progress((index + 1) * 100 / target_count, f"温度校准 {index + 1}/{target_count}")

    return {"ok": True, "outputs": outputs, "logs": []}


def _gray_stretch(gray: np.ndarray, low_pct: float, high_pct: float) -> np.ndarray:
    low_pct = float(max(0.0, min(low_pct, 49.0)))
    high_pct = float(max(51.0, min(high_pct, 100.0)))
    if low_pct >= high_pct:
        low_pct, high_pct = 2.0, 98.0

    low = float(np.percentile(gray, low_pct))
    high = float(np.percentile(gray, high_pct))
    if abs(high - low) < 1e-6:
        return gray.copy()

    stretched = (gray.astype(np.float32) - low) * 255.0 / (high - low)
    return np.clip(stretched, 0, 255).astype(np.uint8)
