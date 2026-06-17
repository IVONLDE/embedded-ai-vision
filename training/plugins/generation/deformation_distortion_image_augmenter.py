from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from ._image_io import read_image, write_image


PARAMETERS = [
    {
        "name": 'elastic_strength',
        "type": 'float',
        "label": '弹性形变强度',
        "default": 8.0,
        "min": 0.0,
        "max": 50.0,
        "options": [],
        "description": '弹性形变位移强度',
        "required": False,
    },
    {
        "name": 'elastic_gaussian_kernel',
        "type": 'float',
        "label": '弹性高斯核',
        "default": 10.0,
        "min": 1.0,
        "max": 50.0,
        "options": [],
        "description": '弹性形变高斯平滑核大小',
        "required": False,
    },
    {
        "name": 'distortion_k1',
        "type": 'float',
        "label": '径向畸变k1',
        "default": 0.18,
        "min": -1.0,
        "max": 1.0,
        "options": [],
        "description": '径向畸变一阶系数',
        "required": False,
    },
    {
        "name": 'distortion_k2',
        "type": 'float',
        "label": '径向畸变k2',
        "default": 0.03,
        "min": -1.0,
        "max": 1.0,
        "options": [],
        "description": '径向畸变二阶系数',
        "required": False,
    },
]


def run(payload: dict, context) -> dict:
    """形变畸变增强：弹性形变与径向畸变。"""
    parameters = payload.get("parameters", {}) or {}
    output_dir = Path(payload.get("output", {}).get("output_dir") or ".")
    output_dir.mkdir(parents=True, exist_ok=True)

    samples = payload.get("input", {}).get("samples", []) or []
    if not samples:
        return {"ok": False, "error_code": "NO_INPUT_SAMPLES", "message": "未提供源样本。"}

    target_count = max(1, int(payload.get("target_count") or len(samples)))
    elastic_strength = float(parameters.get("elastic_strength", parameters.get("弹性强度", 8.0)) or 8.0)
    elastic_sigma = float(parameters.get("elastic_gaussian_kernel", parameters.get("elastic_sigma", parameters.get("弹性高斯核", 10.0))) or 10.0)
    k1 = float(parameters.get("distortion_k1", parameters.get("k1", parameters.get("畸变系数k1", 0.18))) or 0.18)
    k2 = float(parameters.get("distortion_k2", parameters.get("k2", parameters.get("畸变系数k2", 0.03))) or 0.03)

    outputs = []
    for index in range(target_count):
        if context.is_cancel_requested():
            return {"ok": False, "error_code": "CANCELLED", "message": "任务已取消"}

        sample = samples[index % len(samples)]
        source_path = Path(sample.get("sample_path") or sample.get("path") or sample.get("file_path") or "")
        img = read_image(source_path)
        if img is None:
            continue

        if len(img.shape) == 2:
            img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)

        out = img
        h, w = img.shape[:2]

        # 弹性形变
        if elastic_strength > 0:
            alpha = elastic_strength
            sigma = elastic_sigma
            dx = (np.random.rand(h, w).astype(np.float32) * 2 - 1)
            dy = (np.random.rand(h, w).astype(np.float32) * 2 - 1)
            dx = cv2.GaussianBlur(dx, (51, 51), sigma)
            dy = cv2.GaussianBlur(dy, (51, 51), sigma)
            dx = dx * alpha
            dy = dy * alpha
            x, y = np.meshgrid(np.arange(w), np.arange(h))
            map_x = (x + dx).astype(np.float32)
            map_y = (y + dy).astype(np.float32)
            out = cv2.remap(out, map_x, map_y, interpolation=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)

        # 径向畸变
        if k1 != 0.0 or k2 != 0.0:
            xs = np.linspace(-1.0, 1.0, w, dtype=np.float32)
            ys = np.linspace(-1.0, 1.0, h, dtype=np.float32)
            xv, yv = np.meshgrid(xs, ys)
            r2 = xv * xv + yv * yv
            factor = 1.0 + k1 * r2 + k2 * (r2 ** 2)
            x_dist = xv * factor
            y_dist = yv * factor
            map_x = ((x_dist + 1.0) * 0.5 * (w - 1)).astype(np.float32)
            map_y = ((y_dist + 1.0) * 0.5 * (h - 1)).astype(np.float32)
            out = cv2.remap(out, map_x, map_y, interpolation=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)

        output_path = output_dir / f"{source_path.stem}_deform_{index:04d}{source_path.suffix or '.jpg'}"
        if not write_image(output_path, out):
            return {"ok": False, "error_code": "IMAGE_WRITE_ERROR", "message": f"Cannot write image: {output_path}"}

        outputs.append({
            "source_sample_id": sample.get("id"),
            "output_path": str(output_path),
            "relative_path": output_path.name,
            "metadata": {
                "method": "deformation_distortion",
                "algorithm_key": payload.get("algorithm_key", "generation.image.deformation_distortion"),
                "parameters": {"elastic_strength": elastic_strength, "elastic_sigma": elastic_sigma, "k1": k1, "k2": k2},
            },
            "status": "created",
        })
        context.set_progress((index + 1) * 100 / target_count, f"形变畸变 {index + 1}/{target_count}")

    return {"ok": True, "outputs": outputs, "logs": []}
