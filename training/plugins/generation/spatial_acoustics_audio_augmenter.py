from __future__ import annotations

from pathlib import Path

import numpy as np


PARAMETERS = [
    {
        "name": 'effect_type',
        "type": 'select',
        "label": '效果类型',
        "default": 'echo',
        "min": None,
        "max": None,
        "options": ['echo', 'reverb', 'both'],
        "description": '空间声学效果类型',
        "required": False,
    },
    {
        "name": 'probability',
        "type": 'float',
        "label": '触发概率',
        "default": 0.8,
        "min": 0.0,
        "max": 1.0,
        "options": [],
        "description": '效果作用概率',
        "required": False,
    },
    {
        "name": 'count',
        "type": 'int',
        "label": '回声次数',
        "default": 3,
        "min": 1,
        "max": 10,
        "options": [],
        "description": '回声重复次数',
        "required": False,
    },
    {
        "name": 'delay',
        "type": 'float',
        "label": '延迟(秒)',
        "default": 0.3,
        "min": 0.05,
        "max": 2.0,
        "options": [],
        "description": '回声/混响延迟时间',
        "required": False,
    },
    {
        "name": 'decay',
        "type": 'float',
        "label": '衰减系数',
        "default": 0.6,
        "min": 0.0,
        "max": 1.0,
        "options": [],
        "description": '回声/混响衰减系数',
        "required": False,
    },
    {
        "name": 'tau',
        "type": 'float',
        "label": '混响时间常数',
        "default": 0.5,
        "min": 0.1,
        "max": 5.0,
        "options": [],
        "description": '指数衰减混响的时间常数',
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
    echo_prob = float(parameters.get("echo_prob", parameters.get("回声概率", 0.5)) or 0.5)
    num_echoes = max(1, int(parameters.get("num_echoes", parameters.get("回声次数", 3)) or 3))
    min_delay = float(parameters.get("min_delay", parameters.get("最小回声延迟秒", 0.02)) or 0.02)
    max_delay = float(parameters.get("max_delay", parameters.get("最大回声延迟秒", 0.08)) or 0.08)
    echo_decay = float(parameters.get("echo_decay", parameters.get("回声衰减系数", 0.5)) or 0.5)
    reverb_prob = max(0.0, min(float(parameters.get("reverb_prob", parameters.get("混响概率", 0.5)) or 0.5), 1.0))
    reverb_dur = float(parameters.get("reverb_dur", parameters.get("混响持续秒", 0.6)) or 0.6)
    reverb_tau = float(parameters.get("reverb_tau", parameters.get("混响衰减tau", 0.2)) or 0.2)

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
        ya = y.copy().astype(np.float32)

        if np.random.rand() < echo_prob:
            for k in range(num_echoes):
                delay = int(np.random.uniform(min_delay, max_delay) * sr)
                if delay <= 0:
                    continue
                decay = echo_decay ** k
                delayed = np.zeros_like(ya)
                if delay < T:
                    delayed[delay:] = ya[:T - delay]
                ya = ya + decay * delayed

        if np.random.rand() < reverb_prob:
            L = int(max(1, reverb_dur * sr))
            t_arr = np.arange(L, dtype=np.float32) / sr
            ir = np.random.randn(L).astype(np.float32) * np.exp(-t_arr / (reverb_tau + 1e-6))
            y_conv = np.convolve(ya, ir, mode="full")
            ya = y_conv[:T]

        out = output_dir / f"{sp.stem}_spatial_{index:04d}.wav"
        sf.write(str(out), ya, sr)
        outputs.append({
            "source_sample_id": sample.get("id"),
            "output_path": str(out),
            "relative_path": out.name,
            "metadata": {"method": "spatial_acoustics"},
            "status": "created",
        })
        context.set_progress((index + 1) * 100 / target_count, f"Spatial {index+1}/{target_count}")

    return {"ok": True, "outputs": outputs, "logs": []}
