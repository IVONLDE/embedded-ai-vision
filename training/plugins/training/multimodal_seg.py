"""
多模态语义分割训练插件 (图像+雷达 → 分割mask)。

使用UNet架构融合RGB图像和雷达特征，逐像素分类水面场景。
"""
from __future__ import annotations
from pathlib import Path
import os, sys, json, logging, random
import numpy as np

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


def _resolve_device(torch):
    if getattr(torch, "cuda", None) and torch.cuda.is_available():
        torch.cuda.set_device(0)
        return torch.device("cuda:0")
    try:
        import torch_npu  # noqa: F401

        if getattr(torch, "npu", None) and torch.npu.is_available():
            torch_npu.npu.set_device(0)
            return torch.device("npu:0")
    except Exception:
        pass
    return torch.device("cpu")

PARAMETERS = [
    {"name": "epochs", "type": "int", "label": "训练轮次", "default": 30, "min": 5, "max": 200, "options": [], "description": "训练epoch", "required": False},
    {"name": "batch_size", "type": "int", "label": "批大小", "default": 8, "min": 2, "max": 32, "options": [], "description": "批次大小", "required": False},
    {"name": "learning_rate", "type": "float", "label": "学习率", "default": 0.001, "min": 0.0001, "max": 0.01, "options": [], "description": "学习率", "required": False},
    {"name": "img_size", "type": "int", "label": "图像尺寸", "default": 256, "min": 128, "max": 512, "options": [], "description": "输入尺寸", "required": False},
    {"name": "train_ratio", "type": "float", "label": "训练集比例", "default": 0.7, "min": 0.5, "max": 0.9, "options": [], "description": "训练集占比", "required": False},
    {"name": "val_ratio", "type": "float", "label": "验证集比例", "default": 0.15, "min": 0.05, "max": 0.3, "options": [], "description": "验证集占比", "required": False},
]


def run(payload: dict, context) -> dict:
    try:
        return _run_training(payload, context)
    except Exception as exc:
        import traceback
        return {"ok": False, "error_code": "TRAINING_CRASH", "message": f"Training crashed: {exc}\n{traceback.format_exc()}"}


