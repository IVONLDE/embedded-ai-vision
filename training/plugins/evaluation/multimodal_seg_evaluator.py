"""多模态语义分割评估插件。"""
from __future__ import annotations
from pathlib import Path
import os, sys, json, logging
import numpy as np

logging.basicConfig(level=logging.INFO)


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

PARAMETERS = [{"name": "batch_size", "type": "int", "label": "批大小", "default": 8, "min": 2, "max": 32, "options": [], "description": "评估批次", "required": False}]


def run(payload: dict, context) -> dict:
    try: return _run_evaluation(payload, context)
    except Exception as exc:
        import traceback
        return {"ok": False, "error_code": "EVALUATION_CRASH", "message": f"Eval crashed: {exc}\n{traceback.format_exc()}"}


def _run_evaluation(payload: dict, context) -> dict:
    params = payload.get("parameters", {}) or {}
    out_dir = Path(payload["output"]["output_dir"])
    out_dir.mkdir(parents=True, exist_ok=True)

    cp = params.get("model_checkpoint_path", "")
    if not cp or not os.path.isfile(cp):
        return {"ok": False, "error_code": "CHECKPOINT_NOT_FOUND", "message": f"模型不存在: {cp}"}

    batch_size = int(params.get("batch_size", 8))
    train_dir = Path(cp).resolve().parent
    test_npz = train_dir / "test_data.npz"
    if not test_npz.is_file():
        return {"ok": False, "error_code": "NO_TEST_DATA", "message": f"测试数据不存在"}

    data = np.load(test_npz, allow_pickle=True)
    test_paths = data["test_paths"]; test_segs = data["test_segs"]
    context.set_progress(5.0, f"测试: {len(test_paths)} 样本")

    import torch; import torch.nn as nn; import torch.nn.functional as F
    from torch.utils.data import DataLoader, Dataset
    from torchvision import transforms as T

    ckpt = torch.load(cp, map_location="cpu")
    nc = ckpt["num_classes"]; img_size = ckpt["img_size"]
    palette_to_class = ckpt.get("palette_to_class", None)
    device = _resolve_device(torch)

    # 重建模型
    class ConvBlock(nn.Module):
        def __init__(self, cin, cout):
            super().__init__()
            self.conv = nn.Sequential(nn.Conv2d(cin, cout, 3, padding=1), nn.BatchNorm2d(cout), nn.ReLU(),
                                       nn.Conv2d(cout, cout, 3, padding=1), nn.BatchNorm2d(cout), nn.ReLU())
        def forward(self, x): return self.conv(x)

    class MultiModalUNet(nn.Module):
        def __init__(self, nc):
            super().__init__()
            self.enc1 = ConvBlock(3, 32); self.enc2 = ConvBlock(32, 64); self.enc3 = ConvBlock(64, 128)
            self.radar_enc = nn.Sequential(ConvBlock(3, 32), ConvBlock(32, 64), nn.AdaptiveAvgPool2d(1))
            self.fusion = nn.Linear(64, 128)
            self.up2 = nn.ConvTranspose2d(128, 64, 2, 2); self.dec2 = ConvBlock(128, 64)
            self.up1 = nn.ConvTranspose2d(64, 32, 2, 2); self.dec1 = ConvBlock(64, 32)
            self.final = nn.Conv2d(32, nc, 1); self.pool = nn.MaxPool2d(2)
        def forward(self, x, radar=None):
            e1 = self.enc1(x); e2 = self.enc2(self.pool(e1)); e3 = self.enc3(self.pool(e2))
            if radar is not None:
                rf = self.radar_enc(radar).flatten(1); rf = self.fusion(rf).unsqueeze(-1).unsqueeze(-1)
                e3 = e3 + rf.expand_as(e3)
            d2 = self.up2(e3); d2 = self.dec2(torch.cat([d2, e2], dim=1))
            d1 = self.up1(d2); d1 = self.dec1(torch.cat([d1, e1], dim=1))
            return self.final(d1)

    model = MultiModalUNet(nc).to(device)
    model.load_state_dict(ckpt["model_state"]); model.eval()
    context.set_progress(10.0, "模型加载完成")

    from PIL import Image
    img_tf = T.Compose([T.Resize((img_size, img_size)), T.ToTensor(), T.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225])])

    # 构建palette→class查找表 (与训练时一致)
    if palette_to_class is None:
        # 旧版checkpoint兼容: 扫描所有测试mask自动构建
        print("[WARN] checkpoint无palette_to_class, 从测试mask自动扫描")
        palette_to_class = {}
        all_idx = set()
        for _, seg_p in zip(test_paths, test_segs):
            if os.path.isfile(seg_p):
                all_idx.update(np.array(Image.open(seg_p)).ravel().tolist())
        for i, v in enumerate(sorted(all_idx)):
            palette_to_class[v] = i
    lut = np.zeros(256, dtype=np.int64)
    for old_val, new_val in palette_to_class.items():
        lut[old_val] = new_val

    miou_sum, count = 0, 0
    per_class = {c: {"inter": 0, "union": 0} for c in range(nc)}
    for idx, (img_p, seg_p) in enumerate(zip(test_paths, test_segs)):
        if not os.path.isfile(img_p): continue
        img = img_tf(Image.open(img_p).convert("RGB")).unsqueeze(0).to(device)
        # 修复: np.array加载mask保留原始palette索引, 用LUT映射到连续class ID
        mask = np.array(Image.open(seg_p))
        mask = np.array(Image.fromarray(mask).resize((img_size, img_size), Image.NEAREST))
        seg = lut[mask]
        with torch.no_grad():
            pred = model(img, None).argmax(1).squeeze(0).cpu().numpy()
        for c in range(nc):
            inter = ((pred == c) & (seg == c)).sum()
            union = ((pred == c) | (seg == c)).sum()
            per_class[c]["inter"] += inter
            per_class[c]["union"] += union

    for c in range(nc):
        if per_class[c]["union"] > 0:
            miou_sum += per_class[c]["inter"] / per_class[c]["union"]
            count += 1
    miou = round(miou_sum / count, 4) if count > 0 else 0

    metrics = {"mIoU": miou, "num_classes": nc, "test_samples": len(test_paths)}
    summary = f"多模态语义分割: mIoU={miou:.4f} classes={nc}"

    report = out_dir / "report.json"
    report.write_text(json.dumps({"model": "multimodal-seg", "metrics": metrics}, indent=2, ensure_ascii=False), encoding="utf-8")

    context.set_progress(100.0, "评估完成")
    return {"ok": True, "results": [{"model_name": "multimodal-seg", "metrics": metrics, "summary": summary, "artifacts": [{"type": "report", "path": str(report)}]}]}
