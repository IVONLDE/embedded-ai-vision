"""Audio normalize cleaning plugin. Adjusts peak amplitude to a target level."""

from pathlib import Path


PARAMETERS = [
    {
        "name": 'target_peak',
        "type": 'float',
        "label": '目标峰值幅度',
        "default": 0.95,
        "min": 0.1,
        "max": 1.0,
        "options": [],
        "description": '标准化后的音频峰值幅度',
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
        "description": '是否将标准化后的音频写入磁盘',
        "required": False,
    },
]


def run(payload: dict, context) -> dict:
    parameters = payload.get("parameters", {}) or {}
    samples = payload.get("input", {}).get("samples", []) or []
    output_dir = Path(payload.get("output", {}).get("output_dir", "."))
    target_peak = float(parameters.get("target_peak", 0.95))
    apply_changes = bool(parameters.get("apply", True))

    if not samples:
        return {"ok": True, "suggestions": [], "logs": []}

    total = max(len(samples), 1)
    suggestions = []

    for idx, sample in enumerate(samples):
        if context.is_cancel_requested():
            return {"ok": False, "error_code": "CANCELLED", "message": "任务已取消", "details": {}}
        context.set_progress((idx + 1) * 100 / total, f"音频标准化 {idx + 1}/{total}")

        sample_path = _sample_path(sample)
        if not sample_path or not sample_path.is_file():
            continue

        result = _normalize_if_needed(sample_path, output_dir, target_peak, apply_changes)
        if result is not None:
            suggestions.append({
                "sample_id": sample["id"],
                "issue_type": "audio_level",
                "suggested_action": "repair",
                "confidence": result["confidence"],
                "message": f"Peak {result['peak']:.3f} outside target range (target {target_peak:.3f})",
                "details": {"peak": result["peak"], "target_peak": target_peak,
                            "output_file_path": result["output_path"], "processing_result": "normalized"},
            })

    return {"ok": True, "suggestions": suggestions, "logs": []}


def _sample_path(sample: dict):
    path = sample.get("sample_path") or sample.get("path") or sample.get("file_path")
    if not path:
        return None
    return Path(path)


def _normalize_if_needed(path: Path, output_dir: Path, target_peak: float,
                         apply: bool) -> dict | None:
    try:
        import numpy as np
        import librosa
        import soundfile as sf
    except Exception:
        return None
    try:
        y, sr = librosa.load(str(path), sr=None, mono=True)
        if y.size == 0:
            return None
        peak = float(np.max(np.abs(y)) + 1e-12)
        if 0.5 <= peak <= 0.99:
            return None

        confidence = _clamp(abs(target_peak - peak) / max(target_peak, 1e-6))
        output_path = ""
        if apply:
            cleaned = y / peak * target_peak
            output_dir.mkdir(parents=True, exist_ok=True)
            out_path = output_dir / f"normalized_{path.name}"
            sf.write(str(out_path), cleaned, int(sr))
            output_path = str(out_path)
        return {"peak": peak, "confidence": confidence, "output_path": output_path}
    except Exception:
        return None


def _clamp(v: float) -> float:
    return round(max(0.0, min(1.0, v)), 4)
