"""Image denoise cleaning plugin. Filters out images whose noise score exceeds the threshold."""

from pathlib import Path
from typing import Optional


PARAMETERS = [
    {
        "name": 'noise_threshold',
        "type": 'float',
        "label": '噪声阈值',
        "default": 12.0,
        "min": 0.0,
        "max": 255.0,
        "options": [],
        "description": '超过此噪声强度时直接过滤图片',
        "required": False,
    },
    {
        "name": 'min_confidence',
        "type": 'float',
        "label": '最低置信度',
        "default": 0.2,
        "min": 0.0,
        "max": 1.0,
        "options": [],
        "description": '仅当噪声判定置信度不低于该值时才过滤',
        "required": False,
    },
    {
        "name": 'median_kernel_size',
        "type": 'int',
        "label": '中值核大小',
        "default": 3,
        "min": 3,
        "max": 9,
        "options": [],
        "description": '用于估计噪声分数的中值滤波核大小，必须为奇数',
        "required": False,
    },
]


def run(payload: dict, context) -> dict:
    parameters = payload.get("parameters", {}) or {}
    samples = payload.get("input", {}).get("samples", []) or []
    noise_threshold = float(parameters.get("noise_threshold", 12.0))
    min_confidence = float(parameters.get("min_confidence", 0.2))
    median_kernel_size = _odd_kernel_size(parameters.get("median_kernel_size", 3), default=3, minimum=3, maximum=9)

    if not samples:
        return {"ok": True, "suggestions": [], "logs": []}

    total = max(len(samples), 1)
    suggestions = []

    for idx, sample in enumerate(samples):
        if context.is_cancel_requested():
            return {"ok": False, "error_code": "CANCELLED", "message": "任务已取消", "details": {}}
        context.set_progress((idx + 1) * 100 / total, f"去噪检测 {idx + 1}/{total}")

        sample_path = _sample_path(sample)
        if not sample_path or not sample_path.is_file():
            continue

        score = _noise_score(sample_path, median_kernel_size)
        if score is None:
            continue

        if score > noise_threshold:
            confidence = _clamp((score - noise_threshold) / max(noise_threshold * 2.0, 1.0))
            if confidence < min_confidence:
                continue
            suggestions.append({
                "sample_id": sample["id"],
                "issue_type": "image_noise",
                "suggested_action": "delete",
                "confidence": confidence,
                "message": f"Noise score {score:.1f} > threshold {noise_threshold:.1f}",
                "details": {
                    "noise_score": score,
                    "noise_threshold": noise_threshold,
                    "min_confidence": min_confidence,
                    "median_kernel_size": median_kernel_size,
                    "sample_path": str(sample_path),
                    "processing_result": "filtered_out",
                },
            })

    return {"ok": True, "suggestions": suggestions, "logs": []}


def _sample_path(sample: dict):
    path = sample.get("sample_path") or sample.get("path") or sample.get("file_path")
    if not path:
        return None
    return Path(path)


def _noise_score(path: Path, kernel_size: int) -> Optional[float]:
    try:
        import cv2
        import numpy as np
    except Exception:
        return None
    try:
        gray = _read_image(path, cv2.IMREAD_GRAYSCALE)
        if gray is None:
            return None
        median = cv2.medianBlur(gray, kernel_size)
        return float(np.mean(np.abs(gray.astype(np.float32) - median.astype(np.float32))))
    except Exception:
        return None


def _read_image(path: Path, flags):
    try:
        import cv2
        import numpy as np
        data = np.fromfile(str(path), dtype=np.uint8)
        if data.size == 0:
            return None
        return cv2.imdecode(data, flags)
    except Exception:
        return None


def _clamp(v: float) -> float:
    return round(max(0.0, min(1.0, v)), 4)


def _odd_kernel_size(value, *, default: int, minimum: int, maximum: int) -> int:
    try:
        size = int(value)
    except Exception:
        size = default
    size = max(minimum, min(maximum, size))
    if size % 2 == 0:
        size = size + 1 if size < maximum else size - 1
    return max(minimum, min(maximum, size))
