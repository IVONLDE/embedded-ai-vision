from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from ._image_io import read_image, write_image


PARAMETERS = [
    {
        "name": "diffusion_steps",
        "type": "int",
        "label": "扩散步数",
        "default": 40,
        "min": 5,
        "max": 200,
        "options": [],
        "description": "基于原图加噪再去噪的推理步数",
        "required": False,
    },
    {
        "name": "cfg_guidance_scale",
        "type": "float",
        "label": "去噪引导强度",
        "default": 1.0,
        "min": 0.0,
        "max": 5.0,
        "options": [],
        "description": "去噪预测强度，过高会偏离原图",
        "required": False,
    },
    {
        "name": "noise_strength",
        "type": "float",
        "label": "加噪强度",
        "default": 0.25,
        "min": 0.0,
        "max": 0.8,
        "options": [],
        "description": "从原图扩散扰动的强度，越大变化越明显",
        "required": False,
    },
    {
        "name": "blend_strength",
        "type": "float",
        "label": "去噪融合强度",
        "default": 0.55,
        "min": 0.0,
        "max": 1.0,
        "options": [],
        "description": "扩散去噪结果与原图的融合比例",
        "required": False,
    },
]


def run(payload: dict, context) -> dict:
    try:
        import torch
        import torch.nn as nn
        import torch.optim as optim
    except ImportError:
        return _fallback(payload, context, Path(payload.get("output", {}).get("output_dir") or "."), payload.get("input", {}).get("samples", []) or [], max(1, int(payload.get("target_count") or 1)), "diffusion", payload.get("parameters", {}) or {})

    parameters = payload.get("parameters", {}) or {}
    device = _resolve_device(torch)
    output_dir = Path(payload.get("output", {}).get("output_dir") or ".")
    output_dir.mkdir(parents=True, exist_ok=True)

    samples = payload.get("input", {}).get("samples", []) or []
    if not samples:
        return {"ok": False, "error_code": "NO_INPUT_SAMPLES"}

    target_count = max(1, int(payload.get("target_count") or len(samples)))
    cfg_scale = _clamp_float(parameters.get("cfg_guidance_scale", parameters.get("cfg_scale", 1.0)), 0.0, 5.0)
    inference_steps = _clamp_int(parameters.get("diffusion_steps", parameters.get("inference_steps", 40)), 5, 200)
    lr = _clamp_float(parameters.get("learning_rate", parameters.get("lr", 0.0001)), 1e-6, 0.1)
    noise_strength = _clamp_float(parameters.get("noise_strength", 0.25), 0.0, 0.8)
    blend_strength = _clamp_float(parameters.get("blend_strength", 0.55), 0.0, 1.0)
    image_size = 64
    max_images = max(2, min(_clamp_int(parameters.get("max_images", 32), 2, 64), 64))
    total_steps = 200

    betas = torch.linspace(1e-4, 0.02, total_steps, device=device)
    alphas = 1.0 - betas
    alphas_cumprod = torch.cumprod(alphas, dim=0)

    tensors = _read_images(samples, image_size, max_images, device)
    if tensors is None or tensors.size(0) < 2:
        return _fallback(payload, context, output_dir, samples, target_count, "diffusion", parameters)

    n = tensors.size(0)
    batch_size = min(16, n)
    model = _build_model(device).to(device)
    opt = optim.Adam(model.parameters(), lr=lr)
    train_steps = max(20, min(120, n * 3, inference_steps * 2))

    for step in range(train_steps):
        if context.is_cancel_requested():
            return {"ok": False, "error_code": "CANCELLED", "message": "Cancelled"}
        idx = torch.randint(0, n, (batch_size,), device=device)
        x0 = tensors[idx]
        t = torch.randint(0, total_steps, (batch_size,), device=device)
        noise = torch.randn_like(x0)
        a_bar = alphas_cumprod[t].view(-1, 1, 1, 1)
        x_t = torch.sqrt(a_bar) * x0 + torch.sqrt(1.0 - a_bar) * noise
        loss = torch.mean((model(x_t, t) - noise) ** 2)
        opt.zero_grad()
        loss.backward()
        opt.step()
        context.set_progress(step * 50 / train_steps, f"Diffusion train {step + 1}/{train_steps}")

    model.eval()
    outputs = []
    for index in range(target_count):
        if context.is_cancel_requested():
            return {"ok": False, "error_code": "CANCELLED", "message": "Cancelled"}
        source_sample = samples[index % len(samples)]
        x0 = _read_single_image(source_sample, image_size, device)
        if x0 is None:
            continue

        with torch.no_grad():
            start_t = max(1, min(total_steps - 1, int(noise_strength * (total_steps - 1))))
            noise = torch.randn_like(x0)
            a_bar_start = alphas_cumprod[start_t].view(1, 1, 1, 1)
            x = torch.sqrt(a_bar_start) * x0 + torch.sqrt(1.0 - a_bar_start) * noise
            schedule = np.linspace(start_t, 0, num=min(inference_steps, start_t + 1), dtype=np.int64)
            for t_val in schedule:
                t_tensor = torch.tensor([int(t_val)], device=device, dtype=torch.long)
                a_t = alphas[int(t_val)].view(1, 1, 1, 1)
                a_bar_t = alphas_cumprod[int(t_val)].view(1, 1, 1, 1)
                beta_t = 1.0 - a_t
                pred = model(x, t_tensor) * cfg_scale
                coef = (1.0 - a_t) / torch.sqrt(1.0 - a_bar_t)
                mean = (1.0 / torch.sqrt(a_t)) * (x - coef * pred)
                x = mean + (torch.sqrt(beta_t) * torch.randn_like(x) if int(t_val) > 0 else 0)
            x = (x0 * (1.0 - blend_strength) + x * blend_strength).clamp(-1.0, 1.0)

        img = _to_original_size_bgr(x[0], source_sample)
        out = output_dir / f"{_sample_stem(source_sample)}_diffusion_{index:04d}.jpg"
        if not write_image(out, img):
            return {"ok": False, "error_code": "IMAGE_WRITE_ERROR", "message": f"Cannot write image: {out}"}
        outputs.append(
            {
                "source_sample_id": source_sample.get("id"),
                "output_path": str(out),
                "relative_path": out.name,
                "metadata": {
                    "method": "diffusion",
                    "algorithm_key": payload.get("algorithm_key", "generation.image.diffusion"),
                    "diffusion_steps": inference_steps,
                    "cfg_guidance_scale": cfg_scale,
                    "noise_strength": noise_strength,
                    "blend_strength": blend_strength,
                },
                "status": "created",
            }
        )
        context.set_progress(50 + (index + 1) * 50 / target_count, f"Diffusion gen {index + 1}/{target_count}")
    return {"ok": True, "outputs": outputs, "logs": []}


