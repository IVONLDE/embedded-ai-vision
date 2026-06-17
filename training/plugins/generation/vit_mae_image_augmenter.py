from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from ._image_io import read_image, write_image


PARAMETERS = [
    {
        "name": 'mask_ratio',
        "type": 'float',
        "label": '掩码比例',
        "default": 0.35,
        "min": 0.05,
        "max": 0.9,
        "options": [],
        "description": '图像patch掩码比例',
        "required": False,
    },
    {
        "name": 'learning_rate',
        "type": 'float',
        "label": '学习率',
        "default": 0.0001,
        "min": 1e-06,
        "max": 0.1,
        "options": [],
        "description": '训练学习率',
        "required": False,
    },
    {
        "name": 'training_steps',
        "type": 'int',
        "label": '训练步数',
        "default": 120,
        "min": 10,
        "max": 500,
        "options": [],
        "description": '模拟训练迭代步数',
        "required": False,
    },
    {
        "name": 'patch_size',
        "type": 'int',
        "label": 'Patch大小',
        "default": 4,
        "min": 2,
        "max": 32,
        "options": [],
        "description": 'ViT patch划分尺寸',
        "required": False,
    },
    {
        "name": "blend_strength",
        "type": "float",
        "label": "重建融合强度",
        "default": 0.65,
        "min": 0.0,
        "max": 1.0,
        "options": [],
        "description": "Transformer重建区域与原图的融合比例",
        "required": False,
    },
]


def run(payload: dict, context) -> dict:
    try:
        import torch
        import torch.nn as nn
        import torch.optim as optim
    except ImportError:
        return {"ok": False, "error_code": "MISSING_DEPENDENCY"}
    parameters = payload.get("parameters", {}) or {}
    device = _resolve_device(torch)
    output_dir = Path(payload.get("output", {}).get("output_dir") or ".")
    output_dir.mkdir(parents=True, exist_ok=True)
    samples = payload.get("input", {}).get("samples", []) or []
    if not samples:
        return {"ok": False, "error_code": "NO_INPUT_SAMPLES"}
    target_count = max(1, int(payload.get("target_count") or len(samples)))
    mask_ratio = _clamp_float(parameters.get("mask_ratio", 0.35), 0.05, 0.9)
    train_cap = _clamp_int(parameters.get("training_steps", parameters.get("train_cap", 120)), 10, 500)
    ps = _clamp_int(parameters.get("patch_size", parameters.get("ps", 4)), 2, 16)
    lr = _clamp_float(parameters.get("learning_rate", parameters.get("lr", 0.0001)), 1e-6, 0.1)
    blend_strength = _clamp_float(parameters.get("blend_strength", 0.65), 0.0, 1.0)
    image_size = 64
    if image_size % ps != 0:
        return {"ok": False, "error_code": "INVALID_PATCH_SIZE"}
    max_images = max(2, min(64, int(parameters.get("max_images", 32))))
    tensors = _read_img(samples, image_size, max_images, device)
    if tensors is None or tensors.size(0) < 2:
        return _fb(payload, context, output_dir, samples, target_count, "vit_mae", parameters)
    n, bs = tensors.size(0), min(16, tensors.size(0))
    nps, npatch, pdim = image_size // ps, (image_size // ps) ** 2, 3 * ps * ps
    edim = 128
    el = nn.TransformerEncoderLayer(d_model=edim, nhead=4, dim_feedforward=edim*4, dropout=0.0, activation="gelu", batch_first=True)
    encoder = nn.TransformerEncoder(el, num_layers=4).to(device)
    pe = nn.Linear(pdim, edim).to(device)
    mt = nn.Parameter(torch.zeros(1, 1, edim, device=device))
    pos = nn.Parameter(torch.zeros(1, npatch, edim, device=device))
    hd = nn.Sequential(nn.LayerNorm(edim), nn.Linear(edim, pdim)).to(device)
    torch.nn.init.normal_(pos, 0.0, 0.02)
    torch.nn.init.normal_(mt, 0.0, 0.02)
    opt = optim.Adam(list(pe.parameters())+list(encoder.parameters())+list(hd.parameters())+[mt, pos], lr=lr)
    steps = min(train_cap, max(20, n*2))
    for step in range(steps):
        if context.is_cancel_requested():
            return {"ok": False, "error_code": "CANCELLED"}
        idx = torch.randint(0, n, (bs,), device=device)
        x0 = tensors[idx]
        m = torch.rand(bs, npatch, device=device) < mask_ratio
        if m.all():
            m = torch.rand(bs, npatch, device=device) < min(0.5, mask_ratio)
        pred, target = _fwd(x0, m, pe, mt, pos, encoder, hd, ps, nps, image_size)
        loss = torch.mean((pred[m] - target[m]) ** 2)
        opt.zero_grad()
        loss.backward()
        opt.step()
        context.set_progress(step * 50 / steps, f"ViT-MAE train {step+1}/{steps}")
    outputs = []
    for index in range(target_count):
        if context.is_cancel_requested():
            return {"ok": False, "error_code": "CANCELLED"}
        source_sample = samples[index % len(samples)]
        x0 = _read_single_img(source_sample, image_size, device)
        if x0 is None:
            continue
        m = torch.rand(1, npatch, device=device) < mask_ratio
        if m.all():
            m = torch.rand(1, npatch, device=device) < min(0.5, mask_ratio)
        patches = _patch(x0, ps, nps)
        tokens = pe(patches)
        tokens = torch.where(m.unsqueeze(-1), mt.expand(tokens.size(0), tokens.size(1), -1), tokens)
        tokens = tokens + pos
        h = encoder(tokens)
        pred = hd(h)
        blended_pred = patches * (1.0 - blend_strength) + pred * blend_strength
        out_p = torch.where(m.unsqueeze(-1), blended_pred, patches)
        x_rec = _unpatch(out_p, ps, nps, image_size).clamp(-1.0, 1.0)
        img = _to_original_size_bgr(x_rec[0], source_sample)
        out_f = output_dir / f"{_sample_stem(source_sample)}_vit_mae_{index:04d}.jpg"
        if not write_image(out_f, img):
            return {"ok": False, "error_code": "IMAGE_WRITE_ERROR", "message": f"Cannot write image: {out_f}"}
        outputs.append({
            "source_sample_id": source_sample.get("id"),
            "output_path": str(out_f),
            "relative_path": out_f.name,
            "metadata": {
                "method": "vit_mae",
                "mask_ratio": mask_ratio,
                "patch_size": ps,
                "training_steps": steps,
                "learning_rate": lr,
                "blend_strength": blend_strength,
            },
            "status": "created",
        })
        context.set_progress(50 + (index+1)*50/target_count, f"ViT-MAE gen {index+1}/{target_count}")
    return {"ok": True, "outputs": outputs, "logs": []}


