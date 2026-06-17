"""
YOLOv5 目标检测训练插件。

从数据集样本的 labels_json 中提取 bbox 标注，生成 YOLO 格式数据，
调用内嵌 YOLOv5 引擎进行训练。
"""
from __future__ import annotations
from pathlib import Path
import os, sys, shutil, json, yaml


_YOLOV5_ROOT = Path(__file__).resolve().parent.parent / "detection" / "yolov5_core"

PARAMETERS = [
    {
        "name": "weights",
        "type": "string",
        "label": "预训练权重",
        "default": "yolov5n.pt",
        "min": None,
        "max": None,
        "options": ["yolov5n.pt", "yolov5s.pt", "yolov5m.pt", "yolov5l.pt", "yolov5x.pt", ""],
        "description": "预训练权重文件 (yolov5n/s/m/l/x.pt，空字符串=从头训练)",
        "required": False,
    },
    {
        "name": "model_yaml",
        "type": "string",
        "label": "模型配置",
        "default": "models/yolov5n.yaml",
        "min": None,
        "max": None,
        "options": ["models/yolov5n.yaml", "models/yolov5s.yaml", "models/yolov5m.yaml", "models/yolov5l.yaml", "models/yolov5x.yaml"],
        "description": "YOLOv5 模型配置文件",
        "required": False,
    },
    {
        "name": "epochs",
        "type": "int",
        "label": "训练轮次",
        "default": 100,
        "min": 1,
        "max": 1000,
        "options": [],
        "description": "训练 epoch 数量",
        "required": False,
    },
    {
        "name": "batch_size",
        "type": "int",
        "label": "批大小",
        "default": 16,
        "min": 1,
        "max": 256,
        "options": [],
        "description": "批次大小",
        "required": False,
    },
    {
        "name": "img_size",
        "type": "int",
        "label": "图像尺寸",
        "default": 640,
        "min": 320,
        "max": 1280,
        "options": [],
        "description": "训练输入图像尺寸 (像素)",
        "required": False,
    },
    {
        "name": "train_ratio",
        "type": "float",
        "label": "训练集比例",
        "default": 0.7,
        "min": 0.1,
        "max": 0.9,
        "options": [],
        "description": "数据集划分中训练集占比",
        "required": False,
    },
    {
        "name": "val_ratio",
        "type": "float",
        "label": "验证集比例",
        "default": 0.15,
        "min": 0.05,
        "max": 0.5,
        "options": [],
        "description": "数据集划分中验证集占比 (测试集=1-train_ratio-val_ratio)",
        "required": False,
    },
    {
        "name": "device",
        "type": "string",
        "label": "训练设备",
        "default": "",
        "min": None,
        "max": None,
        "options": ["", "0", "1", "cpu"],
        "description": "GPU 设备号 (空=自动选择)",
        "required": False,
    },
]


def run(payload: dict, context) -> dict:
    try:
        return _run_training(payload, context)
    except Exception as exc:
        import traceback
        return {
            "ok": False,
            "error_code": "TRAINING_CRASH",
            "message": f"Training crashed: {exc}\n{traceback.format_exc()}",
        }


