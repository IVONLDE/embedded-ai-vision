from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from ._image_io import read_image, write_image


PARAMETERS = [
    {
        "name": 'shuffle',
        "type": 'bool',
        "label": '通道混洗',
        "default": True,
        "min": None,
        "max": None,
        "options": [],
        "description": '是否随机混洗颜色通道顺序',
        "required": False,
    },
]


def run(payload: dict, context) -> dict:
    """通道混洗增强：随机打乱 BGR 通道顺序，减少对特定通道的过拟合。"""
    parameters = payload.get("parameters", {}) or {}
    output_dir = Path(payload.get("output", {}).get("output_dir") or ".")
    output_dir.mkdir(parents=True, exist_ok=True)

    samples = payload.get("input", {}).get("samples", []) or []
    if not samples:
        return {"ok": False, "error_code": "NO_INPUT_SAMPLES", "message": "未提供源样本。"}

    target_count = max(1, int(payload.get("target_count") or len(samples)))
    do_shuffle = _as_bool(parameters.get("do_shuffle", parameters.get("是否混洗", True)))

    if not do_shuffle:
        return {"ok": True, "outputs": [], "logs": ["通道混洗已禁用，未生成输出。"], "message": "通道混洗开关关闭"}

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

        # cv2 读入为 BGR，随机排列通道顺序
        perm = np.random.permutation(3)
        augmented = img[:, :, perm].copy()

        output_path = output_dir / f"{source_path.stem}_channel_{index:04d}{source_path.suffix or '.jpg'}"
        if not write_image(output_path, augmented):
            return {"ok": False, "error_code": "IMAGE_WRITE_ERROR", "message": f"Cannot write image: {output_path}"}

        outputs.append({
            "source_sample_id": sample.get("id"),
            "output_path": str(output_path),
            "relative_path": output_path.name,
            "metadata": {
                "method": "channel_shuffle",
                "algorithm_key": payload.get("algorithm_key", "generation.image.channel_shuffle"),
                "parameters": {"do_shuffle": do_shuffle},
            },
            "status": "created",
        })
        context.set_progress((index + 1) * 100 / target_count, f"通道混洗 {index + 1}/{target_count}")

    return {"ok": True, "outputs": outputs, "logs": []}


def _as_bool(value) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "y", "是"}
