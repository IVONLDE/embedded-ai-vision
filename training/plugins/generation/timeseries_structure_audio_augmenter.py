from __future__ import annotations

from pathlib import Path

import numpy as np


PARAMETERS = [
    {
        "name": 'operation',
        "type": 'select',
        "label": '操作类型',
        "default": 'mix',
        "min": None,
        "max": None,
        "options": ['mix', 'shift', 'crop', 'concat', 'reverse'],
        "description": '时序变换操作类型',
        "required": False,
    },
    {
        "name": 'shift_sec',
        "type": 'float',
        "label": '偏移量(秒)',
        "default": 0.2,
        "min": 0.01,
        "max": 5.0,
        "options": [],
        "description": '时间偏移量',
        "required": False,
    },
    {
        "name": 'crop_ratio',
        "type": 'float',
        "label": '裁剪保留比例',
        "default": 0.9,
        "min": 0.1,
        "max": 0.99,
        "options": [],
        "description": '随机裁剪保留比例',
        "required": False,
    },
    {
        "name": 'concat_segments',
        "type": 'int',
        "label": '拼接段数',
        "default": 2,
        "min": 2,
        "max": 10,
        "options": [],
        "description": '随机拼接的音频段数量',
        "required": False,
    },
    {
        "name": 'reverse_probability',
        "type": 'float',
        "label": '反转概率',
        "default": 0.5,
        "min": 0.0,
        "max": 1.0,
        "options": [],
        "description": '音频反转的触发概率',
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
    op = str(parameters.get("op", parameters.get("时序操作类型", "mix")) or "mix").lower()
    max_shift = float(parameters.get("max_shift", parameters.get("最大时间偏移秒", 0.2)) or 0.2)
    crop_ratio = max(0.1, min(float(parameters.get("crop_ratio", parameters.get("裁剪比例", 0.9)) or 0.9), 1.0))
    concat_parts = max(2, int(parameters.get("concat_parts", parameters.get("拼接段数", 2)) or 2))
    rev_prob = float(parameters.get("rev_prob", parameters.get("反转概率", 0.5)) or 0.5)

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

        choices = ["shift", "rotate", "crop", "concat", "reverse"]
        if op == "mix":
            sel = list(np.random.choice(choices, size=2, replace=False))
        else:
            sel = [op] if op in choices else ["shift"]

        y_out = y.copy()
        for act in sel:
            if act == "shift":
                shift = int(np.random.uniform(-max_shift, max_shift) * sr)
                if shift > 0:
                    y_out = np.pad(y_out[shift:], (0, shift), mode="constant")
                elif shift < 0:
                    s = -shift
                    y_out = np.pad(y_out[:-s], (s, 0), mode="constant")
            elif act == "rotate":
                shift = int(np.random.uniform(-max_shift, max_shift) * sr)
                y_out = np.roll(y_out, shift)
            elif act == "crop":
                L = max(1, min(int(T * crop_ratio), T))
                start = int(np.random.randint(0, max(1, T - L + 1)))
                seg = y_out[start:start + L]
                y_out = _match_len(seg, T)
            elif act == "concat":
                plen = max(1, T // concat_parts)
                segs = []
                for _ in range(concat_parts):
                    start = int(np.random.randint(0, max(1, T - plen + 1)))
                    segs.append(y_out[start:start + plen])
                cat = np.concatenate(segs)
                y_out = _match_len(cat, T)
            elif act == "reverse":
                if np.random.rand() < rev_prob:
                    y_out = y_out[::-1].copy()

        out = output_dir / f"{sp.stem}_ts_{index:04d}.wav"
        sf.write(str(out), y_out, sr)
        outputs.append({
            "source_sample_id": sample.get("id"),
            "output_path": str(out),
            "relative_path": out.name,
            "metadata": {"method": "timeseries_structure", "op": op},
            "status": "created",
        })
        context.set_progress((index + 1) * 100 / target_count, f"TS structure {index+1}/{target_count}")

    return {"ok": True, "outputs": outputs, "logs": []}


def _match_len(y, target):
    if len(y) == target:
        return y
    if len(y) > target:
        return y[:target]
    return np.pad(y, (0, target - len(y)), mode="constant")
