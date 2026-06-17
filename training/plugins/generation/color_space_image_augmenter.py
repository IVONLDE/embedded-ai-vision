from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from ._image_io import read_image, write_image


PARAMETERS = [
    {
        "name": "brightness",
        "type": "float",
        "label": "亮度增量",
        "default": 14.0,
        "min": -100.0,
        "max": 100.0,
        "options": [],
        "description": "整体亮度增量",
        "required": False,
    },
    {
        "name": "contrast",
        "type": "float",
        "label": "对比度系数",
        "default": 1.18,
        "min": 0.2,
        "max": 3.0,
        "options": [],
        "description": "整体对比度缩放系数",
        "required": False,
    },
    {
        "name": "saturation",
        "type": "float",
        "label": "饱和度系数",
        "default": 1.25,
        "min": 0.0,
        "max": 3.0,
        "options": [],
        "description": "HSV 饱和度缩放系数",
        "required": False,
    },
    {
        "name": "hue",
        "type": "float",
        "label": "色相偏移",
        "default": 8.0,
        "min": -90.0,
        "max": 90.0,
        "options": [],
        "description": "HSV 色相偏移量",
        "required": False,
    },
    {
        "name": "pca_jitter",
        "type": "float",
        "label": "PCA颜色抖动",
        "default": 0.08,
        "min": 0.0,
        "max": 1.0,
        "options": [],
        "description": "沿图像颜色主方向添加轻微扰动",
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
    brightness = _clamp_float(parameters.get("brightness", 14.0), -100.0, 100.0)
    contrast = _clamp_float(parameters.get("contrast", 1.18), 0.2, 3.0)
    saturation = _clamp_float(parameters.get("saturation", 1.25), 0.0, 3.0)
    hue = _clamp_float(parameters.get("hue", 8.0), -90.0, 90.0)
    pca_jitter = _clamp_float(parameters.get("pca_jitter", parameters.get("pca_strength", 0.08)), 0.0, 1.0)

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

        img_f = img.astype(np.float32) * contrast + brightness
        hsv = cv2.cvtColor(np.clip(img_f, 0, 255).astype(np.uint8), cv2.COLOR_BGR2HSV).astype(np.float32)
        hsv[..., 1] = np.clip(hsv[..., 1] * saturation, 0, 255)
        hsv[..., 0] = (hsv[..., 0] + hue) % 180
        out = cv2.cvtColor(hsv.astype(np.uint8), cv2.COLOR_HSV2BGR).astype(np.float32)

        if pca_jitter > 0:
            out = _apply_pca_jitter(out, pca_jitter)

        output_path = output_dir / f"{source_path.stem}_color_{index:04d}{source_path.suffix or '.jpg'}"
        if not write_image(output_path, np.clip(out, 0, 255).astype(np.uint8)):
            return {"ok": False, "error_code": "IMAGE_WRITE_ERROR", "message": f"Cannot write image: {output_path}"}

        outputs.append(
            {
                "source_sample_id": sample.get("id"),
                "output_path": str(output_path),
                "relative_path": output_path.name,
                "metadata": {
                    "method": "color_space",
                    "algorithm_key": payload.get("algorithm_key", "generation.image.color_space"),
                    "parameters": {
                        "brightness": brightness,
                        "contrast": contrast,
                        "saturation": saturation,
                        "hue": hue,
                        "pca_jitter": pca_jitter,
                    },
                },
                "status": "created",
            }
        )
        context.set_progress((index + 1) * 100 / target_count, f"色域变换 {index + 1}/{target_count}")

    return {"ok": True, "outputs": outputs, "logs": []}


def _apply_pca_jitter(img_f: np.ndarray, strength: float) -> np.ndarray:
    pixels = img_f.reshape(-1, 3)
    centered = pixels - np.mean(pixels, axis=0, keepdims=True)
    cov = np.cov(centered, rowvar=False)
    eigvals, eigvecs = np.linalg.eigh(cov)
    order = np.argsort(eigvals)[::-1]
    eigvals = eigvals[order]
    eigvecs = eigvecs[:, order]
    alpha = np.array([0.7, -0.35, 0.2], dtype=np.float32)
    lighting = eigvecs @ (np.sqrt(np.maximum(eigvals, 0)) * alpha)
    return img_f + lighting.astype(np.float32) * strength


def _clamp_float(value, low, high):
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        parsed = low
    return max(low, min(parsed, high))