def _run_training(payload: dict, context) -> dict:
    params = payload.get("parameters", {}) or {}
    inp = payload.get("input", {})
    out_dir = Path(payload["output"]["output_dir"])
    out_dir.mkdir(parents=True, exist_ok=True)

    epochs = int(params.get("epochs", 100))
    batch_size = int(params.get("batch_size", 16))
    img_size = int(params.get("img_size", 640))
    device = str(params.get("device", "") or "")
    weights = str(params.get("weights", "yolov5n.pt") or "yolov5n.pt")
    model_cfg = str(params.get("model_yaml", "models/yolov5n.yaml") or "models/yolov5n.yaml")
    train_ratio = float(params.get("train_ratio", 0.7))
    val_ratio = float(params.get("val_ratio", 0.15))

    samples = inp.get("samples", [])
    if not samples:
        return {"ok": False, "error_code": "NO_SAMPLES", "message": "数据集无样本"}

    # 从样本 labels 提取 bbox，跳过无 bbox 的样本
    valid_samples = []
    for s in samples:
        labels = _parse_labels(s.get("labels", []))
        bboxes = [l for l in labels if len(l.get("bbox", [])) >= 4]
        if bboxes:
            valid_samples.append({**s, "_bboxes": bboxes})
    if not valid_samples:
        return {"ok": False, "error_code": "NO_BBOX",
                "message": f"数据集 {len(samples)} 个样本中未找到 bbox 标注，YOLOv5 需要目标检测标注"}

    context.set_progress(1.0, f"有效样本: {len(valid_samples)}/{len(samples)}")

    # 按类别随机划分训练/验证/测试集
    train_samples, val_samples, test_samples = _split_train_val_test(valid_samples, train_ratio, val_ratio)
    context.set_progress(2.0, f"train={len(train_samples)} val={len(val_samples)} test={len(test_samples)}")

    # 保存测试集文件路径，供评估插件读取
    test_paths_file = out_dir / "test_split.json"
    test_paths_file.write_text(json.dumps([s.get("file_path", s.get("path", "")) for s in test_samples]),
                               encoding="utf-8")

    # 收集类别
    class_names = _collect_class_names(valid_samples)
    context.set_progress(3.0, f"类别: {class_names}")

    # 生成 YOLO 数据目录
    yolo_dir = out_dir / "yolo_data"
    yolo_dir.mkdir(parents=True, exist_ok=True)
    _write_yolo_split(train_samples, yolo_dir / "train" / "images", yolo_dir / "train" / "labels")
    _write_yolo_split(val_samples, yolo_dir / "val" / "images", yolo_dir / "val" / "labels")
    if test_samples:
        _write_yolo_split(test_samples, yolo_dir / "test" / "images", yolo_dir / "test" / "labels")

    # 生成 data.yaml
    data_yaml = out_dir / "data.yaml"
    yaml_data = {
        "path": str(yolo_dir),
        "train": "train/images",
        "val": "val/images",
        "nc": len(class_names),
        "names": class_names,
    }
    if test_samples:
        yaml_data["test"] = "test/images"
    with open(data_yaml, "w", encoding="utf-8") as f:
        yaml.dump(yaml_data, f)

    # 权重和模型配置路径
    weights_path = _YOLOV5_ROOT / weights
    weights_arg = str(weights_path) if weights_path.is_file() else weights
    model_cfg_path = _YOLOV5_ROOT / model_cfg
    model_cfg_arg = str(model_cfg_path) if model_cfg_path.is_file() else ""

    # 导入 YOLOv5
    if str(_YOLOV5_ROOT) not in sys.path:
        sys.path.insert(0, str(_YOLOV5_ROOT))
    import torch
    import train as yolo_train
    from utils.callbacks import Callbacks

    callbacks = Callbacks()

    def _check_cancel(*args, **kwargs):
        if context.is_cancel_requested():
            callbacks.stop_training = True
    callbacks.register_action("on_train_batch_end", callback=_check_cancel)

    class _EpochTracker:
        def __init__(self): self.current = 0
    tracker = _EpochTracker()

    def _report_progress(*args):
        tracker.current = args[1] if len(args) > 1 else tracker.current + 1
        pct = min(5.0 + tracker.current / epochs * 93.0, 98.0)
        context.set_progress(pct, f"Epoch {tracker.current}/{epochs}")
    callbacks.register_action("on_fit_epoch_end", callback=_report_progress)

    context.set_progress(4.0, f"YOLOv5 训练启动: epochs={epochs} batch={batch_size} imgsz={img_size}")
    device_str = device or ("0" if torch.cuda.is_available() else "cpu")

    try:
        opt = yolo_train.run(
            data=str(data_yaml),
            weights=weights_arg,
            cfg=model_cfg_arg,
            epochs=epochs,
            batch_size=batch_size,
            imgsz=img_size,
            device=device_str,
            project=str(out_dir / "runs"),
            name="train",
            exist_ok=True,
            nosave=False,
            noval=True,
            workers=0,
            cache=False,
            callbacks=callbacks,
        )
    except Exception as exc:
        import traceback
        return {"ok": False, "error_code": "TRAINING_FAILED",
                "message": f"YOLOv5 训练失败: {exc}\n{traceback.format_exc()}"}

    if context.is_cancel_requested():
        return {"ok": False, "error_code": "CANCELLED", "message": "训练已被用户取消"}

    # 查找 best.pt
    save_dir = Path(opt.save_dir) if hasattr(opt, "save_dir") else (out_dir / "runs" / "train")
    best_pt = save_dir / "weights" / "best.pt"
    if not best_pt.is_file():
        candidates = list(save_dir.rglob("best.pt"))
        if candidates:
            best_pt = candidates[0]
    if not best_pt.is_file():
        return {"ok": False, "error_code": "CHECKPOINT_NOT_FOUND",
                "message": f"未找到 best.pt: {save_dir}"}

    context.set_progress(100.0, "训练完成")
    return {
        "ok": True,
        "outputs": [{
            "artifact_path": str(best_pt),
            "metadata": {
                "backbone": "yolov5",
                "epochs": epochs,
                "img_size": img_size,
                "class_names": class_names,
                "train_count": len(train_samples),
                "val_count": len(val_samples),
                "test_count": len(test_samples),
            },
        }],
        "logs": [f"YOLOv5 complete: {best_pt}"],
    }


