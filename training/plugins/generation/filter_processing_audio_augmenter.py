from __future__ import annotations

from pathlib import Path

import numpy as np


PARAMETERS = [
    {
        "name": 'filter_type',
        "type": 'select',
        "label": '滤波类型',
        "default": 'bandpass',
        "min": None,
        "max": None,
        "options": ['bandpass', 'lowpass', 'highpass', 'bandstop'],
        "description": '滤波器类型',
        "required": False,
    },
    {
        "name": 'low_cutoff_hz',
        "type": 'float',
        "label": '低截止频率(Hz)',
        "default": 300.0,
        "min": 20.0,
        "max": 20000.0,
        "options": [],
        "description": '低端截止频率',
        "required": False,
    },
    {
        "name": 'high_cutoff_hz',
        "type": 'float',
        "label": '高截止频率(Hz)',
        "default": 3000.0,
        "min": 20.0,
        "max": 20000.0,
        "options": [],
        "description": '高端截止频率',
        "required": False,
    },
]


def run(payload: dict, context) -> dict:
    try:
        import librosa
        import soundfile as sf
    except ImportError:
        return {"ok": False, "error_code": "MISSING_DEPENDENCY"}

    parameters = payload.get("parameters", {}) or {}
    output_dir = Path(payload.get("output", {}).get("output_dir") or ".")
    output_dir.mkdir(parents=True, exist_ok=True)

    samples = payload.get("input", {}).get("samples", []) or []
    if not samples:
        return {"ok": False, "error_code": "NO_INPUT_SAMPLES"}

    target_count = max(1, int(payload.get("target_count") or len(samples)))
    ft = str(parameters.get("ft", parameters.get("滤波类型", "bandpass")) or "bandpass").lower()
    low = float(parameters.get("low", parameters.get("低截止频率Hz", 300.0)) or 300.0)
    high = float(parameters.get("high", parameters.get("高截止频率Hz", 3000.0)) or 3000.0)
    if low > high:
        low, high = high, low

    outputs = []
    for index in range(target_count):
        if context.is_cancel_requested():
            return {"ok": False, "error_code": "CANCELLED"}
        sample = samples[index % len(samples)]
        sp = Path(sample.get("sample_path") or sample.get("path") or sample.get("file_path") or "")
        try:
            y, sr = librosa.load(str(sp), sr=None, mono=True)
        except Exception:
            continue
        T, n = len(y), len(y)
        Y = np.fft.rfft(y)
        freqs = np.fft.rfftfreq(n, d=1.0 / sr)
        mask = np.ones_like(Y, dtype=np.float32)
        if ft == "lowpass":
            mask[freqs > high] = 0.0
        elif ft == "highpass":
            mask[freqs < low] = 0.0
        elif ft == "bandstop":
            mask[(freqs >= low) & (freqs <= high)] = 0.0
        else:
            mask[(freqs < low) | (freqs > high)] = 0.0
        ya = np.fft.irfft(Y * mask, n=n)
        ya = _match_len(ya, T)

        out = output_dir / f"{sp.stem}_filter_{index:04d}.wav"
        sf.write(str(out), ya, sr)
        outputs.append({
            "source_sample_id": sample.get("id"),
            "output_path": str(out),
            "relative_path": out.name,
            "metadata": {"method": "filter_processing", "filter_type": ft},
            "status": "created",
        })
        context.set_progress((index + 1) * 100 / target_count, f"Filter {index+1}/{target_count}")

    return {"ok": True, "outputs": outputs, "logs": []}


def _match_len(y, target):
    if len(y) == target:
        return y
    if len(y) > target:
        return y[:target]
    return np.pad(y, (0, target - len(y)), mode="constant")
