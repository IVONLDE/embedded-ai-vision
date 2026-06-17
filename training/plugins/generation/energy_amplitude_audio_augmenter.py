from __future__ import annotations

from pathlib import Path

import numpy as np


PARAMETERS = [
    {
        "name": "volume_scale",
        "type": "float",
        "label": "音量缩放",
        "default": 1.35,
        "min": 0.0,
        "max": 5.0,
        "options": [],
        "description": "线性音量缩放系数",
        "required": False,
    },
    {
        "name": "mute_probability",
        "type": "float",
        "label": "静音触发概率",
        "default": 0.9,
        "min": 0.0,
        "max": 1.0,
        "options": [],
        "description": "每个样本插入静音段的概率",
        "required": False,
    },
    {
        "name": "mute_count",
        "type": "int",
        "label": "静音段数量",
        "default": 2,
        "min": 0,
        "max": 10,
        "options": [],
        "description": "随机插入的静音段数量",
        "required": False,
    },
    {
        "name": "min_sec",
        "type": "float",
        "label": "最短静音秒数",
        "default": 0.05,
        "min": 0.01,
        "max": 1.0,
        "options": [],
        "description": "单个静音段最短时长",
        "required": False,
    },
    {
        "name": "max_sec",
        "type": "float",
        "label": "最长静音秒数",
        "default": 0.35,
        "min": 0.05,
        "max": 2.0,
        "options": [],
        "description": "单个静音段最长时长",
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
    gain = _clamp_float(parameters.get("volume_scale", parameters.get("gain", 1.35)), 0.0, 5.0)
    mute_probability = _clamp_float(parameters.get("mute_probability", parameters.get("sil_prob", 0.9)), 0.0, 1.0)
    mute_count = _clamp_int(parameters.get("mute_count", parameters.get("sil_times", 2)), 0, 10)
    min_sec = _clamp_float(parameters.get("min_sec", parameters.get("sil_min", 0.05)), 0.01, 1.0)
    max_sec = _clamp_float(parameters.get("max_sec", parameters.get("sil_max", 0.35)), 0.05, 2.0)
    if min_sec > max_sec:
        min_sec, max_sec = max_sec, min_sec

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

        y_out = np.clip(y.astype(np.float32) * gain, -1.0, 1.0)
        if mute_count > 0 and np.random.rand() < mute_probability:
            total = len(y_out)
            for _ in range(mute_count):
                seg = int(np.random.uniform(min_sec, max_sec) * sr)
                seg = max(1, min(seg, total))
                start = int(np.random.randint(0, max(1, total - seg)))
                y_out[start:start + seg] = 0.0

        out = output_dir / f"{sp.stem}_energy_{index:04d}.wav"
        sf.write(str(out), y_out, sr)
        outputs.append(
            {
                "source_sample_id": sample.get("id"),
                "output_path": str(out),
                "relative_path": out.name,
                "metadata": {
                    "method": "energy_amplitude",
                    "volume_scale": gain,
                    "mute_probability": mute_probability,
                    "mute_count": mute_count,
                },
                "status": "created",
            }
        )
        context.set_progress((index + 1) * 100 / target_count, f"Energy/amp {index + 1}/{target_count}")

    return {"ok": True, "outputs": outputs, "logs": []}


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
