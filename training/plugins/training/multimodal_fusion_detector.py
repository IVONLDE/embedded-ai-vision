"""
多模态数据融合检测训练插件 (图像+雷达)。

使用双流CNN分别提取RGB图像和雷达特征图，融合后进行目标检测。
数据集格式: WaterScenes (images/*.jpg + radar/VOCradar320/*.npz + detection/yolo/*.txt)
"""
from __future__ import annotations
from pathlib import Path
import os, sys, json, logging, random
import numpy as np

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

PARAMETERS = [
    {"name": "epochs", "type": "int", "label": "训练轮次", "default": 50, "min": 5, "max": 300, "options": [], "description": "训练epoch数量", "required": False},
    {"name": "batch_size", "type": "int", "label": "批大小", "default": 16, "min": 4, "max": 128, "options": [], "description": "批次大小", "required": False},
    {"name": "learning_rate", "type": "float", "label": "学习率", "default": 0.001, "min": 0.0001, "max": 0.1, "options": [], "description": "初始学习率", "required": False},
    {"name": "img_size", "type": "int", "label": "图像尺寸", "default": 320, "min": 160, "max": 640, "options": [], "description": "输入图像尺寸", "required": False},
    {"name": "train_ratio", "type": "float", "label": "训练集比例", "default": 0.7, "min": 0.5, "max": 0.9, "options": [], "description": "训练集占比", "required": False},
    {"name": "val_ratio", "type": "float", "label": "验证集比例", "default": 0.15, "min": 0.05, "max": 0.3, "options": [], "description": "验证集占比", "required": False},
]


def _normalize_parts(path_value: str) -> list[str]:
    return [part.lower() for part in Path(path_value).parts]


def _is_rgb_image_file(path_value: str) -> bool:
    parts = _normalize_parts(path_value)
    suffix = Path(path_value).suffix.lower()
    return suffix in {".jpg", ".jpeg", ".png"} and "images" in parts


def _is_radar_feature_file(path_value: str) -> bool:
    parts = _normalize_parts(path_value)
    return Path(path_value).suffix.lower() == ".npz" and "vocradar320" in parts


def _is_yolo_label_file(path_value: str) -> bool:
    parts = _normalize_parts(path_value)
    return Path(path_value).suffix.lower() == ".txt" and "detection" in parts and "yolo" in parts


