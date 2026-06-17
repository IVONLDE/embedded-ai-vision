from __future__ import annotations

from pathlib import Path

import numpy as np


PARAMETERS = [
    {
        "name": 'noise_type',
        "type": 'select',
        "label": '噪声类型',
        "default": 'white',
        "min": None,
        "max": None,
        "options": ['white', 'pink'],
        "description": 'white: 白噪声; pink: 粉红噪声',
        "required": False,
    },
    {
        "name": 'noise_intensity',
        "type": 'float',
        "label": '噪声强度',
        "default": 0.1,
        "min": 0.0,
        "max": 1.0,
        "options": [],
        "description": '噪声幅度峰值',
        "required": False,
    },
]


def run(payload: dict, context) -> dict:
    try:
        import librosa
        import soundfile as sf
    except ImportError:
        return {"ok": False, "error_code": "MISSING_DEPENDENCY", "message": "Missing librosa/soundfile"}

    parameters = payload.get("parameters", {}) or {}
    output_dir = Path(payload.get("output", {}).get("output_dir") or ".")
    output_dir.mkdir(parents=True, exist_ok=True)

    samples = payload.get("input", {}).get("samples", []) or []
    if not samples:
        return {"ok": False, "error_code": "NO_INPUT_SAMPLES"}

    target_count = max(1, int(payload.get("target_count") or len(samples)))
    noise_type = str(parameters.get("noise_type", parameters.get("噪声类型", "white")) or "white")
    noise_level = float(parameters.get("noise_level", parameters.get("噪声强度", 0.1)) or 0.1)

    outputs = []
    for index in range(target_count):
        if context.is_cancel_requested():
            return {"ok": False, "error_code": "CANCELLED", "message": "Cancelled"}
        sample = samples[index % len(samples)]
        sp = Path(sample.get("sample_path") or sample.get("path") or sample.get("file_path") or "")
        try:
            y, sr = librosa.load(str(sp), sr=None)
        except Exception:
            continue

        if noise_type == "white":
            noise = np.random.randn(len(y))
        elif noise_type == "pink":
            noise = np.random.randn(len(y))
            noise = np.cumsum(noise) / np.sqrt(np.arange(1, len(y) + 1))
        else:
            noise = np.random.randn(len(y))

        noise = noise / (np.max(np.abs(noise)) + 1e-6) * noise_level
        y_out = y + noise

        out = output_dir / f"{sp.stem}_noise_{index:04d}.wav"
        try:
            sf.write(str(out), y_out, sr)
        except Exception:
            continue
        outputs.append({
            "source_sample_id": sample.get("id"),
            "output_path": str(out),
            "relative_path": out.name,
            "metadata": {"method": "noise_injection", "noise_type": noise_type, "noise_level": noise_level},
            "status": "created",
        })
        context.set_progress((index + 1) * 100 / target_count, f"Noise injection {index+1}/{target_count}")

    return {"ok": True, "outputs": outputs, "logs": []}
