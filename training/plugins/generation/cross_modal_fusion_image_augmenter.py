from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from ._image_io import read_image, write_image


PARAMETERS = [
    {
        "name": 'clahe_clip',
        "type": 'float',
        "label": 'CLAHE剪切限制',
        "default": 2.0,
        "min": 0.0,
        "max": 10.0,
        "options": [],
        "description": '限制对比度自适应直方图均衡化的剪切阈值',
        "required": False,
    },
    {
        "name": 'ir_weight',
        "type": 'float',
        "label": '红外权重',
        "default": 0.5,
        "min": 0.0,
        "max": 1.0,
        "options": [],
        "description": '伪红外通道融合权重',
        "required": False,
    },
]


def run(payload: dict, context) -> dict:
    """跨模态融合增强：单张图生成伪红外，融合到可见光亮度通道。

    说明：当前增强框架一次只传入单张图，因此退化为"伪融合"。
    生成伪 IR（CLAHE 增强的灰度图），在 HSV 的 V 通道上与可见光加权融合。
    """
    parameters = payload.get("parameters", {}) or {}
    output_dir = Path(payload.get("output", {}).get("output_dir") or ".")
    output_dir.mkdir(parents=True, exist_ok=True)

    samples = payload.get("input", {}).get("samples", []) or []
    if not samples:
        return {"ok": False, "error_code": "NO_INPUT_SAMPLES", "message": "未提供源样本。"}

    target_count = max(1, int(payload.get("target_count") or len(samples)))
    clahe_clip = float(parameters.get("clahe_clip", parameters.get("CLAHE剪切值", 2.0)) or 2.0)
    ir_weight = float(parameters.get("ir_weight", parameters.get("融合权重IR", 0.5)) or 0.5)
    ir_weight = max(0.0, min(ir_weight, 1.0))

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

        # 生成伪红外：灰度 + CLAHE + 归一化
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        clahe = cv2.createCLAHE(clipLimit=max(0.1, clahe_clip), tileGridSize=(8, 8))
        ir = clahe.apply(gray).astype(np.float32)
        ir = (ir - ir.min()) / (ir.max() - ir.min() + 1e-6)

        # 在 HSV 的 V 通道上融合
        vis_hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV).astype(np.float32)
        v = vis_hsv[..., 2] / 255.0
        v_new = (1.0 - ir_weight) * v + ir_weight * ir
        vis_hsv[..., 2] = np.clip(v_new * 255.0, 0, 255)
        out = cv2.cvtColor(vis_hsv.astype(np.uint8), cv2.COLOR_HSV2BGR)

        output_path = output_dir / f"{source_path.stem}_fusion_{index:04d}{source_path.suffix or '.jpg'}"
        if not write_image(output_path, out):
            return {"ok": False, "error_code": "IMAGE_WRITE_ERROR", "message": f"Cannot write image: {output_path}"}

        outputs.append({
            "source_sample_id": sample.get("id"),
            "output_path": str(output_path),
            "relative_path": output_path.name,
            "metadata": {
                "method": "cross_modal_fusion",
                "algorithm_key": payload.get("algorithm_key", "generation.image.cross_modal_fusion"),
                "parameters": {"clahe_clip": clahe_clip, "ir_weight": ir_weight},
            },
            "status": "created",
        })
        context.set_progress((index + 1) * 100 / target_count, f"跨模态融合 {index + 1}/{target_count}")

    return {"ok": True, "outputs": outputs, "logs": []}