def _run_training(payload: dict, context) -> dict:
    params = payload.get("parameters", {}) or {}
    inp = payload.get("input", {})
    out_dir = Path(payload["output"]["output_dir"])
    out_dir.mkdir(parents=True, exist_ok=True)

    epochs = int(params.get("epochs", 30))
    batch_size = int(params.get("batch_size", 8))
    lr = float(params.get("learning_rate", 0.001))
    img_size = int(params.get("img_size", 256))
    train_ratio = float(params.get("train_ratio", 0.7))
    val_ratio = float(params.get("val_ratio", 0.15))

    # 找数据集目录
    samples = inp.get("samples", [])
    dataset_root = inp.get("dataset_path", "")
    image_dir, seg_dir, radar_dir = None, None, None

    for s in samples:
        fp = s.get("file_path", s.get("path", ""))
        rp = s.get("relative_path", "")
        if "SegmentationClass" in fp or "SegmentationClass" in rp:
            seg_dir = str(Path(fp).parent) if fp else ""
        elif "VOCradar320" in fp or "VOCradar320" in rp:
            radar_dir = str(Path(fp).parent) if fp else ""
        elif fp.lower().endswith((".jpg", ".png")) and "Segmentation" not in fp:
            image_dir = str(Path(fp).parent) if fp else ""

    if not image_dir and dataset_root:
        image_dir = os.path.join(dataset_root, "images")
        seg_dir = os.path.join(dataset_root, "semantic", "SegmentationClass", "SegmentationClass")
        radar_dir = os.path.join(dataset_root, "radar", "VOCradar320")

    if not image_dir or not os.path.isdir(image_dir):
        return {"ok": False, "error_code": "NO_IMAGES", "message": "未找到图片目录"}
    if not seg_dir or not os.path.isdir(seg_dir):
        return {"ok": False, "error_code": "NO_SEG", "message": "未找到分割标注目录"}

    image_files = sorted([f for f in os.listdir(image_dir) if f.lower().endswith(('.jpg', '.png'))])
    context.set_progress(1.0, f"图片: {len(image_files)}")

    # 收集配对
    paired = []
    for img_name in image_files:
        stem = os.path.splitext(img_name)[0]
        img_path = os.path.join(image_dir, img_name)
        seg_path = os.path.join(seg_dir, stem + ".png")
        if not os.path.isfile(seg_path):
            continue
        radar_path = None
        if radar_dir:
            rp = os.path.join(radar_dir, stem + ".npz")
            if os.path.isfile(rp):
                radar_path = rp
        paired.append({"img": img_path, "seg": seg_path, "radar": radar_path})

    if len(paired) < 10:
        return {"ok": False, "error_code": "INSUFFICIENT_DATA", "message": f"有效配对不足: {len(paired)}"}

    # 扫描所有mask构建调色板→类别ID映射 (修复P模式PNG被ToTensor÷255截断的问题)
    from PIL import Image
    all_palette_idx: set[int] = set()
    for p in paired:
        mask_arr = np.array(Image.open(p["seg"]))
        all_palette_idx.update(np.unique(mask_arr).tolist())
    all_palette_idx = sorted(all_palette_idx)
    palette_to_class = {v: i for i, v in enumerate(all_palette_idx)}
    nc = len(all_palette_idx)
    context.set_progress(2.0, f"配对: {len(paired)}, palette索引: {all_palette_idx}, 类别数: {nc} (雷达: {sum(1 for p in paired if p['radar'])} 组)")

    random.shuffle(paired)
    n = len(paired)
    tr_end = int(n * train_ratio)
    val_end = int(n * (train_ratio + val_ratio))
    train_data = paired[:tr_end]
    val_data = paired[tr_end:val_end]
    test_data = paired[val_end:]
    context.set_progress(3.0, f"train={len(train_data)} val={len(val_data)} test={len(test_data)}")

    # 模型: 多模态 UNet
    import torch; import torch.nn as nn; import torch.nn.functional as F
    from torch.utils.data import DataLoader, Dataset
    import torch.optim as optim

    class ConvBlock(nn.Module):
        def __init__(self, cin, cout):
            super().__init__()
            self.conv = nn.Sequential(nn.Conv2d(cin, cout, 3, padding=1), nn.BatchNorm2d(cout), nn.ReLU(),
                                       nn.Conv2d(cout, cout, 3, padding=1), nn.BatchNorm2d(cout), nn.ReLU())
        def forward(self, x): return self.conv(x)

    class MultiModalUNet(nn.Module):
        def __init__(self, num_classes):
            super().__init__()
            # Encoder (共享前半部分, 后半分开)
            self.enc1 = ConvBlock(3, 32)
            self.enc2 = ConvBlock(32, 64)
            self.enc3 = ConvBlock(64, 128)
            # 雷达编码器
            self.radar_enc = nn.Sequential(ConvBlock(3, 32), ConvBlock(32, 64), nn.AdaptiveAvgPool2d(1))
            # 融合
            self.fusion = nn.Linear(64, 128)
            # Decoder
            self.up2 = nn.ConvTranspose2d(128, 64, 2, 2)
            self.dec2 = ConvBlock(128, 64)
            self.up1 = nn.ConvTranspose2d(64, 32, 2, 2)
            self.dec1 = ConvBlock(64, 32)
            self.final = nn.Conv2d(32, num_classes, 1)
            self.pool = nn.MaxPool2d(2)

        def forward(self, x, radar=None):
            e1 = self.enc1(x)
            e2 = self.enc2(self.pool(e1))
            e3 = self.enc3(self.pool(e2))
            # 融合雷达特征
            if radar is not None:
                rf = self.radar_enc(radar).flatten(1)
                rf = self.fusion(rf).unsqueeze(-1).unsqueeze(-1)
                e3 = e3 + rf.expand_as(e3)
            d2 = self.up2(e3)
            d2 = self.dec2(torch.cat([d2, e2], dim=1))
            d1 = self.up1(d2)
            d1 = self.dec1(torch.cat([d1, e1], dim=1))
            return self.final(d1)

    device = _resolve_device(torch)
    model = MultiModalUNet(nc).to(device)
    context.set_progress(5.0, f"模型参数: {sum(p.numel() for p in model.parameters()):,}")

    # 数据集
    from torchvision import transforms as T
    img_tf = T.Compose([T.Resize((img_size, img_size)), T.ToTensor(), T.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225])])

    class SegDataset(Dataset):
        def __init__(self, data, palette_map, img_size):
            self.data = data
            self.img_size = img_size
            # 快速查找表: palette索引 → 连续class ID
            self.lut = np.zeros(256, dtype=np.int64)
            for old_val, new_val in palette_map.items():
                self.lut[old_val] = new_val

        def __len__(self):
            return len(self.data)

        def __getitem__(self, idx):
            item = self.data[idx]
            img = img_tf(Image.open(item["img"]).convert("RGB"))
            # 修复: 不用ToTensor处理mask(会÷255), 直接用np.array保留原始palette索引
            mask = np.array(Image.open(item["seg"]))
            mask_resized = np.array(Image.fromarray(mask).resize((self.img_size, self.img_size), Image.NEAREST))
            seg = torch.from_numpy(self.lut[mask_resized]).long()
            radar = torch.zeros(3, img_size, img_size)
            if item["radar"]:
                try:
                    rd = np.load(item["radar"])["arr_0"]
                    rd = torch.from_numpy(rd).float()
                    if rd.shape[1:] != (img_size, img_size):
                        rd = F.interpolate(rd.unsqueeze(0), size=(img_size, img_size))[0]
                    radar = rd
                except:
                    pass
            return img, radar, seg

    train_ds = SegDataset(train_data, palette_to_class, img_size)
    val_ds = SegDataset(val_data, palette_to_class, img_size)
    train_dl = DataLoader(train_ds, batch_size=batch_size, shuffle=True, num_workers=0)
    val_dl = DataLoader(val_ds, batch_size=batch_size, shuffle=False, num_workers=0)

    criterion = nn.CrossEntropyLoss()
    optimizer = optim.AdamW(model.parameters(), lr=lr)
    scheduler = optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=epochs)
    best_miou = 0; best_path = out_dir / "best_model.pth"
    patience = 0

    for ep in range(epochs):
        if context.is_cancel_requested():
            return {"ok": False, "error_code": "CANCELLED", "message": "训练已取消"}

        model.train(); tr_loss = 0
        for img, radar, seg in train_dl:
            img, seg = img.to(device), seg.to(device)
            radar = radar.to(device) if radar.sum() > 0 else None
            out = model(img, radar)
            loss = criterion(out, seg)
            optimizer.zero_grad(); loss.backward(); optimizer.step()
            tr_loss += loss.item()
        tr_loss /= len(train_dl)

        model.eval()
        val_miou = 0; val_count = 0
        with torch.no_grad():
            for img, radar, seg in val_dl:
                img, seg = img.to(device), seg.to(device)
                radar = radar.to(device) if radar.sum() > 0 else None
                out = model(img, radar)
                pred = out.argmax(1)
                for c in range(nc):
                    inter = ((pred == c) & (seg == c)).sum().item()
                    union = ((pred == c) | (seg == c)).sum().item()
                    if union > 0:
                        val_miou += inter / union
                        val_count += 1
        val_miou = val_miou / val_count if val_count > 0 else 0
        scheduler.step()

        if val_miou > best_miou:
            best_miou = val_miou; patience = 0
            torch.save({"model_state": model.state_dict(), "num_classes": nc,
                         "img_size": img_size, "palette_to_class": palette_to_class}, best_path)
        else:
            patience += 1

        pct = 8.0 + (ep + 1) / epochs * 88.0
        context.set_progress(pct, f"E{ep+1}/{epochs} loss={tr_loss:.4f} mIoU={val_miou:.4f}")
        if patience > 10: break

    # 保存测试数据
    np.savez(out_dir / "test_data.npz", test_paths=np.array([p["img"] for p in test_data]),
             test_segs=np.array([p["seg"] for p in test_data]))

    context.set_progress(98.0, f"最佳mIoU: {best_miou:.4f}")
    return {"ok": True, "outputs": [{"artifact_path": str(best_path),
        "metadata": {"best_miou": round(best_miou, 4), "num_classes": nc,
                     "train": len(train_data), "val": len(val_data), "test": len(test_data)}}],
        "logs": [f"MultiModal Seg: best_mIoU={best_miou:.4f}"]}
