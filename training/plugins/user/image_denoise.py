"""Image denoise cleaning plugin. Estimates noise via median blur difference, denoises with fastNlMeansDenoisingColored."""

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
        "description": '超过此噪声强度时触发去噪',
        "required": False,
    },
    {
        "name": 'denoise_strength',
        "type": 'int',
        "label": '去噪强度',
        "default": 10,
        "min": 3,
        "max": 30,
        "options": [],
        "description": 'fastNlMeansDenoisingColored的h参数，值越大去噪越强',
        "required": False,
    },
    {
        "name": 'apply',
        "type": 'bool',
        "label": '写入修复结果',
        "default": True,
        "min": None,
        "max": None,
        "options": [],
        "description": '是否将去噪后的图像写入磁盘',
        "required": False,
    },
]


def run(payload: dict, context) -> dict:
    parameters = payload.get("parameters", {}) or {}
    samples = payload.get("input", {}).get("samples", []) or []
    output_dir = Path(payload.get("output", {}).get("output_dir", "."))
    noise_threshold = float(parameters.get("noise_threshold", 12.0))
    denoise_strength = int(parameters.get("denoise_strength", 10))
    apply_changes = bool(parameters.get("apply", True))

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

        score = _noise_score(sample_path)
        if score is None:
            continue

        if score > noise_threshold:
            confidence = _clamp((score - noise_threshold) / max(noise_threshold * 2.0, 1.0))
            output_path = ""
            if apply_changes:
                output_path = _denoise_and_save(sample_path, output_dir, denoise_strength)
            suggestions.append({
                "sample_id": sample["id"],
                "issue_type": "image_noise",
                "suggested_action": "repair",
                "confidence": confidence,
                "message": f"Noise score {score:.1f} > threshold {noise_threshold:.1f}",
                "details": {"noise_score": score, "noise_threshold": noise_threshold,
                            "denoise_strength": denoise_strength,
                            "output_file_path": output_path, "processing_result": "denoised"},
            })

    return {"ok": True, "suggestions": suggestions, "logs": []}


def _sample_path(sample: dict):
    path = sample.get("sample_path") or sample.get("path") or sample.get("file_path")
    if not path:
        return None
    return Path(path)


def _noise_score(path: Path) -> Optional[float]:
    try:
        import cv2
        import numpy as np
    except Exception:
        return None
    try:
        gray = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
        if gray is None:
            return None
        median = cv2.medianBlur(gray, 3)
        return float(np.mean(np.abs(gray.astype(np.float32) - median.astype(np.float32))))
    except Exception:
        return None


def _denoise_and_save(path: Path, output_dir: Path, strength: int) -> str:
    try:
        import cv2
    except Exception:
        return ""
    try:
        img = cv2.imread(str(path))
        if img is None:
            return ""
        h = max(3, min(strength, 30))
        cleaned = cv2.fastNlMeansDenoisingColored(img, None, h, h, 7, 21)
        output_dir.mkdir(parents=True, exist_ok=True)
        out_path = output_dir / f"denoised_{path.name}"
        cv2.imwrite(str(out_path), cleaned)
        return str(out_path)
    except Exception:
        return ""


def _clamp(v: float) -> float:
    return round(max(0.0, min(1.0, v)), 4)
