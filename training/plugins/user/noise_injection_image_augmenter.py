from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from plugins.generation._image_io import read_image, write_image


PARAMETERS = [
    {
        "name": "noise_type",
        "type": "select",
        "label": "噪声类型",
        "default": "gaussian",
        "min": None,
        "max": None,
        "options": ["gaussian", "salt_pepper", "multiplicative", "shot_read"],
        "description": "选择要注入的图像噪声类型",
        "required": False,
    },
    {
        "name": "noise_intensity",
        "type": "float",
        "label": "噪声强度",
        "default": 0.08,
        "min": 0.0,
        "max": 1.0,
        "options": [],
        "description": "高斯、椒盐和乘性噪声的通用强度",
        "required": False,
    },
    {
        "name": "salt_pepper_ratio",
        "type": "float",
        "label": "椒盐比例",
        "default": 0.5,
        "min": 0.0,
        "max": 1.0,
        "options": [],
        "description": "椒盐噪声中盐噪声所占比例",
        "required": False,
    },
    {
        "name": "shot_noise",
        "type": "float",
        "label": "散粒噪声强度",
        "default": 0.03,
        "min": 0.0,
        "max": 0.5,
        "options": [],
        "description": "shot_read 模式下的泊松散粒噪声强度",
        "required": False,
    },
    {
        "name": "read_noise",
        "type": "float",
        "label": "读出噪声标准差",
        "default": 0.01,
        "min": 0.0,
        "max": 0.1,
        "options": [],
        "description": "shot_read 模式下的高斯读出噪声标准差",
        "required": False,
    },
]


def run(payload: dict, context) -> dict:
    """图像噪声注入：高斯、椒盐、乘性、散粒/读出噪声。"""
    parameters = payload.get("parameters", {}) or {}
    output_dir = Path(payload.get("output", {}).get("output_dir") or ".")
    output_dir.mkdir(parents=True, exist_ok=True)

    samples = payload.get("input", {}).get("samples", []) or []
    samples = [sample for sample in samples if _is_image_sample(sample)]
    if not samples:
        return {"ok": False, "error_code": "NO_INPUT_SAMPLES", "message": "未提供图像源样本。"}

    target_count = max(1, int(payload.get("target_count") or len(samples)))
    noise_type = str(parameters.get("noise_type", parameters.get("噪声类型", "gaussian")) or "gaussian").lower()
    noise_intensity = _clamp_float(parameters.get("noise_intensity", parameters.get("噪声强度", 0.08)), 0.0, 1.0)
    salt_pepper_ratio = _clamp_float(parameters.get("salt_pepper_ratio", parameters.get("椒盐比例", 0.5)), 0.0, 1.0)
    shot_strength = _clamp_float(parameters.get("shot_noise", parameters.get("散粒噪声强度", 0.03)), 0.0, 0.5)
    read_noise_sigma = _clamp_float(parameters.get("read_noise", parameters.get("读出噪声标准差", 0.01)), 0.0, 0.1)

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

        out = img.astype(np.float32) / 255.0
        if noise_type == "salt_pepper":
            out = _apply_salt_pepper_noise(out, noise_intensity, salt_pepper_ratio)
        elif noise_type == "multiplicative":
            out = out * (1.0 + np.random.normal(0, noise_intensity, size=out.shape).astype(np.float32))
        elif noise_type == "shot_read":
            shot_std = np.sqrt(np.clip(out, 0, 1)) * shot_strength
            out = out + np.random.normal(0, shot_std, size=out.shape).astype(np.float32)
            out = out + np.random.normal(0, read_noise_sigma, size=out.shape).astype(np.float32)
        else:
            out = out + np.random.normal(0, noise_intensity, size=out.shape).astype(np.float32)

        augmented = (np.clip(out, 0.0, 1.0) * 255.0).astype(np.uint8)
        output_path = output_dir / f"{source_path.stem}_noise_{index:04d}{source_path.suffix or '.jpg'}"
        if not write_image(output_path, augmented):
            return {"ok": False, "error_code": "IMAGE_WRITE_ERROR", "message": f"Cannot write image: {output_path}"}

        outputs.append(
            {
                "source_sample_id": sample.get("id"),
                "output_path": str(output_path),
                "relative_path": output_path.name,
                "metadata": {
                    "method": "noise_injection",
                    "algorithm_key": payload.get("algorithm_key", "generation.image.noise_injection"),
                    "parameters": {
                        "noise_type": noise_type,
                        "noise_intensity": noise_intensity,
                        "salt_pepper_ratio": salt_pepper_ratio,
                        "shot_noise": shot_strength,
                        "read_noise": read_noise_sigma,
                    },
                },
                "status": "created",
            }
        )
        context.set_progress((index + 1) * 100 / target_count, f"噪声注入 {index + 1}/{target_count}")

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


def _apply_salt_pepper_noise(out, intensity: float, salt_ratio: float):
    noisy = out.copy()
    if intensity <= 0:
        return noisy

    total = noisy.shape[0] * noisy.shape[1]
    num_pixels = max(1, int(total * intensity))
    num_salt = int(num_pixels * salt_ratio)

    ys = np.random.randint(0, noisy.shape[0], size=num_pixels)
    xs = np.random.randint(0, noisy.shape[1], size=num_pixels)
    noisy[ys[:num_salt], xs[:num_salt], :] = 1.0
    noisy[ys[num_salt:], xs[num_salt:], :] = 0.0
    return noisy
