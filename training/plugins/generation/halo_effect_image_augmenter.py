from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from ._image_io import read_image, write_image


PARAMETERS = [
    {
        "name": "mode",
        "type": "select",
        "label": "处理模式",
        "default": "simulate",
        "min": None,
        "max": None,
        "options": ["simulate", "remove"],
        "description": "simulate=热晕模拟，remove=热晕消除",
        "required": False,
    },
    {
        "name": "halo_strength",
        "type": "float",
        "label": "热晕强度",
        "default": 0.5,
        "min": 0.0,
        "max": 1.0,
        "options": [],
        "description": "热晕效果强度",
        "required": False,
    },
    {
        "name": "halo_radius",
        "type": "int",
        "label": "热晕半径",
        "default": 24,
        "min": 3,
        "max": 128,
        "options": [],
        "description": "热晕扩散半径",
        "required": False,
    },
    {
        "name": "dehalo_clip",
        "type": "float",
        "label": "消除抑制",
        "default": 0.7,
        "min": 0.0,
        "max": 1.0,
        "options": [],
        "description": "热晕消除时的抑制强度",
        "required": False,
    },
]


def run(payload: dict, context) -> dict:
    """热晕处理：支持热晕模拟与热晕消除。"""
    parameters = payload.get("parameters", {}) or {}
    output_dir = Path(payload.get("output", {}).get("output_dir") or ".")
    output_dir.mkdir(parents=True, exist_ok=True)

    samples = payload.get("input", {}).get("samples", []) or []
    if not samples:
        return {"ok": False, "error_code": "NO_INPUT_SAMPLES", "message": "未提供源样本。"}

    target_count = max(1, int(payload.get("target_count") or len(samples)))
    mode = str(parameters.get("mode", parameters.get("处理模式", "simulate")) or "simulate").strip().lower()
    halo_strength = float(parameters.get("halo_strength", parameters.get("热晕强度", 0.5)) or 0.5)
    halo_radius = int(parameters.get("halo_radius", parameters.get("热晕半径", 24)) or 24)
    dehalo_clip = float(parameters.get("dehalo_clip", parameters.get("消除抑制", 0.7)) or 0.7)

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

        if mode == "remove":
            out = _remove_halo(image, halo_strength, halo_radius, dehalo_clip)
        else:
            out = _simulate_halo(image, halo_strength, halo_radius)

        output_path = output_dir / f"{source_path.stem}_halo_{index:04d}{source_path.suffix or '.jpg'}"
        if not write_image(output_path, out):
            return {"ok": False, "error_code": "IMAGE_WRITE_ERROR", "message": f"Cannot write image: {output_path}"}

        outputs.append(
            {
                "source_sample_id": sample.get("id"),
                "output_path": str(output_path),
                "relative_path": output_path.name,
                "metadata": {
                    "method": "halo_effect",
                    "algorithm_key": payload.get("algorithm_key", "generation.image.halo_effect"),
                    "parameters": {
                        "mode": mode,
                        "halo_strength": halo_strength,
                        "halo_radius": halo_radius,
                        "dehalo_clip": dehalo_clip,
                    },
                },
                "status": "created",
            }
        )
        context.set_progress((index + 1) * 100 / target_count, f"热晕处理 {index + 1}/{target_count}")

    return {"ok": True, "outputs": outputs, "logs": []}


def _simulate_halo(image: np.ndarray, strength: float, radius: int) -> np.ndarray:
    base = image.astype(np.float32) / 255.0
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY).astype(np.float32) / 255.0
    bright = np.clip((gray - 0.45) * 2.2, 0.0, 1.0)
    halo = cv2.GaussianBlur(bright, (0, 0), sigmaX=max(1.0, radius / 3.0), sigmaY=max(1.0, radius / 3.0))
    halo = np.clip(halo, 0.0, 1.0)
    halo_rgb = np.repeat(halo[:, :, None], 3, axis=2)
    glow = np.clip(base + halo_rgb * strength * 0.75, 0.0, 1.0)
    out = np.clip(glow * (1.0 - strength * 0.15) + 0.15 * halo_rgb * strength, 0.0, 1.0)
    return (out * 255.0).astype(np.uint8)


def _remove_halo(image: np.ndarray, strength: float, radius: int, dehalo_clip: float) -> np.ndarray:
    base = image.astype(np.float32) / 255.0
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY).astype(np.float32) / 255.0
    blur = cv2.GaussianBlur(gray, (0, 0), sigmaX=max(1.0, radius / 4.0), sigmaY=max(1.0, radius / 4.0))
    detail = gray - blur
    corrected = gray - np.clip(detail, 0.0, 1.0) * strength * dehalo_clip
    corrected = np.clip(corrected, 0.0, 1.0)
    corrected_bgr = cv2.cvtColor((corrected * 255.0).astype(np.uint8), cv2.COLOR_GRAY2BGR).astype(np.float32) / 255.0
    out = np.clip(base * (1.0 - 0.3 * strength) + corrected_bgr * (0.3 + 0.7 * strength), 0.0, 1.0)
    out = cv2.GaussianBlur(out, (3, 3), 0)
    return (out * 255.0).astype(np.uint8)
