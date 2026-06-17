"""
多模态数据融合检测评估插件。

加载训练产出checkpoint，在测试集上评估分类准确率。
"""
from __future__ import annotations
from pathlib import Path
import os, sys, json, logging
import numpy as np

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

PARAMETERS = [
    {"name": "batch_size", "type": "int", "label": "批大小", "default": 16, "min": 4, "max": 128, "options": [], "description": "评估批次大小", "required": False},
]


def run(payload: dict, context) -> dict:
    try:
        return _run_evaluation(payload, context)
    except Exception as exc:
        import traceback
        return {"ok": False, "error_code": "EVALUATION_CRASH", "message": f"Evaluation crashed: {exc}\n{traceback.format_exc()}"}


def _run_evaluation(payload: dict, context) -> dict:
    params = payload.get("parameters", {}) or {}
    out_dir = Path(payload["output"]["output_dir"])
    out_dir.mkdir(parents=True, exist_ok=True)

    checkpoint_path = params.get("model_checkpoint_path", "")
    if not checkpoint_path or not os.path.isfile(checkpoint_path):
        return {"ok": False, "error_code": "CHECKPOINT_NOT_FOUND", "message": f"模型文件不存在: {checkpoint_path}"}

    batch_size = int(params.get("batch_size", 16))
    train_out_dir = Path(checkpoint_path).resolve().parent
    test_npz = train_out_dir / "test_data.npz"
    if not test_npz.is_file():
        return {"ok": False, "error_code": "NO_TEST_DATA", "message": f"测试数据不存在: {test_npz}"}

    data = np.load(test_npz, allow_pickle=True)
    test_paths = data["test_pairs"]
    test_labels = json.loads(str(data["test_labels"]))
    context.set_progress(5.0, f"测试集: {len(test_paths)} 样本")

    # 加载模型
    import torch; import torch.nn as nn
    from torch.utils.data import DataLoader, Dataset
    from torchvision import transforms as T

    ckpt = torch.load(checkpoint_path, map_location="cpu")
    nc = ckpt["num_classes"]; img_size = ckpt["img_size"]
    class_names = ckpt.get("class_names", [])

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

    from plugins.training.multimodal_fusion_detector import _run_training
    # Recreate model (inline class)
    class MultiModalDetector(nn.Module):
        def __init__(self, num_classes, img_h, img_w):
            super().__init__()
            self.img_conv = nn.Sequential(
                nn.Conv2d(3, 32, 3, 2, 1), nn.BatchNorm2d(32), nn.ReLU(),
                nn.Conv2d(32, 64, 3, 2, 1), nn.BatchNorm2d(64), nn.ReLU(),
                nn.Conv2d(64, 128, 3, 2, 1), nn.BatchNorm2d(128), nn.ReLU(),
                nn.Conv2d(128, 256, 3, 2, 1), nn.BatchNorm2d(256), nn.ReLU(),
                nn.AdaptiveAvgPool2d(8),
            )
            self.radar_conv = nn.Sequential(
                nn.Conv2d(3, 32, 3, 2, 1), nn.BatchNorm2d(32), nn.ReLU(),
                nn.Conv2d(32, 64, 3, 2, 1), nn.BatchNorm2d(64), nn.ReLU(),
                nn.Conv2d(64, 128, 3, 2, 1), nn.BatchNorm2d(128), nn.ReLU(),
                nn.Conv2d(128, 256, 3, 2, 1), nn.BatchNorm2d(256), nn.ReLU(),
                nn.AdaptiveAvgPool2d(8),
            )
            self.cls_head = nn.Sequential(nn.Linear(256*64*2, 512), nn.ReLU(), nn.Dropout(0.3), nn.Linear(512, num_classes+1))
            self.bbox_head = nn.Sequential(nn.Linear(256*64*2, 512), nn.ReLU(), nn.Dropout(0.3), nn.Linear(512, 4*(num_classes+1)))
        def forward(self, img, radar=None):
            f_img = self.img_conv(img).flatten(1)
            f_radar = self.radar_conv(radar).flatten(1) if radar is not None else torch.zeros_like(f_img)
            f = torch.cat([f_img, f_radar], dim=1)
            return self.cls_head(f), self.bbox_head(f)

    model = MultiModalDetector(nc, img_size, img_size).to(device)
    model.load_state_dict(ckpt["model_state"])
    model.eval()
    context.set_progress(10.0, "模型加载完成")

    tf = T.Compose([T.Resize((img_size, img_size)), T.ToTensor(), T.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225])])

    correct, total = 0, 0
    all_preds, all_labels = [], []
    from PIL import Image

    batch_imgs, batch_cls = [], []
    for idx, img_path in enumerate(test_paths):
        if not os.path.isfile(img_path):
            continue
        img = tf(Image.open(img_path).convert("RGB")).unsqueeze(0).to(device)
        with torch.no_grad():
            cls_out, _ = model(img, None)
            pred = cls_out.argmax(1).item()
        label = test_labels[idx]["class_id"] if idx < len(test_labels) else 0
        correct += 1 if pred == label else 0
        total += 1
        all_preds.append(pred); all_labels.append(label)

    acc = correct / total * 100 if total > 0 else 0

    from sklearn.metrics import accuracy_score, f1_score
    macro_f1 = f1_score(all_labels, all_preds, average="macro") if len(set(all_labels)) > 1 else 0

    metrics = {
        "accuracy": round(acc, 2),
        "macro_f1": round(macro_f1, 4),
        "test_samples": total,
        "num_classes": nc,
    }
    summary = f"多模态融合检测: Acc={acc:.2f}% Macro-F1={macro_f1:.4f} classes={nc}"

    report_path = out_dir / "evaluation_report.json"
    report_path.write_text(json.dumps({"model": "multimodal-fusion", "checkpoint": os.path.basename(checkpoint_path), "metrics": metrics}, ensure_ascii=False, indent=2), encoding="utf-8")

    context.set_progress(100.0, "评估完成")
    return {"ok": True, "results": [{"model_name": "multimodal-fusion", "metrics": metrics, "summary": summary, "artifacts": [{"type": "report", "path": str(report_path)}]}]}
