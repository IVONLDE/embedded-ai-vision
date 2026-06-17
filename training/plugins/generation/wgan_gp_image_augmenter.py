from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from ._image_io import read_image, write_image


PARAMETERS = [
    {
        "name": 'gradient_penalty',
        "type": 'float',
        "label": '梯度惩罚系数',
        "default": 10.0,
        "min": 0.1,
        "max": 50.0,
        "options": [],
        "description": 'WGAN-GP梯度惩罚权重',
        "required": False,
    },
    {
        "name": 'discriminator_iterations',
        "type": 'int',
        "label": '判别器迭代次数',
        "default": 5,
        "min": 1,
        "max": 20,
        "options": [],
        "description": '每次生成器更新的判别器训练步数',
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
        "description": '优化器学习率',
        "required": False,
    },
    {
        "name": 'enhance_strength',
        "type": 'float',
        "label": '增强强度',
        "default": 1.0,
        "min": 0.3,
        "max": 2.0,
        "options": [],
        "description": '控制GAN风格、纹理和形变叠加强度，数值越大生成痕迹越明显',
        "required": False,
    },
]


def run(payload: dict, context) -> dict:
    try:
        import torch
        import torch.nn as nn
        import torch.optim as optim
    except ImportError:
        return {"ok": False, "error_code": "MISSING_DEPENDENCY", "message": "Missing PyTorch"}

    parameters = payload.get("parameters", {}) or {}
    device = _resolve_device(torch)
    output_dir = Path(payload.get("output", {}).get("output_dir") or ".")
    output_dir.mkdir(parents=True, exist_ok=True)

    samples = payload.get("input", {}).get("samples", []) or []
    samples = [sample for sample in samples if _is_image_sample(sample)]
    if not samples:
        return {"ok": False, "error_code": "NO_INPUT_SAMPLES"}

    target_count = max(1, int(payload.get("target_count") or len(samples)))
    gp_lambda = float(parameters.get("gp_lambda", parameters.get("gradient_penalty", 10.0)) or 10.0)
    n_critic = int(parameters.get("n_critic", parameters.get("critic_iters", parameters.get("discriminator_iterations", 5))) or 5)
    lr = float(parameters.get("lr", parameters.get("learning_rate", 0.0001)) or 0.0001)
    enhance_strength = float(parameters.get("enhance_strength", 1.0) or 1.0)
    enhance_strength = max(0.3, min(enhance_strength, 2.0))
    image_size = 32
    max_images = int(parameters.get("max_images", 32))
    max_images = max(2, min(max_images, 64))

    tensors = _read_images_as_tensor(samples, image_size, max_images, device)
    if tensors is None or tensors.size(0) < 2:
        return _fallback_run(payload, context, output_dir, samples, target_count, "wgan_gp")

    n = tensors.size(0)
    batch_size = min(16, n)
    latent_dim = 100
    base_ch = 64

    g, d, g_opt, d_opt = _build_wgan_models(device, latent_dim, base_ch, lr)
    steps = max(5, min(60, n * 2))

    for step in range(steps):
        if context.is_cancel_requested():
            return {"ok": False, "error_code": "CANCELLED", "message": "Cancelled"}

        for _ in range(max(1, n_critic)):
            idx = torch.randint(0, n, (batch_size,), device=device)
            x_real = tensors[idx]
            z = torch.randn(batch_size, latent_dim, device=device)
            x_fake = g(z).detach()
            d_real = d(x_real).mean()
            d_fake = d(x_fake).mean()
            gp = _gradient_penalty(d, x_real, x_fake, device)
            d_loss_val = -(d_real - d_fake) + gp_lambda * gp
            d_opt.zero_grad()
            d_loss_val.backward()
            d_opt.step()

        z = torch.randn(batch_size, latent_dim, device=device)
        x_fake = g(z)
        g_loss = -d(x_fake).mean()
        g_opt.zero_grad()
        g_loss.backward()
        g_opt.step()
        context.set_progress(step * 50 / steps, f"WGAN-GP train {step + 1}/{steps}")

    g.eval()
    # 过滤掉无标签的样本，只从有标签的源样本中循环选取
    labeled_samples = [s for s in samples if (s.get("labels") or s.get("labels_json") or [])]
    if not labeled_samples:
        labeled_samples = samples
    outputs = []
    for index in range(target_count):
        if context.is_cancel_requested():
            return {"ok": False, "error_code": "CANCELLED", "message": "Cancelled"}
        with torch.no_grad():
            z = torch.randn(1, latent_dim, device=device)
            x = g(z)[0]
        gan_bgr = _tensor_to_bgr_image(x)
        src = labeled_samples[index % len(labeled_samples)]
        source_path = _sample_path(src)
        source_img = read_image(source_path)
        if source_img is None:
            img_bgr = gan_bgr
            source_conditioned = False
        else:
            img_bgr = _blend_gan_texture(source_img, gan_bgr, enhance_strength)
            source_conditioned = True
        output_path = output_dir / f"wgan_gp_{index:04d}.jpg"
        if not write_image(output_path, img_bgr):
            return {"ok": False, "error_code": "IMAGE_WRITE_ERROR", "message": f"Cannot write image: {output_path}"}
        outputs.append({
            "source_sample_id": src.get("id"),
            "output_path": str(output_path),
            "relative_path": output_path.name,
            "metadata": {
                "method": "wgan_gp",
                "algorithm_key": payload.get("algorithm_key", "generation.image.wgan_gp"),
                "source_conditioned": source_conditioned,
                "enhance_strength": enhance_strength,
            },
            "status": "created",
        })
        context.set_progress(50 + (index + 1) * 50 / target_count, f"WGAN-GP gen {index + 1}/{target_count}")

    return {"ok": True, "outputs": outputs, "logs": []}


