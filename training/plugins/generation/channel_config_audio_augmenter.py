from __future__ import annotations

from pathlib import Path

import numpy as np


PARAMETERS = [
    {
        "name": 'target_channel',
        "type": 'select',
        "label": '目标声道',
        "default": 'auto',
        "min": None,
        "max": None,
        "options": ['auto', 'mono', 'stereo'],
        "description": '目标声道配置',
        "required": False,
    },
    {
        "name": 'mix_strategy',
        "type": 'select',
        "label": '混合策略',
        "default": 'avg',
        "min": None,
        "max": None,
        "options": ['avg', 'max', 'min'],
        "description": '多声道混合策略',
        "required": False,
    },
    {
        "name": 'dither',
        "type": 'float',
        "label": '抖动幅度',
        "default": 0.002,
        "min": 0.0,
        "max": 0.1,
        "options": [],
        "description": '声道抖动噪声幅度',
        "required": False,
    },
    {
        "name": 'swap_probability',
        "type": 'float',
        "label": '声道交换概率',
        "default": 0.2,
        "min": 0.0,
        "max": 1.0,
        "options": [],
        "description": '左右声道交换概率',
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
    target_ch = str(parameters.get("target_ch", parameters.get("目标声道", "auto")) or "auto").lower()
    mix_strat = str(parameters.get("mix_strat", parameters.get("混合策略", "avg")) or "avg").lower()
    jitter = float(parameters.get("jitter", parameters.get("立体声微抖动", 0.002)) or 0.002)
    swap_prob = float(parameters.get("swap_prob", parameters.get("左右交换概率", 0.2)) or 0.2)

    outputs = []
    for index in range(target_count):
        if context.is_cancel_requested():
            return {"ok": False, "error_code": "CANCELLED"}
        sample = samples[index % len(samples)]
        sp = Path(sample.get("sample_path") or sample.get("path") or sample.get("file_path") or "")
        try:
            y, sr = librosa.load(str(sp), sr=None, mono=False)
        except Exception:
            continue

        if y.ndim == 1:
            y = y[np.newaxis, :]
        C, T = y.shape

        ch = target_ch
        if ch == "auto":
            ch = "mono" if np.random.rand() < 0.5 else "stereo"

        if ch == "mono":
            if mix_strat == "random_weight" and C >= 2:
                w = np.random.rand(C).astype(np.float32)
                w = w / (w.sum() + 1e-6)
                y_out = np.sum(y * w[:, None], axis=0, keepdims=True)
            else:
                y_out = np.mean(y, axis=0, keepdims=True)
        elif ch == "stereo":
            if C == 1:
                ch1, ch2 = y[0], y[0] * (1.0 + np.random.uniform(-jitter, jitter))
                y_out = np.stack([ch1, ch2], axis=0)
            else:
                left, right = y[0], y[min(1, C - 1)]
                if np.random.rand() < swap_prob:
                    left, right = right, left
                y_out = np.stack([left, right], axis=0)
        else:
            y_out = y

        if y_out.ndim == 1:
            y_save = y_out
        else:
            y_save = y_out.T

        peak = float(np.max(np.abs(y_save))) if y_save.size else 0.0
        if peak > 1.0:
            y_save = y_save / (peak + 1e-6) * 0.999

        out = output_dir / f"{sp.stem}_ch_{index:04d}.wav"
        sf.write(str(out), y_save, sr)
        outputs.append({
            "source_sample_id": sample.get("id"),
            "output_path": str(out),
            "relative_path": out.name,
            "metadata": {"method": "channel_config", "target_channels": ch},
            "status": "created",
        })
        context.set_progress((index + 1) * 100 / target_count, f"Channel cfg {index+1}/{target_count}")

    return {"ok": True, "outputs": outputs, "logs": []}
