"""Audio denoise cleaning plugin. Uses spectral gating to reduce background noise."""

from pathlib import Path


PARAMETERS = [
    {
        "name": 'snr_threshold',
        "type": 'float',
        "label": '信噪比阈值(dB)',
        "default": 18.0,
        "min": 0.0,
        "max": 100.0,
        "options": [],
        "description": '低于此信噪比时触发去噪',
        "required": False,
    },
    {
        "name": 'noise_reduce_strength',
        "type": 'float',
        "label": '降噪强度',
        "default": 1.0,
        "min": 0.1,
        "max": 3.0,
        "options": [],
        "description": '频谱门控的噪声削减倍数',
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
        "description": '是否将去噪后的音频写入磁盘',
        "required": False,
    },
]


def run(payload: dict, context) -> dict:
    parameters = payload.get("parameters", {}) or {}
    samples = payload.get("input", {}).get("samples", []) or []
    output_dir = Path(payload.get("output", {}).get("output_dir", "."))
    snr_threshold = float(parameters.get("snr_threshold", 18.0))
    noise_reduce_strength = float(parameters.get("noise_reduce_strength", 1.0))
    apply_changes = bool(parameters.get("apply", True))

    if not samples:
        return {"ok": True, "suggestions": [], "logs": []}

    total = max(len(samples), 1)
    suggestions = []

    for idx, sample in enumerate(samples):
        if context.is_cancel_requested():
            return {"ok": False, "error_code": "CANCELLED", "message": "任务已取消", "details": {}}
        context.set_progress((idx + 1) * 100 / total, f"音频去噪 {idx + 1}/{total}")

        sample_path = _sample_path(sample)
        if not sample_path or not sample_path.is_file():
            continue

        result = _denoise_if_noisy(sample_path, output_dir, snr_threshold, noise_reduce_strength, apply_changes)
        if result is not None:
            suggestions.append({
                "sample_id": sample["id"],
                "issue_type": "audio_noise",
                "suggested_action": "repair",
                "confidence": result["confidence"],
                "message": f"SNR score {result['snr_score']:.1f} < threshold {snr_threshold:.1f}",
                "details": {"snr_score": result["snr_score"], "snr_threshold": snr_threshold,
                            "output_file_path": result["output_path"], "processing_result": "denoised"},
            })

    return {"ok": True, "suggestions": suggestions, "logs": []}


def _sample_path(sample: dict):
    path = sample.get("sample_path") or sample.get("path") or sample.get("file_path")
    if not path:
        return None
    return Path(path)


def _denoise_if_noisy(path: Path, output_dir: Path, snr_threshold: float,
                      strength: float, apply: bool) -> dict | None:
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
        signal_rms = float(np.sqrt(np.mean(np.square(y))) + 1e-12)
        noise_floor = float(np.percentile(np.abs(y), 10) + 1e-12)
        snr = float(20.0 * np.log10(signal_rms / noise_floor))
        if snr >= snr_threshold:
            return None

        confidence = _clamp((snr_threshold - snr) / snr_threshold)
        output_path = ""
        if apply:
            stft = librosa.stft(y)
            mag, phase = np.abs(stft), np.angle(stft)
            noise_profile = np.percentile(mag, 20, axis=1, keepdims=True)
            reduced = np.maximum(mag - noise_profile * strength, 0.0)
            cleaned = librosa.istft(reduced * np.exp(1j * phase), length=len(y))
            output_dir.mkdir(parents=True, exist_ok=True)
            out_path = output_dir / f"denoised_{path.name}"
            sf.write(str(out_path), cleaned, int(sr))
            output_path = str(out_path)
        return {"snr_score": snr, "confidence": confidence, "output_path": output_path}
    except Exception:
        return None


def _clamp(v: float) -> float:
    return round(max(0.0, min(1.0, v)), 4)
