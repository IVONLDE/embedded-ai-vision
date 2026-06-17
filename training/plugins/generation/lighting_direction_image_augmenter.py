from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from ._image_io import read_image, write_image


PARAMETERS = [
    {
        "name": "light_direction",
        "type": "select",
        "label": "光照方向",
        "default": "left_to_right",
        "min": None,
        "max": None,
        "options": ["left_to_right", "right_to_left", "top_to_bottom", "bottom_to_top"],
        "description": "选择光照渐变方向",
        "required": False,
    },
    {
        "name": "light_strength",
        "type": "float",
        "label": "光照强度",
        "default": 0.5,
        "min": 0.0,
        "max": 1.0,
        "options": [],
        "description": "光照方向变化的强度",
        "required": False,
    },
    {
        "name": "ambient_level",
        "type": "float",
        "label": "环境光",
        "default": 0.15,
        "min": 0.0,
        "max": 1.0,
        "options": [],
        "description": "整体环境光抬升比例",
        "required": False,
    },
]


def run(payload: dict, context) -> dict:
    """光照方向调整：通过方向性明暗梯度模拟左/右/上/下光照变化。"""
    parameters = payload.get("parameters", {}) or {}
    output_dir = Path(payload.get("output", {}).get("output_dir") or ".")
    output_dir.mkdir(parents=True, exist_ok=True)

    samples = payload.get("input", {}).get("samples", []) or []
    if not samples:
        return {"ok": False, "error_code": "NO_INPUT_SAMPLES", "message": "未提供源样本。"}

    target_count = max(1, int(payload.get("target_count") or len(samples)))
    direction = str(parameters.get("light_direction", parameters.get("光照方向", "left_to_right")) or "left_to_right").strip().lower()
    light_strength = float(parameters.get("light_strength", parameters.get("光照强度", 0.5)) or 0.5)
    ambient_level = float(parameters.get("ambient_level", parameters.get("环境光", 0.15)) or 0.15)

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
        h, w = base.shape[:2]
        gradient = _directional_gradient(h, w, direction)

        # 让亮部和暗部都留一点底色，避免过黑或过曝
        shade = 1.0 - light_strength * (0.5 + 0.5 * gradient)
        highlight = 1.0 + light_strength * 0.35 * gradient
        lighting = np.clip(shade * highlight + ambient_level, 0.0, 1.0)
        lighting = lighting[..., None]

        out = np.clip(base * lighting + ambient_level * 0.25, 0.0, 1.0)
        out = (out * 255.0).astype(np.uint8)

        output_path = output_dir / f"{source_path.stem}_lightdir_{index:04d}{source_path.suffix or '.jpg'}"
        if not write_image(output_path, out):
            return {"ok": False, "error_code": "IMAGE_WRITE_ERROR", "message": f"Cannot write image: {output_path}"}

        outputs.append(
            {
                "source_sample_id": sample.get("id"),
                "output_path": str(output_path),
                "relative_path": output_path.name,
                "metadata": {
                    "method": "lighting_direction",
                    "algorithm_key": payload.get("algorithm_key", "generation.image.lighting_direction"),
                    "parameters": {
                        "light_direction": direction,
                        "light_strength": light_strength,
                        "ambient_level": ambient_level,
                    },
                },
                "status": "created",
            }
        )
        context.set_progress((index + 1) * 100 / target_count, f"光照方向调整 {index + 1}/{target_count}")

    return {"ok": True, "outputs": outputs, "logs": []}


def _directional_gradient(h: int, w: int, direction: str) -> np.ndarray:
    xs = np.linspace(0.0, 1.0, w, dtype=np.float32)
    ys = np.linspace(0.0, 1.0, h, dtype=np.float32)
    xv, yv = np.meshgrid(xs, ys)

    if direction == "right_to_left":
        grad = 1.0 - xv
    elif direction == "top_to_bottom":
        grad = yv
    elif direction == "bottom_to_top":
        grad = 1.0 - yv
    else:
        grad = xv

    # 轻微平滑，避免过于生硬的分界
    grad = cv2.GaussianBlur(grad, (0, 0), sigmaX=max(1.0, min(h, w) / 24.0))
    grad = grad - float(grad.min())
    denom = float(grad.max()) + 1e-6
    return grad / denom
