"""
YOLOv5 目标检测评估插件。

加载训练产出的 best.pt，用验证集运行 YOLOv5 val.run()，
输出 mAP/P/R/F1 及混淆矩阵。
"""
from __future__ import annotations
from pathlib import Path
import os, sys, json, shutil, yaml


_YOLOV5_ROOT = Path(__file__).resolve().parent.parent / "detection" / "yolov5_core"

PARAMETERS = [
    {
        "name": "conf_thres",
        "type": "float",
        "label": "置信度阈值",
        "default": 0.001,
        "min": 0.0,
        "max": 1.0,
        "options": [],
        "description": "检测置信度阈值",
        "required": False,
    },
    {
        "name": "iou_thres",
        "type": "float",
        "label": "IoU 阈值",
        "default": 0.6,
        "min": 0.1,
        "max": 1.0,
        "options": [],
        "description": "NMS IoU 阈值",
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
        "description": "评估输入图像尺寸",
        "required": False,
    },
    {
        "name": "batch_size",
        "type": "int",
        "label": "批大小",
        "default": 32,
        "min": 1,
        "max": 256,
        "options": [],
        "description": "批次大小",
        "required": False,
    },
    {
        "name": "device",
        "type": "string",
        "label": "评估设备",
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
        return _run_evaluation(payload, context)
    except Exception as exc:
        import traceback
        return {
            "ok": False,
            "error_code": "EVALUATION_CRASH",
            "message": f"Evaluation crashed: {exc}\n{traceback.format_exc()}",
        }


def _run_evaluation(payload: dict, context) -> dict:
    params = payload.get("parameters", {}) or {}
    inp = payload.get("input", {})
    out_dir = Path(payload["output"]["output_dir"])
    out_dir.mkdir(parents=True, exist_ok=True)

    checkpoint_path = params.get("model_checkpoint_path", "")
    if not checkpoint_path or not os.path.isfile(checkpoint_path):
        return {"ok": False, "error_code": "CHECKPOINT_NOT_FOUND",
                "message": f"模型权重文件不存在: {checkpoint_path}"}

    conf_thres = float(params.get("conf_thres", 0.001))
    iou_thres = float(params.get("iou_thres", 0.6))
    img_size = int(params.get("img_size", 640))
    batch_size = int(params.get("batch_size", 32))
    device = str(params.get("device", "") or "")

    # 样本在 target_dataset 或 baseline_dataset 中
    target_data = inp.get("target_dataset", {})
    val_samples = target_data.get("samples", [])
    if not val_samples:
        baseline_data = inp.get("baseline_dataset", {})
        val_samples = baseline_data.get("samples", [])
    if not val_samples:
        return {"ok": False, "error_code": "NO_SAMPLES", "message": "评估数据集无样本"}

    # 尝试读取训练时保存的测试集路径，只评估测试集
    test_paths = None
    test_json = Path(checkpoint_path).resolve().parent.parent.parent.parent / "test_split.json"
    if test_json.is_file():
        try:
            test_paths = set(json.loads(test_json.read_text(encoding="utf-8")))
        except Exception:
            pass
    if test_paths:
        val_samples = [s for s in val_samples if (s.get("file_path") or s.get("path", "")) in test_paths]
        if not val_samples:
            return {"ok": False, "error_code": "NO_TEST_SAMPLES",
                    "message": f"测试集中无有效样本 (test_split 有 {len(test_paths)} 个路径)"}

    # 生成 YOLO 验证目录
    yolo_dir = out_dir / "yolo_val_data"
    val_img_dir = yolo_dir / "images"
    val_lbl_dir = yolo_dir / "labels"
    val_img_dir.mkdir(parents=True, exist_ok=True)
    val_lbl_dir.mkdir(parents=True, exist_ok=True)

    class_names = []
    valid_count = 0
    for s in val_samples:
        labels = _parse_labels(s.get("labels", []))
        src = s.get("path", s.get("file_path", ""))
        if not src or not os.path.isfile(src):
            continue

        bbox_lines = []
        for lbl in labels:
            cn = lbl.get("class_name", "")
            if cn and cn not in class_names:
                class_names.append(cn)
            bbox = lbl.get("bbox", [])
            if len(bbox) >= 4:
                cls_id = lbl.get("class_id", len(class_names) - 1)
                bbox_lines.append(f"{cls_id} {bbox[0]:.6f} {bbox[1]:.6f} {bbox[2]:.6f} {bbox[3]:.6f}\n")
        if not bbox_lines:
            continue

        name = s.get("name", os.path.basename(src))
        stem = os.path.splitext(name)[0]
        dst = val_img_dir / name
        if not dst.exists():
            try:
                os.link(src, dst)
            except OSError:
                shutil.copy2(src, dst)
        with open(val_lbl_dir / f"{stem}.txt", "w", encoding="utf-8") as f:
            f.writelines(bbox_lines)
        valid_count += 1

    if not class_names:
        class_names = ["ship"]

    data_yaml_path = out_dir / "val_data.yaml"
    with open(data_yaml_path, "w", encoding="utf-8") as f:
        yaml.dump({
            "path": str(yolo_dir),
            "train": "images",
            "val": "images",
            "nc": len(class_names),
            "names": class_names,
        }, f)

    context.set_progress(10.0, f"验证样本: {valid_count}, {len(class_names)} 类")

    # 导入 YOLOv5
    if str(_YOLOV5_ROOT) not in sys.path:
        sys.path.insert(0, str(_YOLOV5_ROOT))
    import torch
    import val as yolo_val

    device_str = device or ("0" if torch.cuda.is_available() else "cpu")
    context.set_progress(15.0, f"YOLOv5 评估启动: {checkpoint_path}")

    try:
        result = yolo_val.run(
            data=str(data_yaml_path),
            weights=checkpoint_path,
            batch_size=batch_size,
            imgsz=img_size,
            conf_thres=conf_thres,
            iou_thres=iou_thres,
            task="val",
            device=device_str,
            workers=0,
            save_txt=False,
            save_json=False,
            save_hybrid=False,
            project=str(out_dir / "runs"),
            name="val",
            exist_ok=True,
            half=True,
            plots=True,
        )
    except Exception as exc:
        import traceback
        return {"ok": False, "error_code": "EVALUATION_FAILED",
                "message": f"YOLOv5 评估失败: {exc}\n{traceback.format_exc()}"}

    # 解析指标
    metrics_raw, maps_per_class, times = result
    mp = float(metrics_raw[0]) if len(metrics_raw) > 0 else 0.0
    mr = float(metrics_raw[1]) if len(metrics_raw) > 1 else 0.0
    map50 = float(metrics_raw[2]) if len(metrics_raw) > 2 else 0.0
    map_val = float(metrics_raw[3]) if len(metrics_raw) > 3 else 0.0
    f1 = (2.0 * mp * mr / (mp + mr)) if (mp + mr) > 0 else 0.0

    per_class_ap = {}
    maps_list = maps_per_class.tolist() if hasattr(maps_per_class, "tolist") else (maps_per_class if isinstance(maps_per_class, list) else [])
    for i, ap in enumerate(maps_list):
        if i < len(class_names):
            per_class_ap[class_names[i]] = round(float(ap), 4)

    cm_img_path = ""
    save_dir_val = out_dir / "runs" / "val"
    cm_candidates = list(save_dir_val.glob("confusion_matrix*.png"))
    if cm_candidates:
        cm_img_path = str(cm_candidates[0])

    context.set_progress(95.0, f"mAP@0.5={map50:.4f} F1={f1:.4f}")

    import math
    metrics = {
        "precision": round(mp * 100, 2),
        "recall": round(mr * 100, 2),
        "f1_score": round(f1, 4),
        "map50": round(map50, 4),
        "map": round(map_val, 4),
        "num_classes": len(class_names),
        "class_names": class_names,
        "per_class_ap": per_class_ap,
        "accuracy": round(map50 * 100, 2),
        "osfm": round(f1, 4),
        "macro_f1": round(f1, 4),
        "gmean": round(math.sqrt(max(mp * mr, 0)), 4),
        "nma": round(map_val * 100, 2),
    }

    report = {"model": "yolov5-detector", "checkpoint": os.path.basename(checkpoint_path), "metrics": metrics}
    report_path = out_dir / "yolov5_evaluation_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    summary = (
        f"YOLOv5 检测评估: P={mp*100:.1f}% R={mr*100:.1f}% F1={f1:.4f} "
        f"mAP@0.5={map50:.4f} mAP@0.5:0.95={map_val:.4f}"
    )

    artifacts = [{"type": "report", "path": str(report_path)}]
    if cm_img_path:
        artifacts.append({"type": "confusion_matrix", "path": cm_img_path})

    context.set_progress(100.0, "评估完成")
    return {
        "ok": True,
        "results": [{
            "model_name": "yolov5-detector",
            "metrics": metrics,
            "summary": summary,
            "artifacts": artifacts,
        }],
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