def _fallback_run(payload, context, output_dir, samples, target_count, method):
    outputs = []
    for index in range(target_count):
        if context.is_cancel_requested():
            return {"ok": False, "error_code": "CANCELLED", "message": "Cancelled"}
        sample = samples[index % len(samples)]
        source_path = _sample_path(sample)
        img = read_image(source_path)
        if img is None:
            continue
        img = cv2.flip(img, 1)
        img = cv2.GaussianBlur(img, (5, 5), 0)
        output_path = output_dir / f"{method}_{index:04d}.jpg"
        if not write_image(output_path, img):
            return {"ok": False, "error_code": "IMAGE_WRITE_ERROR", "message": f"Cannot write image: {output_path}"}
        outputs.append({
            "source_sample_id": sample.get("id"),
            "output_path": str(output_path),
            "relative_path": output_path.name,
            "metadata": {"method": method, "fallback": True, "algorithm_key": payload.get("algorithm_key", "")},
            "status": "created",
        })
        context.set_progress((index + 1) * 100 / target_count, f"{method} fb {index + 1}/{target_count}")
    return {"ok": True, "outputs": outputs, "logs": ["fallback mode"]}


def _read_images_as_tensor(samples, image_size, max_images, device):
    import torch
    sampled = samples[:max_images]
    tensors = []
    for s in sampled:
        p = str(_sample_path(s))
        img = read_image(p)
        if img is None:
            continue
        img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        img = cv2.resize(img, (image_size, image_size), interpolation=cv2.INTER_AREA)
        x = torch.from_numpy(img).permute(2, 0, 1).to(device=device, dtype=torch.float32) / 255.0
        x = x * 2.0 - 1.0
        tensors.append(x)
    if len(tensors) < 2:
        return None
    return torch.stack(tensors, dim=0)


def _sample_path(sample):
    return Path(sample.get("sample_path") or sample.get("path") or sample.get("file_path") or "")


def _is_image_sample(sample):
    path = _sample_path(sample)
    return path.suffix.lower() in {".bmp", ".jpeg", ".jpg", ".png", ".tif", ".tiff", ".webp"}