def _parse_labels(raw_labels):
    if isinstance(raw_labels, str):
        try:
            raw_labels = json.loads(raw_labels)
        except (json.JSONDecodeError, TypeError):
            return []
    if not isinstance(raw_labels, list):
        return []
    return [l for l in raw_labels if isinstance(l, dict)]


def _split_train_val_test(samples, train_ratio, val_ratio):
    """按类别随机划分训练/验证/测试集。"""
    import random
    by_class = {}
    for s in samples:
        bboxes = s.get("_bboxes", [])
        cn = bboxes[0].get("class_name", "unknown") if bboxes else "unknown"
        by_class.setdefault(cn, []).append(s)

    train, val, test = [], [], []
    for items in by_class.values():
        random.shuffle(items)
        n = len(items)
        nt = max(1, int(n * train_ratio))
        nv = max(1, int(n * val_ratio))
        if nt + nv >= n:
            nt = max(1, n - 2)
            nv = max(1, n - nt - 1)
        train.extend(items[:nt])
        val.extend(items[nt:nt + nv])
        test.extend(items[nt + nv:])
    return train, val, test


def _collect_class_names(samples):
    names = []
    for s in samples:
        for lbl in s.get("_bboxes", []):
            cn = lbl.get("class_name", "")
            if cn and cn not in names:
                names.append(str(cn))
    return names if names else ["ship"]


def _write_yolo_split(samples, img_dir, lbl_dir):
    img_dir.mkdir(parents=True, exist_ok=True)
    lbl_dir.mkdir(parents=True, exist_ok=True)

    for s in samples:
        src = s.get("path", s.get("file_path", ""))
        if not src or not os.path.isfile(src):
            continue

        bboxes = s.get("_bboxes", [])
        if not bboxes:
            continue

        name = s.get("name", os.path.basename(src))
        stem = os.path.splitext(name)[0]
        dst_img = img_dir / name
        if not dst_img.exists():
            try:
                os.link(src, dst_img)
            except OSError:
                shutil.copy2(src, dst_img)

        cls_to_id = {}
        lines = []
        for lbl in bboxes:
            cn = lbl.get("class_name", "ship")
            if cn not in cls_to_id:
                cls_to_id[cn] = len(cls_to_id)
            cid = cls_to_id[cn]
            bbox = lbl.get("bbox", [])
            lines.append(f"{cid} {bbox[0]:.6f} {bbox[1]:.6f} {bbox[2]:.6f} {bbox[3]:.6f}\n")

        with open(lbl_dir / f"{stem}.txt", "w", encoding="utf-8") as f:
            f.writelines(lines)
