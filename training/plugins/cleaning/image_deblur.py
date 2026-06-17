"""Image deblur cleaning plugin. Filters out images whose blur score falls below the threshold."""

from pathlib import Path
from typing import Optional


PARAMETERS = [
    {
        "name": 'blur_threshold',
        "type": 'int',
        "label": '模糊阈值',
        "default": 100,
        "min": 1,
        "max": 1000,
        "options": [],
        "description": 'Laplacian方差低于此值时直接过滤图片',
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
        "description": '仅当模糊判定置信度不低于该值时才过滤',
        "required": False,
    },
    {
        "name": 'laplacian_ksize',
        "type": 'int',
        "label": '拉普拉斯核大小',
        "default": 3,
        "min": 1,
        "max": 7,
        "options": [],
        "description": '计算模糊分数时使用的拉普拉斯卷积核大小，必须为奇数',
        "required": False,
    },
]


def run(payload: dict, context) -> dict:
    parameters = payload.get("parameters", {}) or {}
    samples = payload.get("input", {}).get("samples", []) or []
    blur_threshold = float(parameters.get("blur_threshold", 100))
    min_confidence = float(parameters.get("min_confidence", 0.2))
    laplacian_ksize = _odd_kernel_size(parameters.get("laplacian_ksize", 3), default=3, minimum=1, maximum=7)

    if not samples:
        return {"ok": True, "suggestions": [], "logs": []}

    total = max(len(samples), 1)
    suggestions = []

    for idx, sample in enumerate(samples):
        if context.is_cancel_requested():
            return {"ok": False, "error_code": "CANCELLED", "message": "任务已取消", "details": {}}
        context.set_progress((idx + 1) * 100 / total, f"去模糊检测 {idx + 1}/{total}")

        sample_path = _sample_path(sample)
        if not sample_path or not sample_path.is_file():
            continue

        score = _blur_score(sample_path, laplacian_ksize)
        if score is None:
            continue

        if score < blur_threshold:
            confidence = _clamp(1.0 - score / max(blur_threshold, 1.0))
            if confidence < min_confidence:
                continue
            suggestions.append({
                "sample_id": sample["id"],
                "issue_type": "image_blur",
                "suggested_action": "delete",
                "confidence": confidence,
                "message": f"Laplacian blur score {score:.1f} < threshold {blur_threshold:.0f}",
                "details": {
                    "blur_score": score,
                    "blur_threshold": blur_threshold,
                    "min_confidence": min_confidence,
                    "laplacian_ksize": laplacian_ksize,
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


def _blur_score(path: Path, laplacian_ksize: int) -> Optional[float]:
    try:
        import cv2
    except Exception:
        return None
    try:
        img = _read_image(path, cv2.IMREAD_GRAYSCALE)
        if img is None:
            return None
        return float(cv2.Laplacian(img, cv2.CV_64F, ksize=laplacian_ksize).var())
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
