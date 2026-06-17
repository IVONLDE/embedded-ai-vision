"""Audio environment noise injection augmenter. Adds white/pink/brown/uniform noise at a target SNR."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

SUPPORTED_EXTENSIONS = {".wav", ".mp3", ".flac", ".ogg", ".m4a"}


PARAMETERS = [
    {
        "name": "noise_type",
        "type": "select",
        "label": "噪声类型",
        "default": "white",
        "min": None,
        "max": None,
        "options": ["white", "pink", "brown", "uniform"],
        "description": "环境噪声频谱类型",
        "required": False,
    },
    {
        "name": "target_snr",
        "type": "float",
        "label": "目标SNR(dB)",
        "default": 10.0,
        "min": -20.0,
        "max": 40.0,
        "options": [],
        "description": "目标信噪比",
        "required": False,
    },
]


def run(payload: dict, context) -> dict:
    parameters = payload.get("parameters", {}) or {}
    samples = payload.get("input", {}).get("samples", []) or []
    output_dir = Path(payload.get("output", {}).get("output_dir", "."))

    noise_type = str(parameters.get("noise_type", "white")).lower()
    target_snr = float(parameters.get("target_snr", 10.0))

    if not samples:
        return {"ok": True, "outputs": [], "logs": []}

    output_dir.mkdir(parents=True, exist_ok=True)
    target_count = max(1, int(payload.get("target_count") or len(samples)))
    outputs = []

    for idx in range(target_count):
        if context.is_cancel_requested():
            return {"ok": False, "error_code": "CANCELLED", "message": "任务已取消", "details": {}}

        sample = samples[idx % len(samples)]
        context.set_progress((idx + 1) * 100 / target_count, f"环境噪声注入 {idx + 1}/{target_count}")

        sample_path = _resolve_path(sample)
        if not sample_path or not sample_path.is_file():
            return {
                "ok": False,
                "error_code": "SOURCE_FILE_NOT_FOUND",
                "message": f"Cannot read source sample: {sample_path}",
            }

        result = _inject_environment_noise(sample_path, output_dir, idx, noise_type, target_snr)
        if result:
            outputs.append(
                {
                    "output_path": result["path"],
                    "relative_path": Path(result["path"]).name,
                    "metadata": {
                        "original": str(sample_path),
                        "noise_type": noise_type,
                        "target_snr": target_snr,
                    },
                }
            )

    return {"ok": True, "outputs": outputs, "logs": []}


def _resolve_path(sample: dict) -> Optional[Path]:
    path = sample.get("sample_path") or sample.get("path") or sample.get("file_path")
    if not path:
        return None
    p = Path(path)
    if p.suffix.lower() in SUPPORTED_EXTENSIONS:
        return p
    return None


def _inject_environment_noise(path: Path, output_dir: Path, idx: int, noise_type: str, snr_db: float) -> Optional[dict]:
    try:
        import numpy as np
        import librosa
        import soundfile as sf
    except Exception:
        return None

    try:
        y, sr = librosa.load(str(path), sr=None, mono=False)
        if y.ndim == 1:
            y = y[np.newaxis, :]
        T = y.shape[-1]

        snr_db = max(-5.0, min(snr_db, 60.0))

        rng = np.random.default_rng()
        y_out_channels = []
        for c in range(y.shape[0]):
            signal = y[c]
            noise = rng.standard_normal(size=T).astype(np.float32)
            if noise_type == "pink":
                noise = np.cumsum(noise) / (np.sqrt(np.arange(1, T + 1, dtype=np.float32)) + 1e-6)
            elif noise_type == "brown":
                noise = np.cumsum(noise)
                noise = noise / (np.max(np.abs(noise)) + 1e-6)
            elif noise_type == "uniform":
                noise = rng.uniform(-1.0, 1.0, size=T).astype(np.float32)

            sp = float(np.mean(signal.astype(np.float32) ** 2) + 1e-8)
            npow = float(np.mean(noise.astype(np.float32) ** 2) + 1e-8)
            snr_linear = 10.0 ** (snr_db / 10.0)
            noise_scale = np.sqrt(sp / (snr_linear * npow))
            y_noisy = signal + noise_scale * noise
            y_noisy = _match_length(y_noisy[np.newaxis, :], T)[0]
            y_out_channels.append(y_noisy)

        y_out = np.stack(y_out_channels, axis=0)
        y_save = _prepare_for_save(y_out)

        out_path = output_dir / f"env_noise_{idx}_{path.name}"
        sf.write(str(out_path), y_save, int(sr))
        return {"path": str(out_path)}
    except Exception:
        return None


def _match_length(y: "np.ndarray", target_len: int) -> "np.ndarray":
    if y.shape[-1] == target_len:
        return y
    if y.shape[-1] > target_len:
        return y[..., :target_len]
    import numpy as np
    pad = target_len - y.shape[-1]
    return np.pad(y, ((0, 0), (0, pad)), mode="constant")


def _prepare_for_save(y: "np.ndarray") -> "np.ndarray":
    import numpy as np

    y = np.asarray(y)
    if y.ndim == 1:
        y_out = y
    else:
        y_out = y.T
    peak = float(np.max(np.abs(y_out))) if y_out.size else 0.0
    if peak > 1.0:
        y_out = y_out / (peak + 1e-6) * 0.999
    return y_out