def _fb(payload, context, output_dir, samples, target_count, method, parameters):
    ps = _clamp_int(parameters.get("patch_size", parameters.get("ps", 4)), 2, 16)
    mask_ratio = _clamp_float(parameters.get("mask_ratio", 0.35), 0.05, 0.9)
    outputs = []
    for index in range(target_count):
        if context.is_cancel_requested():
            return {"ok": False, "error_code": "CANCELLED"}
        s = samples[index % len(samples)]
        p = Path(s.get("sample_path") or s.get("path") or "")
        img = read_image(p)
        if img is None:
            continue
        h, w = img.shape[:2]
        if h < ps or w < ps:
            out = cv2.GaussianBlur(img, (3, 3), 0)
        else:
            out = img.copy()
            patch = max(2, ps * max(1, min(h, w) // 64))
            blurred = cv2.GaussianBlur(img, (3, 3), 0)
            for yy in range(0, h, patch):
                for xx in range(0, w, patch):
                    if np.random.random() < mask_ratio:
                        out[yy:yy + patch, xx:xx + patch] = blurred[yy:yy + patch, xx:xx + patch]
        of = output_dir / f"{_sample_stem(s)}_{method}_{index:04d}.jpg"
        if not write_image(of, out):
            return {"ok": False, "error_code": "IMAGE_WRITE_ERROR", "message": f"Cannot write image: {of}"}
        outputs.append({"source_sample_id": s.get("id"), "output_path": str(of), "relative_path": of.name, "metadata": {"method": method, "fallback": True, "mask_ratio": mask_ratio, "patch_size": ps}, "status": "created"})
        context.set_progress((index+1)*100/target_count, f"{method} fb {index+1}/{target_count}")
    return {"ok": True, "outputs": outputs, "logs": ["fallback mode"]}


def _read_img(samples, image_size, max_images, device):
    import torch
    tensors = []
    for s in samples[:max_images]:
        x = _read_single_img(s, image_size, device)
        if x is not None:
            tensors.append(x[0])
    return torch.stack(tensors, dim=0) if len(tensors) >= 2 else None


def _read_single_img(sample, image_size, device):
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


def _patch(x, ps, nps):
    B, C, H, W = x.shape
    x = x.view(B, C, nps, ps, nps, ps).permute(0, 2, 4, 1, 3, 5).contiguous()
    return x.view(B, nps*nps, C*ps*ps)


def _unpatch(patches, ps, nps, sz):
    B, P, D = patches.shape
    x = patches.view(B, nps, nps, 3, ps, ps).permute(0, 3, 1, 4, 2, 5).contiguous()
    return x.view(B, 3, sz, sz)


def _fwd(x, mask, pe, mt, pos, encoder, hd, ps, nps, sz):
    import torch
    patches = _patch(x, ps, nps)
    tokens = pe(patches)
    tokens = torch.where(mask.unsqueeze(-1), mt.expand(tokens.size(0), tokens.size(1), -1), tokens)
    tokens = tokens + pos
    h = encoder(tokens)
    pred = hd(h)
    return pred, patches


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