def _resolve_dataset_dirs(dataset_root: str) -> tuple[str, str, str]:
    root = Path(dataset_root) if dataset_root else Path()
    candidates = [root]
    if root:
        candidates.extend([root / "raw", root / "raw" / "WaterScenes-Mini", root / "WaterScenes-Mini"])

    for candidate in candidates:
        image_dir = candidate / "images"
        radar_dir = candidate / "radar" / "VOCradar320"
        label_dir = candidate / "detection" / "detection" / "yolo"
        if image_dir.is_dir():
            return str(image_dir), str(radar_dir), str(label_dir)

    return "", "", ""


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

    epochs = int(params.get("epochs", 50))
    batch_size = int(params.get("batch_size", 16))
    lr = float(params.get("learning_rate", 0.001))
    img_size = int(params.get("img_size", 320))
    train_ratio = float(params.get("train_ratio", 0.7))
    val_ratio = float(params.get("val_ratio", 0.15))

    # ---- 构建样本列表 ----
    samples = inp.get("samples", [])
    dataset_root = inp.get("dataset_path", "")

    image_dir = None; radar_dir = None; label_dir = None
    for s in samples:
        rp = s.get("relative_path", "")
        fp = s.get("file_path", s.get("path", ""))
        source = fp or rp
        if _is_radar_feature_file(source):
            radar_dir = str(Path(fp).parent) if fp else ""
        elif _is_yolo_label_file(source):
            label_dir = str(Path(fp).parent) if fp else ""
        elif _is_rgb_image_file(source):
            image_dir = str(Path(fp).parent) if fp else ""

    # 回退: 从 dataset_path 推测
    if not image_dir and dataset_root:
        image_dir, radar_dir, label_dir = _resolve_dataset_dirs(dataset_root)

    # 最后一招: 遍历样本找 images 目录下的真图
    if not image_dir:
        for s in samples:
            fp = s.get("file_path", s.get("path", "")) or s.get("relative_path", "")
            if _is_rgb_image_file(fp):
                image_dir = str(Path(fp).parent)
                break

    if not image_dir or not os.path.isdir(image_dir):
        return {"ok": False, "error_code": "NO_IMAGES", "message": "未找到图片目录"}

    image_files = sorted([f for f in os.listdir(image_dir) if f.lower().endswith(('.jpg', '.png'))])
    context.set_progress(1.0, f"图片: {len(image_files)}")

    # 收集配对样本
    paired = []
    class_names = []
    for img_name in image_files:
        stem = os.path.splitext(img_name)[0]
        img_path = os.path.join(image_dir, img_name)

        radar_path = None
        if radar_dir:
            rp = os.path.join(radar_dir, stem + ".npz")
            if os.path.isfile(rp):
                radar_path = rp

        labels = []
        if label_dir:
            lp = os.path.join(label_dir, stem + ".txt")
            if os.path.isfile(lp):
                with open(lp) as f:
                    for line in f:
                        parts = line.strip().split()
                        if len(parts) >= 5:
                            cls_id = int(parts[0])
                            bbox = [float(x) for x in parts[1:5]]
                            labels.append({"class_id": cls_id, "bbox": bbox})

        if labels:
            paired.append({"img": img_path, "radar": radar_path, "labels": labels})
            for l in labels:
                cn = f"class_{l['class_id']}"
                if cn not in class_names:
                    class_names.append(cn)

    if len(paired) < 10:
        return {"ok": False, "error_code": "INSUFFICIENT_DATA", "message": f"有效配对样本不足: {len(paired)}"}

    class_names = sorted(class_names)
    nc = len(class_names)
    context.set_progress(2.0, f"配对: {len(paired)}, 类别: {nc} (雷达: {sum(1 for p in paired if p['radar'])} 组)")

    # 划分
    random.shuffle(paired)
    n = len(paired)
    tr_end = int(n * train_ratio)
    val_end = int(n * (train_ratio + val_ratio))
    train_data = paired[:tr_end]
    val_data = paired[tr_end:val_end]
    test_data = paired[val_end:]
    context.set_progress(3.0, f"train={len(train_data)} val={len(val_data)} test={len(test_data)}")

    # ---- 模型 ----
    import torch; import torch.nn as nn; import torch.optim as optim
    from torch.utils.data import DataLoader, Dataset
    from torchvision import transforms as T

    # 多模态检测模型
    class MultiModalDetector(nn.Module):
        def __init__(self, num_classes, img_h, img_w):
            super().__init__()
            # 图像分支: 轻量 CNN
            self.img_conv = nn.Sequential(
                nn.Conv2d(3, 32, 3, 2, 1), nn.BatchNorm2d(32), nn.ReLU(),
                nn.Conv2d(32, 64, 3, 2, 1), nn.BatchNorm2d(64), nn.ReLU(),
                nn.Conv2d(64, 128, 3, 2, 1), nn.BatchNorm2d(128), nn.ReLU(),
                nn.Conv2d(128, 256, 3, 2, 1), nn.BatchNorm2d(256), nn.ReLU(),
                nn.AdaptiveAvgPool2d(8),
            )
            # 雷达分支: 相同结构
            self.radar_conv = nn.Sequential(
                nn.Conv2d(3, 32, 3, 2, 1), nn.BatchNorm2d(32), nn.ReLU(),
                nn.Conv2d(32, 64, 3, 2, 1), nn.BatchNorm2d(64), nn.ReLU(),
                nn.Conv2d(64, 128, 3, 2, 1), nn.BatchNorm2d(128), nn.ReLU(),
                nn.Conv2d(128, 256, 3, 2, 1), nn.BatchNorm2d(256), nn.ReLU(),
                nn.AdaptiveAvgPool2d(8),
            )
            # 融合头: 分类 + bbox
            self.cls_head = nn.Sequential(
                nn.Linear(256 * 64 * 2, 512), nn.ReLU(), nn.Dropout(0.3),
                nn.Linear(512, num_classes + 1)  # +1 for background
            )
            self.bbox_head = nn.Sequential(
                nn.Linear(256 * 64 * 2, 512), nn.ReLU(), nn.Dropout(0.3),
                nn.Linear(512, 4 * (num_classes + 1))
            )

        def forward(self, img, radar=None):
            f_img = self.img_conv(img).flatten(1)
            if radar is not None:
                f_radar = self.radar_conv(radar).flatten(1)
                f = torch.cat([f_img, f_radar], dim=1)
            else:
                f = torch.cat([f_img, torch.zeros_like(f_img)], dim=1)
            cls_out = self.cls_head(f)
            bbox_out = self.bbox_head(f)
            return cls_out, bbox_out

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model = MultiModalDetector(nc, img_size, img_size).to(device)
    context.set_progress(5.0, f"模型参数: {sum(p.numel() for p in model.parameters()):,}")

    # ---- 数据加载 ----
    tf = T.Compose([T.Resize((img_size, img_size)), T.ToTensor(), T.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225])])

    class FusionDataset(Dataset):
        def __init__(self, data):
            self.data = data
        def __len__(self):
            return len(self.data)
        def __getitem__(self, idx):
            from PIL import Image
            item = self.data[idx]
            img = tf(Image.open(item["img"]).convert("RGB"))
            has_radar = 1.0 if item["radar"] else 0.0
            radar = torch.zeros(3, img_size, img_size)
            if item["radar"]:
                try:
                    rd = np.load(item["radar"])["arr_0"]
                    rd = torch.from_numpy(rd).float()
                    if rd.shape[1:] != (img_size, img_size):
                        rd = nn.functional.interpolate(rd.unsqueeze(0), size=(img_size, img_size))[0]
                    radar = rd
                except:
                    pass
            # 标签: 取第一个 bbox + class
            lbl = item["labels"][0]
            cls_id = lbl["class_id"]
            bbox = lbl["bbox"]  # YOLO format: cx,cy,w,h
            return img, radar, torch.tensor(has_radar), torch.tensor(cls_id, dtype=torch.long), torch.tensor(bbox, dtype=torch.float32)

    train_ds = FusionDataset(train_data)
    val_ds = FusionDataset(val_data)
    train_dl = DataLoader(train_ds, batch_size=batch_size, shuffle=True, num_workers=0)
    val_dl = DataLoader(val_ds, batch_size=batch_size, shuffle=False, num_workers=0)

    cls_criterion = nn.CrossEntropyLoss()
    bbox_criterion = nn.SmoothL1Loss()
    optimizer = optim.AdamW(model.parameters(), lr=lr, weight_decay=0.001)
    scheduler = optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=epochs)

    best_val_acc = 0; best_path = out_dir / "best_model.pth"
    patience = 0

    for ep in range(epochs):
        if context.is_cancel_requested():
            return {"ok": False, "error_code": "CANCELLED", "message": "训练已取消"}

        model.train()
        tr_loss, tr_acc = 0, 0
        for img, radar, has_r, cls_lbl, bbox_lbl in train_dl:
            img, radar, cls_lbl, bbox_lbl = img.to(device), radar.to(device), cls_lbl.to(device), bbox_lbl.to(device)
            use_radar = (has_r.mean() > 0.5)
            cls_out, bbox_out = model(img, radar if use_radar else None)
            # 修复: bbox_out(batch, 4*(nc+1)) → (batch, nc+1, 4), 按每个样本的类别取对应bbox
            bbox_out_reshaped = bbox_out.view(-1, nc + 1, 4)
            selected_bbox = bbox_out_reshaped[torch.arange(cls_lbl.size(0), device=device), cls_lbl]
            loss = cls_criterion(cls_out, cls_lbl) + bbox_criterion(selected_bbox, bbox_lbl)
            optimizer.zero_grad()
            loss.backward()
            optimizer.step()
            tr_loss += loss.item()
            tr_acc += (cls_out.argmax(1) == cls_lbl).float().mean().item()
        tr_loss /= len(train_dl)
        tr_acc = tr_acc / len(train_dl) * 100

        model.eval()
        val_acc = 0
        with torch.no_grad():
            for img, radar, has_r, cls_lbl, bbox_lbl in val_dl:
                img, radar, cls_lbl = img.to(device), radar.to(device), cls_lbl.to(device)
                use_radar = (has_r.mean() > 0.5)
                cls_out, _ = model(img, radar if use_radar else None)
                val_acc += (cls_out.argmax(1) == cls_lbl).float().mean().item()
        val_acc = val_acc / len(val_dl) * 100
        scheduler.step()

        if val_acc > best_val_acc:
            best_val_acc = val_acc; patience = 0
            torch.save({"model_state": model.state_dict(), "num_classes": nc, "class_names": class_names, "img_size": img_size}, best_path)
        else:
            patience += 1

        pct = 8.0 + (ep + 1) / epochs * 88.0
        context.set_progress(pct, f"E{ep+1}/{epochs} tr_acc={tr_acc:.1f}% val_acc={val_acc:.1f}%")
        if patience > 15:
            break

    # 保存测试集
    np.savez(out_dir / "test_data.npz", test_pairs=np.array([p["img"] for p in test_data]),
             test_labels=json.dumps([{"class_id": p["labels"][0]["class_id"], "bbox": p["labels"][0]["bbox"]} for p in test_data]))

    context.set_progress(98.0, f"最佳验证精度: {best_val_acc:.1f}%")
    return {"ok": True, "outputs": [{"artifact_path": str(best_path),
        "metadata": {"best_val_acc": round(best_val_acc, 2), "num_classes": nc, "class_names": class_names,
                     "train_count": len(train_data), "val_count": len(val_data), "test_count": len(test_data)}}],
        "logs": [f"MultiModal fusion: best_val_acc={best_val_acc:.1f}%"]}