def _fallback(payload, context, output_dir, samples, target_count, method, parameters):
    output_dir.mkdir(parents=True, exist_ok=True)
    steps = _clamp_int(parameters.get("diffusion_steps", 40), 5, 200)
    noise_strength = _clamp_float(parameters.get("noise_strength", 0.25), 0.0, 0.8)
    blend_strength = _clamp_float(parameters.get("blend_strength", 0.55), 0.0, 1.0)
    outputs = []
    for index in range(target_count):
        if context.is_cancel_requested():
            return {"ok": False, "error_code": "CANCELLED"}
        sample = samples[index % len(samples)]
        p = Path(sample.get("sample_path") or sample.get("path") or sample.get("file_path") or "")
        img = read_image(p)
        if img is None:
            continue
        original = img.astype(np.float32)
        noisy = original.copy()
        for _ in range(max(1, steps // 20)):
            noise = np.random.normal(0, noise_strength * 24.0, noisy.shape)
            noisy = np.clip(noisy + noise, 0, 255)
            noisy = cv2.bilateralFilter(noisy.astype(np.uint8), 5, 35, 35).astype(np.float32)
        img = np.clip(original * (1.0 - blend_strength) + noisy * blend_strength, 0, 255).astype(np.uint8)
        out = output_dir / f"{_sample_stem(sample)}_{method}_{index:04d}.jpg"
        if not write_image(out, img):
            return {"ok": False, "error_code": "IMAGE_WRITE_ERROR", "message": f"Cannot write image: {out}"}
        outputs.append(
            {
                "source_sample_id": sample.get("id"),
                "output_path": str(out),
                "relative_path": out.name,
                "metadata": {
                    "method": method,
                    "fallback": True,
                    "diffusion_steps": steps,
                    "noise_strength": noise_strength,
                    "blend_strength": blend_strength,
                },
                "status": "created",
            }
        )
        context.set_progress((index + 1) * 100 / target_count, f"{method} fb {index + 1}/{target_count}")
    return {"ok": True, "outputs": outputs, "logs": ["fallback mode"]}


def _read_images(samples, image_size, max_images, device):
    import torch

    tensors = []
    for sample in samples[:max_images]:
        x = _read_single_image(sample, image_size, device)
        if x is not None:
            tensors.append(x[0])
    return torch.stack(tensors, dim=0) if len(tensors) >= 2 else None


def _read_single_image(sample, image_size, device):
    import torch

    p = str(Path(sample.get("sample_path") or sample.get("path") or ""))
    img = read_image(p)
    if img is None:
        return None
    img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    img = cv2.resize(img, (image_size, image_size), interpolation=cv2.INTER_AREA)
    x = torch.from_numpy(img).permute(2, 0, 1).to(device=device, dtype=torch.float32) / 255.0
    return (x * 2.0 - 1.0).unsqueeze(0)


def _to_bgr(x):
    import torch

    x = x.detach().cpu().clamp(-1.0, 1.0)
    x = (x + 1.0) / 2.0
    x = (x * 255.0).to(torch.uint8).permute(1, 2, 0).numpy()
    return cv2.cvtColor(x, cv2.COLOR_RGB2BGR)


def _to_original_size_bgr(x, sample):
    img = _to_bgr(x)
    source = read_image(Path(sample.get("sample_path") or sample.get("path") or ""))
    if source is None:
        return img
    h, w = source.shape[:2]
    return cv2.resize(img, (w, h), interpolation=cv2.INTER_LINEAR)


def _sample_stem(sample):
    return Path(sample.get("sample_path") or sample.get("path") or "sample").stem or "sample"


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


def _build_model(device):
    import torch
    import torch.nn as nn

    base_ch = 64
    time_dim = 128

    def _temb(t, dim):
        half = dim // 2
        scale = np.log(10000.0) / (half - 1)
        emb = torch.exp(torch.arange(half, device=device, dtype=torch.float32) * -scale)
        emb = t.float().unsqueeze(1) * emb.unsqueeze(0)
        return torch.cat([torch.sin(emb), torch.cos(emb)], dim=1)

    class NoisePredictor(nn.Module):
        def __init__(self):
            super().__init__()
            self.c1 = nn.Conv2d(3, base_ch, 3, 1, 1)
            self.c2 = nn.Conv2d(base_ch, base_ch * 2, 4, 2, 1)
            self.c3 = nn.Conv2d(base_ch * 2, base_ch * 2, 3, 1, 1)
            self.tmlp = nn.Sequential(nn.Linear(time_dim, base_ch * 2), nn.ReLU(inplace=True), nn.Linear(base_ch * 2, base_ch * 2))
            self.up = nn.ConvTranspose2d(base_ch * 2, base_ch, 4, 2, 1)
            self.cout = nn.Conv2d(base_ch, 3, 3, 1, 1)

        def forward(self, xt, t):
            h1 = torch.relu(self.c1(xt))
            h2 = torch.relu(self.c2(h1))
            h2 = self.c3(h2)
            temb = _temb(t, time_dim)
            h2 = h2 + self.tmlp(temb).unsqueeze(-1).unsqueeze(-1)
            return self.cout(torch.relu(self.up(h2)))

    return NoisePredictor()


def _resolve_device(torch):
    if getattr(torch, "cuda", None) and torch.cuda.is_available():
        torch.cuda.set_device(0)
        return torch.device("cuda:0")
    try:
        import torch_npu  # noqa: F401

        if torch.npu.is_available():
            torch_npu.npu.set_device(0)
            return torch.device("npu:0")
    except ImportError:
        pass
    return torch.device("cpu")
