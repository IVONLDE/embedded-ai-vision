from __future__ import annotations

from pathlib import Path

import cv2

from ._image_io import read_image, write_image


PARAMETERS = [
    {
        "name": "blur_strength",
        "type": "float",
        "label": "模糊强度",
        "default": 0.0,
        "min": 0.0,
        "max": 10.0,
        "options": [],
        "description": "高斯模糊强度，0 表示不模糊",
        "required": False,
    },
    {
        "name": "blur_kernel",
        "type": "int",
        "label": "模糊核大小",
        "default": 5,
        "min": 3,
        "max": 31,
        "options": [],
        "description": "高斯模糊卷积核大小，自动调整为奇数",
        "required": False,
    },
    {
        "name": "sharpen_strength",
        "type": "float",
        "label": "锐化强度",
        "default": 1.2,
        "min": 0.0,
        "max": 5.0,
        "options": [],
        "description": "反遮罩锐化强度，默认产生明显清晰度变化",
        "required": False,
    },
    {
        "name": "sharpen_amount",
        "type": "float",
        "label": "锐化叠加比例",
        "default": 0.55,
        "min": 0.0,
        "max": 1.0,
        "options": [],
        "description": "锐化细节叠加比例",
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
    blur_strength = _clamp_float(parameters.get("blur_strength", 0.0), 0.0, 10.0)
    blur_kernel = _clamp_int(parameters.get("blur_kernel", 5), 3, 31)
    sharpen_strength = _clamp_float(parameters.get("sharpen_strength", parameters.get("sharp_strength", 1.2)), 0.0, 5.0)
    sharpen_amount = _clamp_float(parameters.get("sharpen_amount", parameters.get("sharp_amount", 0.55)), 0.0, 1.0)

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

        out = img.copy()
        if blur_strength > 0:
            kernel = blur_kernel + int(blur_strength * 2)
            kernel = max(3, min(kernel + (kernel + 1) % 2, 31))
            out = cv2.GaussianBlur(out, (kernel, kernel), sigmaX=max(0.1, blur_strength))

        if sharpen_strength > 0:
            blurred = cv2.GaussianBlur(out, (0, 0), 1.0)
            amount = sharpen_amount * sharpen_strength
            out = cv2.addWeighted(out, 1.0 + amount, blurred, -amount, 0)

        output_path = output_dir / f"{source_path.stem}_clarity_{index:04d}{source_path.suffix or '.jpg'}"
        if not write_image(output_path, out):
            return {"ok": False, "error_code": "IMAGE_WRITE_ERROR", "message": f"Cannot write image: {output_path}"}

        outputs.append(
            {
                "source_sample_id": sample.get("id"),
                "output_path": str(output_path),
                "relative_path": output_path.name,
                "metadata": {
                    "method": "clarity",
                    "algorithm_key": payload.get("algorithm_key", "generation.image.clarity"),
                    "parameters": {
                        "blur_strength": blur_strength,
                        "blur_kernel": blur_kernel,
                        "sharpen_strength": sharpen_strength,
                        "sharpen_amount": sharpen_amount,
                    },
                },
                "status": "created",
            }
        )
        context.set_progress((index + 1) * 100 / target_count, f"清晰度变换 {index + 1}/{target_count}")

    return {"ok": True, "outputs": outputs, "logs": []}


def _clamp_float(value, low, high):
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        parsed = low
    return max(low, min(parsed, high))


def _clamp_int(value, low, high):
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = low
    return max(low, min(parsed, high))
