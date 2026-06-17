from __future__ import annotations

from pathlib import Path

import numpy as np


PARAMETERS = [
    {
        "name": 'freq_range',
        "type": 'string',
        "label": '频谱范围(Hz)',
        "default": '[0, 4000]',
        "min": None,
        "max": None,
        "options": [],
        "description": '频谱重构的起始和截止频率，格式 [low, high]',
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
    freq_range = parameters.get("freq_range", parameters.get("频谱范围", [0, 4000]))
    if isinstance(freq_range, (list, tuple)) and len(freq_range) >= 2:
        min_freq, max_freq = freq_range[0], freq_range[1]
    else:
        min_freq, max_freq = 0, 4000

    outputs = []
    for index in range(target_count):
        if context.is_cancel_requested():
            return {"ok": False, "error_code": "CANCELLED"}
        sample = samples[index % len(samples)]
        sp = Path(sample.get("sample_path") or sample.get("path") or sample.get("file_path") or "")
        try:
            y, sr = librosa.load(str(sp), sr=None)
        except Exception:
            continue

        D = librosa.stft(y)
        freq_bins = librosa.fft_frequencies(sr=sr)
        mask = (freq_bins >= min_freq) & (freq_bins <= max_freq)
        D_filtered = D * mask[np.newaxis, :]
        y_out = librosa.istft(D_filtered, length=len(y))

        out = output_dir / f"{sp.stem}_spectrum_{index:04d}.wav"
        try:
            sf.write(str(out), y_out, sr)
        except Exception:
            continue
        outputs.append({
            "source_sample_id": sample.get("id"),
            "output_path": str(out),
            "relative_path": out.name,
            "metadata": {"method": "spectrum_reconstruction", "freq_range": [min_freq, max_freq]},
            "status": "created",
        })
        context.set_progress((index + 1) * 100 / target_count, f"Spectrum recon {index+1}/{target_count}")

    return {"ok": True, "outputs": outputs, "logs": []}