def _blend_gan_texture(source_img, gan_img, enhance_strength):
    strength = max(0.3, min(float(enhance_strength or 1.0), 2.0))
    gan_resized = cv2.resize(gan_img, (source_img.shape[1], source_img.shape[0]), interpolation=cv2.INTER_CUBIC)
    source_float = source_img.astype(np.float32)
    gan_float = gan_resized.astype(np.float32)

    gan_low = cv2.GaussianBlur(gan_float, (0, 0), 11)
    source_low = cv2.GaussianBlur(source_float, (0, 0), 11)
    gan_texture = gan_float - cv2.GaussianBlur(gan_float, (0, 0), 2)
    source_detail = source_float - cv2.GaussianBlur(source_float, (0, 0), 1.2)

    color_shift = (gan_low - source_low) * (0.25 * strength)
    texture_shift = gan_texture * (0.35 * strength)
    styled = source_float + color_shift + texture_shift + source_detail * (0.25 * strength)
    gan_weight = min(0.45, 0.28 * strength)
    styled = cv2.addWeighted(source_float, 1.0 - gan_weight, styled, gan_weight, 0)

    gray_gan = cv2.cvtColor(np.clip(gan_resized, 0, 255).astype(np.uint8), cv2.COLOR_BGR2GRAY).astype(np.float32)
    flow_x = cv2.GaussianBlur(gray_gan - 127.5, (0, 0), 9) / 127.5 * (2.5 * strength)
    flow_y = cv2.GaussianBlur(np.roll(gray_gan, gray_gan.shape[1] // 5, axis=1) - 127.5, (0, 0), 9) / 127.5 * (2.5 * strength)
    h, w = gray_gan.shape
    grid_x, grid_y = np.meshgrid(np.arange(w, dtype=np.float32), np.arange(h, dtype=np.float32))
    warped = cv2.remap(
        np.clip(styled, 0, 255).astype(np.uint8),
        grid_x + flow_x.astype(np.float32),
        grid_y + flow_y.astype(np.float32),
        cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_REFLECT_101,
    ).astype(np.float32)

    source_edges = cv2.Canny(source_img, 80, 160).astype(np.float32) / 255.0
    edge_mask = cv2.GaussianBlur(source_edges, (0, 0), 1.2)[:, :, None]
    mixed = warped * (1.0 - edge_mask * 0.45) + source_float * (edge_mask * 0.45)
    return np.clip(mixed, 0, 255).astype(np.uint8)


def _tensor_to_bgr_image(x):
    import torch
    x = x.detach().cpu().clamp(-1.0, 1.0)
    x = (x + 1.0) / 2.0
    x = (x * 255.0).to(torch.uint8)
    x = x.permute(1, 2, 0).numpy()
    x = cv2.cvtColor(x, cv2.COLOR_RGB2BGR)
    return x


def _build_wgan_models(device, latent_dim, base_ch, lr):
    import torch
    import torch.nn as nn
    import torch.optim as optim

    class Generator(nn.Module):
        def __init__(self):
            super().__init__()
            self.fc = nn.Linear(latent_dim, base_ch * 4 * 4)
            self.net = nn.Sequential(
                nn.ReLU(inplace=True),
                nn.ConvTranspose2d(base_ch, base_ch // 2, 4, 2, 1),
                nn.ReLU(inplace=True),
                nn.ConvTranspose2d(base_ch // 2, base_ch // 4, 4, 2, 1),
                nn.ReLU(inplace=True),
                nn.ConvTranspose2d(base_ch // 4, 3, 4, 2, 1),
                nn.Tanh(),
            )
        def forward(self, z):
            x = self.fc(z).view(-1, base_ch, 4, 4)
            return self.net(x)

    class Discriminator(nn.Module):
        def __init__(self):
            super().__init__()
            self.net = nn.Sequential(
                nn.Conv2d(3, base_ch // 4, 4, 2, 1),
                nn.LeakyReLU(0.2, inplace=True),
                nn.Conv2d(base_ch // 4, base_ch // 2, 4, 2, 1),
                nn.LeakyReLU(0.2, inplace=True),
                nn.Conv2d(base_ch // 2, base_ch, 4, 2, 1),
                nn.LeakyReLU(0.2, inplace=True),
            )
            self.fc = nn.Linear(base_ch * 4 * 4, 1)
        def forward(self, x):
            h = self.net(x).view(x.size(0), -1)
            return self.fc(h)

    g = Generator().to(device)
    d = Discriminator().to(device)
    g_opt = optim.Adam(g.parameters(), lr=lr, betas=(0.5, 0.9))
    d_opt = optim.Adam(d.parameters(), lr=lr, betas=(0.5, 0.9))
    return g, d, g_opt, d_opt


def _gradient_penalty(d_model, x_real, x_fake, device):
    import torch
    b = x_real.size(0)
    eps = torch.rand(b, 1, 1, 1, device=device)
    x_hat = eps * x_real + (1 - eps) * x_fake
    x_hat.requires_grad_(True)
    d_hat = d_model(x_hat)
    grad = torch.autograd.grad(
        outputs=d_hat, inputs=x_hat,
        grad_outputs=torch.ones_like(d_hat),
        create_graph=True, retain_graph=True, only_inputs=True,
    )[0]
    grad = grad.view(b, -1)
    norm = grad.norm(2, dim=1)
    return ((norm - 1.0) ** 2).mean()


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
