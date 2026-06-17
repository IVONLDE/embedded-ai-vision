from __future__ import annotations

from pathlib import Path

import numpy as np


PARAMETERS = [
    {
        "name": 'mel_bins',
        "type": 'int',
        "label": 'Mel频带数',
        "default": 64,
        "min": 16,
        "max": 256,
        "options": [],
        "description": 'Mel频谱频带数量',
        "required": False,
    },
    {
        "name": 'n_fft',
        "type": 'int',
        "label": 'FFT点数',
        "default": 1024,
        "min": 256,
        "max": 4096,
        "options": [],
        "description": 'STFT的FFT窗口大小',
        "required": False,
    },
    {
        "name": 'hop',
        "type": 'int',
        "label": '帧移',
        "default": 256,
        "min": 64,
        "max": 1024,
        "options": [],
        "description": 'STFT帧移',
        "required": False,
    },
    {
        "name": 'freq_mask_param',
        "type": 'int',
        "label": '频率掩码宽度',
        "default": 8,
        "min": 1,
        "max": 32,
        "options": [],
        "description": '频率维度掩码的最大宽度',
        "required": False,
    },
    {
        "name": 'time_mask_param',
        "type": 'int',
        "label": '时间掩码宽度',
        "default": 8,
        "min": 1,
        "max": 32,
        "options": [],
        "description": '时间维度掩码的最大宽度',
        "required": False,
    },
    {
        "name": 'inversion_iterations',
        "type": 'int',
        "label": '反演迭代次数',
        "default": 16,
        "min": 1,
        "max": 100,
        "options": [],
        "description": 'Griffin-Lim迭代次数',
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
    n_mels = int(parameters.get("n_mels", parameters.get("mel_bins", 64)) or 64)
    n_fft = int(parameters.get("n_fft", 1024) or 1024)
    hop = int(parameters.get("hop_length", 256) or 256)
    freq_mask = int(parameters.get("freq_mask", parameters.get("频谱遮挡最大宽度", 10)) or 10)
    time_mask = int(parameters.get("time_mask", parameters.get("时间遮挡最大长度", 20)) or 20)
    n_freq = int(parameters.get("n_freq", parameters.get("频谱遮挡次数", 1)) or 1)
    n_time = int(parameters.get("n_time", parameters.get("时间遮挡次数", 1)) or 1)
    n_iter = int(parameters.get("n_iter", parameters.get("反演迭代次数", 16)) or 16)

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
        T = len(y)

        S = librosa.feature.melspectrogram(y=y, sr=sr, n_fft=n_fft, hop_length=hop, n_mels=n_mels, power=2.0)
        Sm = S.copy()

        for _ in range(max(0, n_freq)):
            f = int(np.random.uniform(0, max(1, freq_mask)))
            if f <= 0:
                continue
            f0 = int(np.random.randint(0, max(1, n_mels - f + 1)))
            Sm[f0:f0 + f, :] = 0.0

        tframes = Sm.shape[-1]
        for _ in range(max(0, n_time)):
            t = int(np.random.uniform(0, max(1, time_mask)))
            if t <= 0:
                continue
            t0 = int(np.random.randint(0, max(1, tframes - t + 1)))
            Sm[:, t0:t0 + t] = 0.0

        ya = librosa.feature.inverse.mel_to_audio(Sm, sr=sr, n_fft=n_fft, hop_length=hop, power=2.0, n_iter=n_iter)
        ya = _match_len(ya, T)

        out = output_dir / f"{sp.stem}_specaug_{index:04d}.wav"
        sf.write(str(out), ya, sr)
        outputs.append({
            "source_sample_id": sample.get("id"),
            "output_path": str(out),
            "relative_path": out.name,
            "metadata": {"method": "specaugment"},
            "status": "created",
        })
        context.set_progress((index + 1) * 100 / target_count, f"SpecAugment {index+1}/{target_count}")

    return {"ok": True, "outputs": outputs, "logs": []}


def _match_len(y, target):
    if len(y) == target:
        return y
    if len(y) > target:
        return y[:target]
    return np.pad(y, (0, target - len(y)), mode="constant")
