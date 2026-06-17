"""Audio silence removal plugin. Strips silent segments using librosa.effects.split."""

from pathlib import Path


PARAMETERS = [
    {
        "name": 'top_db',
        "type": 'int',
        "label": '静音阈值(dB)',
        "default": 30,
        "min": 10,
        "max": 80,
        "options": [],
        "description": '低于此分贝值的片段视为静音',
        "required": False,
    },
    {
        "name": 'silence_ratio_threshold',
        "type": 'float',
        "label": '静音比例阈值',
        "default": 0.2,
        "min": 0.0,
        "max": 1.0,
        "options": [],
        "description": '静音片段占比超过此值时触发修剪',
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
        "description": '是否将修剪后的音频写入磁盘',
        "required": False,
    },
]


def run(payload: dict, context) -> dict:
    parameters = payload.get("parameters", {}) or {}
    samples = payload.get("input", {}).get("samples", []) or []
    output_dir = Path(payload.get("output", {}).get("output_dir", "."))
    top_db = int(parameters.get("top_db", 30))
    silence_ratio_threshold = float(parameters.get("silence_ratio_threshold", 0.2))
    apply_changes = bool(parameters.get("apply", True))

    if not samples:
        return {"ok": True, "suggestions": [], "logs": []}

    total = max(len(samples), 1)
    suggestions = []

    for idx, sample in enumerate(samples):
        if context.is_cancel_requested():
            return {"ok": False, "error_code": "CANCELLED", "message": "任务已取消", "details": {}}
        context.set_progress((idx + 1) * 100 / total, f"静音检测 {idx + 1}/{total}")

        sample_path = _sample_path(sample)
        if not sample_path or not sample_path.is_file():
            continue

        result = _trim_if_silent(sample_path, output_dir, top_db, silence_ratio_threshold, apply_changes)
        if result is not None:
            if result.get("error_code"):
                suggestions.append({
                    "sample_id": sample["id"],
                    "issue_type": "audio_decode_failed",
                    "suggested_action": "manual_review",
                    "confidence": 1.0,
                    "message": result["message"],
                    "details": {
                        "error_code": result["error_code"],
                        "sample_path": str(sample_path),
                        "processing_result": "audio_decode_failed",
                    },
                })
                continue
            suggestions.append({
                "sample_id": sample["id"],
                "issue_type": "audio_silence",
                "suggested_action": "repair",
                "confidence": result["confidence"],
                "message": f"Silence ratio {result['silence_ratio']:.2f} exceeds threshold {silence_ratio_threshold:.2f}",
                "details": {"silence_ratio": result["silence_ratio"], "top_db": top_db,
                            "output_file_path": result["output_path"], "processing_result": "silence_trimmed"},
            })

    return {"ok": True, "suggestions": suggestions, "logs": []}


def _sample_path(sample: dict):
    path = sample.get("sample_path") or sample.get("path") or sample.get("file_path")
    if not path:
        return None
    return Path(path)


def _trim_if_silent(path: Path, output_dir: Path, top_db: int,
                    silence_ratio_threshold: float, apply: bool) -> dict | None:
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
        intervals = librosa.effects.split(y, top_db=top_db)
        if intervals.size == 0:
            return None
        voiced_samples = int(sum(end - start for start, end in intervals))
        silence_ratio = 1.0 - voiced_samples / max(len(y), 1)
        if silence_ratio <= silence_ratio_threshold:
            return None

        confidence = _clamp(silence_ratio)
        output_path = ""
        if apply:
            cleaned = np.concatenate([y[start:end] for start, end in intervals])
            output_dir.mkdir(parents=True, exist_ok=True)
            out_path = output_dir / f"trimmed_{path.name}"
            sf.write(str(out_path), cleaned, int(sr))
            output_path = str(out_path)
        return {"silence_ratio": silence_ratio, "confidence": confidence, "output_path": output_path}
    except Exception as exc:
        return {
            "error_code": "AUDIO_DECODE_FAILED",
            "message": f"无法读取音频文件，请先转换为 wav/flac/ogg 等可解码格式后再清洗: {exc}",
        }


def _clamp(v: float) -> float:
    return round(max(0.0, min(1.0, v)), 4)
