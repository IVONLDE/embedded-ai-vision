from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np


PARAMETERS = [
    {
        "name": 'rotation_degrees',
        "type": 'float',
        "label": '旋转角度',
        "default": 15.0,
        "min": -360.0,
        "max": 360.0,
        "options": [],
        "description": '围绕图像中心旋转的角度',
        "required": False,
    },
    {
        "name": 'scale',
        "type": 'float',
        "label": '缩放比例',
        "default": 0.92,
        "min": 0.1,
        "max": 5.0,
        "options": [],
        "description": '几何变换缩放比例',
        "required": False,
    },
    {
        "name": 'translate_x_pct',
        "type": 'float',
        "label": '水平平移百分比',
        "default": 6.0,
        "min": -100.0,
        "max": 100.0,
        "options": [],
        "description": '相对图像宽度的水平平移百分比',
        "required": False,
    },
    {
        "name": 'translate_y_pct',
        "type": 'float',
        "label": '垂直平移百分比',
        "default": -4.0,
        "min": -100.0,
        "max": 100.0,
        "options": [],
        "description": '相对图像高度的垂直平移百分比',
        "required": False,
    },
    {
        "name": 'flip_horizontal',
        "type": 'bool',
        "label": '水平翻转',
        "default": False,
        "min": None,
        "max": None,
        "options": [],
        "description": '是否执行水平翻转',
        "required": False,
    },
    {
        "name": 'flip_vertical',
        "type": 'bool',
        "label": '垂直翻转',
        "default": False,
        "min": None,
        "max": None,
        "options": [],
        "description": '是否执行垂直翻转',
        "required": False,
    },
    {
        "name": 'border_value',
        "type": 'int',
        "label": '边界填充值',
        "default": 0,
        "min": 0,
        "max": 255,
        "options": [],
        "description": '仿射变换边界填充像素值',
        "required": False,
    },
]


def run(payload: dict, context) -> dict:
    parameters = payload.get("parameters", {}) or {}
    output_dir = Path(payload.get("output", {}).get("output_dir") or ".")
    output_dir.mkdir(parents=True, exist_ok=True)

    samples = payload.get("input", {}).get("samples", []) or []
    if not samples:
        return {"ok": False, "error_code": "NO_INPUT_SAMPLES", "message": "No source samples provided."}

    target_count = max(1, int(payload.get("target_count") or parameters.get("target_count") or len(samples)))
    rotation = float(parameters.get("rotation_degrees", parameters.get("angle", 15.0)) or 15.0)
    scale = float(parameters.get("scale", 0.92) or 0.92)
    translate_x_pct = float(parameters.get("translate_x_pct", 6.0) or 6.0)
    translate_y_pct = float(parameters.get("translate_y_pct", -4.0) or -4.0)
    flip_horizontal = _as_bool(parameters.get("flip_horizontal", False))
    flip_vertical = _as_bool(parameters.get("flip_vertical", False))
    border_value = int(parameters.get("border_value", 0) or 0)

    outputs = []
    for index in range(target_count):
        if context.is_cancel_requested():
            return {"ok": False, "error_code": "CANCELLED", "message": "Generation cancelled."}

        sample = samples[index % len(samples)]
        source_path = Path(sample.get("sample_path") or sample.get("path") or sample.get("file_path") or "")
        image = _read_image(source_path)
        if image is None:
            return {"ok": False, "error_code": "IMAGE_READ_ERROR", "message": f"Cannot read image: {source_path}"}

        augmented = _transform_image(
            image,
            rotation_degrees=rotation,
            scale=scale,
            translate_x_pct=translate_x_pct,
            translate_y_pct=translate_y_pct,
            flip_horizontal=flip_horizontal,
            flip_vertical=flip_vertical,
            border_value=border_value,
        )
        output_path = output_dir / f"{source_path.stem}_geo_{index:04d}{source_path.suffix or '.jpg'}"
        if not _write_image(output_path, augmented):
            return {"ok": False, "error_code": "IMAGE_WRITE_ERROR", "message": f"Cannot write image: {output_path}"}

        metadata = {
            "method": "geometric_transform",
            "algorithm_key": payload.get("algorithm_key", "generation.image.geometric_transform"),
            "source_sample_id": sample.get("id"),
            "source_sample_path": str(source_path),
            "augmented_sample_path": str(output_path),
            "parameters": {
                "rotation_degrees": rotation,
                "scale": scale,
                "translate_x_pct": translate_x_pct,
                "translate_y_pct": translate_y_pct,
                "flip_horizontal": flip_horizontal,
                "flip_vertical": flip_vertical,
                "border_value": border_value,
            },
        }
        outputs.append(
            {
                "source_sample_id": sample.get("id"),
                "output_path": str(output_path),
                "relative_path": output_path.name,
                "metadata": metadata,
                "status": "created",
            }
        )
        context.set_progress((index + 1) * 100 / target_count, f"generated {index + 1}/{target_count}")

    return {"ok": True, "outputs": outputs, "logs": []}


def _transform_image(
    image,
    *,
    rotation_degrees: float,
    scale: float,
    translate_x_pct: float,
    translate_y_pct: float,
    flip_horizontal: bool,
    flip_vertical: bool,
    border_value: int,
):
    height, width = image.shape[:2]
    center = (width / 2.0, height / 2.0)
    matrix = cv2.getRotationMatrix2D(center, rotation_degrees, scale)
    matrix[0, 2] += width * translate_x_pct / 100.0
    matrix[1, 2] += height * translate_y_pct / 100.0
    transformed = cv2.warpAffine(
        image,
        matrix,
        (width, height),
        flags=cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=_border_value_for(image, border_value),
    )
    if flip_horizontal and flip_vertical:
        transformed = cv2.flip(transformed, -1)
    elif flip_horizontal:
        transformed = cv2.flip(transformed, 1)
    elif flip_vertical:
        transformed = cv2.flip(transformed, 0)
    return transformed


def _border_value_for(image, value: int):
    channels = 1 if len(image.shape) == 2 else image.shape[2]
    if channels == 1:
        return value
    return tuple([value] * channels)


def _as_bool(value) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "y", "是"}


def _read_image(path: Path):
    data = np.frombuffer(path.read_bytes(), dtype=np.uint8)
    return cv2.imdecode(data, cv2.IMREAD_UNCHANGED)


def _write_image(path: Path, image) -> bool:
    ext = path.suffix or ".jpg"
    ok, encoded = cv2.imencode(ext, image)
    if not ok:
        return False
    path.write_bytes(encoded.tobytes())
    return True
