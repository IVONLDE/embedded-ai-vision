from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from ._image_io import read_image, write_image


PARAMETERS = [
    {
        "name": "fog_intensity",
        "type": "float",
        "label": "雾气浓度",
        "default": 0.45,
        "min": 0.0,
        "max": 1.0,
        "options": [],
        "description": "大气散射模拟强度",
        "required": False,
    },
    {
        "name": "snow_intensity",
        "type": "float",
        "label": "雪花强度",
        "default": 0.35,
        "min": 0.0,
        "max": 1.0,
        "options": [],
        "description": "雪花叠加强度",
        "required": False,
    },
    {
        "name": "shadow_intensity",
        "type": "float",
        "label": "阴影强度",
        "default": 0.35,
        "min": 0.0,
        "max": 1.0,
        "options": [],
        "description": "随机阴影块强度",
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
    fog_strength = _clamp_float(parameters.get("fog_intensity", parameters.get("fog", 0.45)), 0.0, 1.0)
    snow_strength = _clamp_float(parameters.get("snow_intensity", parameters.get("snow", 0.35)), 0.0, 1.0)
    shadow_strength = _clamp_float(parameters.get("shadow_intensity", parameters.get("shadow", 0.35)), 0.0, 1.0)

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

        h, w = img.shape[:2]
        out = img.astype(np.float32)

        if fog_strength > 0:
            yy = np.linspace(0.15, 1.0, h, dtype=np.float32)[:, None]
            depth = np.repeat(yy, w, axis=1)
            depth += cv2.GaussianBlur(np.random.rand(h, w).astype(np.float32), (51, 51), 0) * 0.35
            depth = (depth - depth.min()) / (depth.max() - depth.min() + 1e-6)
            trans = np.exp(-fog_strength * 2.4 * depth)[..., None]
            airlight = np.array([210, 215, 220], dtype=np.float32)
            out = out * trans + airlight * (1.0 - trans)

        if snow_strength > 0:
            snow = np.zeros((h, w), dtype=np.uint8)
            n_snow = max(20, int((h * w) * 0.0012 * snow_strength))
            for _ in range(n_snow):
                x = int(np.random.randint(0, w))
                y = int(np.random.randint(0, h))
                r = int(np.random.randint(1, 2 + int(4 * snow_strength)))
                cv2.circle(snow, (x, y), r, 255, -1)
            snow_f = cv2.GaussianBlur(snow, (5, 5), 0).astype(np.float32) / 255.0
            out = out * (1.0 - 0.25 * snow_strength) + 255.0 * snow_f[..., None] * (0.85 * snow_strength)

        if shadow_strength > 0:
            mask = np.ones((h, w), dtype=np.float32)
            for _ in range(2):
                cx = int(np.random.randint(0, w))
                cy = int(np.random.randint(0, h))
                ax = int(w * np.random.uniform(0.28, 0.75))
                ay = int(h * np.random.uniform(0.22, 0.65))
                angle = float(np.random.uniform(0, 180))
                ellipse = np.zeros((h, w), dtype=np.uint8)
                cv2.ellipse(ellipse, (cx, cy), (ax, ay), angle, 0, 360, 255, -1)
                ellipse_f = cv2.GaussianBlur(ellipse.astype(np.float32), (31, 31), 0) / 255.0
                mask *= 1.0 - ellipse_f * 0.55 * shadow_strength
            out *= mask[..., None]

        augmented = np.clip(out, 0, 255).astype(np.uint8)
        output_path = output_dir / f"{source_path.stem}_env_{index:04d}{source_path.suffix or '.jpg'}"
        if not write_image(output_path, augmented):
            return {"ok": False, "error_code": "IMAGE_WRITE_ERROR", "message": f"Cannot write image: {output_path}"}

        outputs.append(
            {
                "source_sample_id": sample.get("id"),
                "output_path": str(output_path),
                "relative_path": output_path.name,
                "metadata": {
                    "method": "environment_simulation",
                    "algorithm_key": payload.get("algorithm_key", "generation.image.environment_simulation"),
                    "parameters": {
                        "fog_intensity": fog_strength,
                        "snow_intensity": snow_strength,
                        "shadow_intensity": shadow_strength,
                    },
                },
                "status": "created",
            }
        )
        context.set_progress((index + 1) * 100 / target_count, f"环境模拟 {index + 1}/{target_count}")

    return {"ok": True, "outputs": outputs, "logs": []}


def _clamp_float(value, low, high):
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        parsed = low
    return max(low, min(parsed, high))
