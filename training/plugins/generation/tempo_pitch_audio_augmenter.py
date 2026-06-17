from __future__ import annotations

from pathlib import Path

import numpy as np


PARAMETERS = [
    {
        "name": "rate",
        "type": "float",
        "label": "时间拉伸速率",
        "default": 1.15,
        "min": 0.5,
        "max": 2.0,
        "options": [],
        "description": "语速拉伸系数，>1 变快，<1 变慢",
        "required": False,
    },
    {
        "name": "n_steps",
        "type": "float",
        "label": "音高半音偏移",
        "default": 2.0,
        "min": -12.0,
        "max": 12.0,
        "options": [],
        "description": "半音偏移量，正值升调",
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
    rate = _clamp_float(parameters.get("rate", 1.15), 0.5, 2.0)
    n_steps = _clamp_float(parameters.get("n_steps", 2.0), -12.0, 12.0)

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

        y_out = y.copy()
        if rate > 0 and abs(rate - 1.0) > 1e-6:
            y_out = librosa.effects.time_stretch(y_out, rate=rate)
            y_out = _match_len(y_out, target_len)
        if abs(n_steps) > 1e-6:
            y_out = librosa.effects.pitch_shift(y_out, sr=sr, n_steps=n_steps)
            y_out = _match_len(y_out, target_len)

        out = output_dir / f"{sp.stem}_tempo_{index:04d}.wav"
        sf.write(str(out), y_out, sr)
        outputs.append(
            {
                "source_sample_id": sample.get("id"),
                "output_path": str(out),
                "relative_path": out.name,
                "metadata": {"method": "tempo_pitch", "rate": rate, "n_steps": n_steps},
                "status": "created",
            }
        )
        context.set_progress((index + 1) * 100 / target_count, f"Tempo/pitch {index + 1}/{target_count}")

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
