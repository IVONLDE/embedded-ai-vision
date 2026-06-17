from __future__ import annotations

from pathlib import Path

import numpy as np


PARAMETERS = [
    {
        "name": "downsample_ratio",
        "type": "float",
        "label": "降采样比例",
        "default": 0.6,
        "min": 0.1,
        "max": 1.0,
        "options": [],
        "description": "降采样后再升采样的比例",
        "required": False,
    },
    {
        "name": "quantize_bits",
        "type": "int",
        "label": "量化位深",
        "default": 6,
        "min": 2,
        "max": 32,
        "options": [],
        "description": "量化比特深度，越低失真越明显",
        "required": False,
    },
    {
        "name": "distortion_drive",
        "type": "float",
        "label": "失真驱动量",
        "default": 0.45,
        "min": 0.0,
        "max": 1.0,
        "options": [],
        "description": "tanh 饱和失真驱动量",
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
    ds_ratio = _clamp_float(parameters.get("downsample_ratio", parameters.get("ds_ratio", 0.6)), 0.1, 1.0)
    bits = _clamp_int(parameters.get("quantize_bits", parameters.get("bits", 6)), 2, 16)
    drive = _clamp_float(parameters.get("distortion_drive", parameters.get("drive", 0.45)), 0.0, 1.0)

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

        target_len = len(y)
        y_out = y.astype(np.float32)
        if ds_ratio < 0.999:
            new_sr = max(4000, int(sr * ds_ratio))
            y_ds = librosa.resample(y_out, orig_sr=sr, target_sr=new_sr)
            y_out = librosa.resample(y_ds, orig_sr=new_sr, target_sr=sr)
            y_out = _match_len(y_out, target_len)

        levels = float((2 ** bits) - 1)
        y_out = np.round(y_out * levels) / levels
        if drive > 0:
            drive_gain = 1.0 + drive * 8.0
            y_out = np.tanh(drive_gain * y_out) / (np.tanh(drive_gain) + 1e-6)

        out = output_dir / f"{sp.stem}_distort_{index:04d}.wav"
        sf.write(str(out), y_out, sr)
        outputs.append(
            {
                "source_sample_id": sample.get("id"),
                "output_path": str(out),
                "relative_path": out.name,
                "metadata": {
                    "method": "quality_distortion",
                    "downsample_ratio": ds_ratio,
                    "quantize_bits": bits,
                    "distortion_drive": drive,
                },
                "status": "created",
            }
        )
        context.set_progress((index + 1) * 100 / target_count, f"Distort {index + 1}/{target_count}")

    return {"ok": True, "outputs": outputs, "logs": []}


def _match_len(y, target):
    if len(y) == target:
        return y
    if len(y) > target:
        return y[:target]
    return np.pad(y, (0, target - len(y)), mode="constant")


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
