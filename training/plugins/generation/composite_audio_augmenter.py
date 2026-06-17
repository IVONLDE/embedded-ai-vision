from __future__ import annotations

from pathlib import Path

import numpy as np


PARAMETERS = [
    {
        "name": 'combination_count',
        "type": 'int',
        "label": '组合次数',
        "default": 3,
        "min": 1,
        "max": 10,
        "options": [],
        "description": '每次随机选取并应用的增强策略数量',
        "required": False,
    },
    {
        "name": 'include_specaugment',
        "type": 'bool',
        "label": '包含SpecAugment',
        "default": True,
        "min": None,
        "max": None,
        "options": [],
        "description": '是否将SpecAugment纳入候选策略池',
        "required": False,
    },
    {
        "name": 'include_spatial',
        "type": 'bool',
        "label": '包含空间声学',
        "default": True,
        "min": None,
        "max": None,
        "options": [],
        "description": '是否将空间声学纳入候选策略池',
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
    combo = max(2, min(int(parameters.get("combo", parameters.get("组合次数", 3)) or 3), 6))
    inc_spec = bool(parameters.get("inc_spec", parameters.get("是否包含SpecAugment", True)))
    inc_spatial = bool(parameters.get("inc_spatial", parameters.get("是否包含空间声学", True)))

    outputs = []
    rng = np.random.default_rng()

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
        y_out = y.copy().astype(np.float32)

        ops_pool = ["tempo", "energy", "timeseries", "channel", "noise", "filter", "distort"]
        if inc_spec:
            ops_pool.append("specaugment")
        if inc_spatial:
            ops_pool.append("spatial")

        ops = list(rng.choice(ops_pool, size=min(combo, len(ops_pool)), replace=False))

        for op in ops:
            if op == "tempo":
                rate = float(rng.uniform(0.9, 1.1))
                if abs(rate - 1.0) > 1e-6:
                    y_out = librosa.effects.time_stretch(y_out, rate=rate)
                    y_out = _mlen(y_out, T)
                n_steps = float(rng.uniform(-2, 2))
                if abs(n_steps) > 1e-6:
                    y_out = librosa.effects.pitch_shift(y_out, sr=sr, n_steps=n_steps)
                    y_out = _mlen(y_out, T)
            elif op == "energy":
                gain = float(rng.uniform(0.7, 1.3))
                y_out = y_out * gain
                if rng.random() < 0.7:
                    st = int(rng.integers(0, max(1, T - int(0.1 * sr))))
                    sl = int(rng.uniform(0.02, 0.08) * sr)
                    sl = max(1, min(sl, T - st))
                    y_out[st:st + sl] = 0.0
            elif op == "timeseries":
                if rng.random() < 0.5:
                    shift = int(rng.uniform(-0.2, 0.2) * sr)
                    if shift > 0:
                        y_out = np.pad(y_out[shift:], (0, shift), mode="constant")
                    elif shift < 0:
                        s = -shift
                        y_out = np.pad(y_out[:-s], (s, 0), mode="constant")
                if rng.random() < 0.3:
                    y_out = y_out[::-1].copy()
            elif op == "channel":
                pass
            elif op == "noise":
                snr = float(rng.uniform(5.0, 20.0))
                noise = rng.standard_normal(size=T).astype(np.float32)
                spow = float(np.mean(y_out.astype(np.float32) ** 2) + 1e-8)
                npow = float(np.mean(noise.astype(np.float32) ** 2) + 1e-8)
                snr_lin = 10.0 ** (snr / 10.0)
                y_out = y_out + np.sqrt(spow / (snr_lin * npow)) * noise
            elif op == "filter":
                lo, hi = float(rng.uniform(200, 800)), float(rng.uniform(1500, 4000))
                if lo > hi:
                    lo, hi = hi, lo
                n_fft = len(y_out)
                Y = np.fft.rfft(y_out)
                freqs = np.fft.rfftfreq(n_fft, d=1.0 / sr)
                mask = np.ones_like(Y, dtype=np.float32)
                mask[(freqs < lo) | (freqs > hi)] = 0.0
                y_out = np.fft.irfft(Y * mask, n=n_fft)
                y_out = _mlen(y_out, T)
            elif op == "distort":
                ds = float(rng.uniform(0.6, 0.95))
                if ds < 0.999:
                    nsr = max(8000, int(sr * ds))
                    y_out = librosa.resample(y_out, orig_sr=sr, target_sr=nsr)
                    y_out = librosa.resample(y_out, orig_sr=nsr, target_sr=sr)
                    y_out = _mlen(y_out, T)
                lv = (2 ** int(rng.integers(6, 12))) - 1
                y_out = np.round(y_out * lv) / lv
            elif op == "specaugment":
                n_mels, n_fft_s, hop_s = 48, 1024, 256
                S = librosa.feature.melspectrogram(y=y_out, sr=sr, n_fft=n_fft_s, hop_length=hop_s, n_mels=n_mels, power=2.0)
                Sm = S.copy()
                for _ in range(1 + int(rng.random() < 0.5)):
                    f = int(rng.uniform(0, 8))
                    if f > 0:
                        f0 = int(rng.integers(0, max(1, n_mels - f + 1)))
                        Sm[f0:f0 + f, :] = 0.0
                tf = Sm.shape[-1]
                for _ in range(1 + int(rng.random() < 0.5)):
                    t = int(rng.uniform(0, 16))
                    if t > 0:
                        t0 = int(rng.integers(0, max(1, tf - t + 1)))
                        Sm[:, t0:t0 + t] = 0.0
                y_out = librosa.feature.inverse.mel_to_audio(Sm, sr=sr, n_fft=n_fft_s, hop_length=hop_s, power=2.0, n_iter=12)
                y_out = _mlen(y_out, T)
            elif op == "spatial":
                if rng.random() < 0.5:
                    for k in range(2):
                        delay = int(rng.uniform(0.02, 0.06) * sr)
                        if delay > 0:
                            decay = 0.5 ** k
                            d = np.zeros_like(y_out)
                            if delay < T:
                                d[delay:] = y_out[:T - delay]
                            y_out = y_out + decay * d
                if rng.random() < 0.4:
                    L = int(max(1, 0.5 * sr))
                    t_arr = np.arange(L, dtype=np.float32) / sr
                    ir = np.random.randn(L).astype(np.float32) * np.exp(-t_arr / 0.2)
                    y_conv = np.convolve(y_out, ir, mode="full")
                    y_out = y_conv[:T]

        out = output_dir / f"{sp.stem}_composite_{index:04d}.wav"
        sf.write(str(out), y_out, sr)
        outputs.append({
            "source_sample_id": sample.get("id"),
            "output_path": str(out),
            "relative_path": out.name,
            "metadata": {"method": "composite", "ops": ops},
            "status": "created",
        })
        context.set_progress((index + 1) * 100 / target_count, f"Composite {index+1}/{target_count}")

    return {"ok": True, "outputs": outputs, "logs": []}


def _mlen(y, target):
    if len(y) == target:
        return y
    if len(y) > target:
        return y[:target]
    return np.pad(y, (0, target - len(y)), mode="constant")
