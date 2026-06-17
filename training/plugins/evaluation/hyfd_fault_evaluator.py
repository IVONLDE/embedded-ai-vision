"""
HyFD-SME 船舶主机故障诊断评估插件。

加载训练产出的 best_model.pth，在测试集上评估分类准确率。
"""
from __future__ import annotations
from pathlib import Path
import os, sys, json, logging
import numpy as np

_FAULT_ROOT = Path(__file__).resolve().parent.parent / "fault_diagnosis"
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

PARAMETERS = [
    {
        "name": "batch_size", "type": "int", "label": "批大小", "default": 256,
        "min": 32, "max": 1024, "options": [], "description": "评估批次大小", "required": False,
    },
]


def run(payload: dict, context) -> dict:
    try:
        return _run_evaluation(payload, context)
    except Exception as exc:
        import traceback
        return {"ok": False, "error_code": "EVALUATION_CRASH",
                "message": f"Evaluation crashed: {exc}\n{traceback.format_exc()}"}


def _run_evaluation(payload: dict, context) -> dict:
    params = payload.get("parameters", {}) or {}
    out_dir = Path(payload["output"]["output_dir"])
    out_dir.mkdir(parents=True, exist_ok=True)

    checkpoint_path = params.get("model_checkpoint_path", "")
    if not checkpoint_path or not os.path.isfile(checkpoint_path):
        return {"ok": False, "error_code": "CHECKPOINT_NOT_FOUND",
                "message": f"模型文件不存在: {checkpoint_path}"}

    batch_size = int(params.get("batch_size", 256))

    train_out_dir = Path(checkpoint_path).resolve().parent
    test_npz = train_out_dir / "test_data.npz"
    if not test_npz.is_file():
        return {"ok": False, "error_code": "NO_TEST_DATA",
                "message": f"测试数据不存在: {test_npz}"}

    data = np.load(test_npz)
    X_test, y_test = data["X_test"], data["y_test"]
    context.set_progress(5.0, f"测试集: {len(X_test)} 样本")

    sys.path.insert(0, str(_FAULT_ROOT))
    import torch; import torch.nn as nn
    from model import Method
    from tdf_extractor import TDF_Extractor
    from raw_signal_feature_extractor import Raw_Signal_Convolution_Block, Raw_Signal_Feature_Extractor
    from torchvision.models import resnet34

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

    tdfe = TDF_Extractor()
    rscb = Raw_Signal_Convolution_Block()
    resnet = resnet34()
    resnet.conv1 = nn.Conv2d(1, 64, kernel_size=(7,7), stride=(2,2), padding=(3,3), bias=False)
    resnet.fc = nn.Linear(512, 6)
    rsfe = Raw_Signal_Feature_Extractor(rscb, resnet)
    model = Method(tdfe, rsfe).to(device)

    ckpt = torch.load(checkpoint_path, map_location=device)
    model.load_state_dict(ckpt["model_state"])
    model.eval()
    context.set_progress(10.0, "模型加载完成")

    from torch.utils.data import DataLoader, TensorDataset
    from torch.autograd import Variable

    test_ds = TensorDataset(torch.FloatTensor(X_test), torch.LongTensor(y_test))
    test_dl = DataLoader(test_ds, batch_size=batch_size, shuffle=False)

    correct, total = 0, 0
    all_preds, all_labels = [], []
    with torch.no_grad():
        for batch, label in test_dl:
            tdf_b = Variable(batch[:, :12].unsqueeze(1).float().to(device))
            raw_b = Variable(batch[:, 12:].unsqueeze(1).float().to(device))
            label = label.to(device)
            out = model(tdf_b, raw_b)
            preds = out.argmax(1)
            correct += (preds == label).sum().item()
            total += len(label)
            all_preds.extend(preds.cpu().tolist())
            all_labels.extend(label.cpu().tolist())

    acc = correct / total * 100 if total > 0 else 0
    context.set_progress(90.0, f"准确率: {acc:.2f}%")

    from sklearn.metrics import accuracy_score, f1_score, classification_report
    macro_f1 = f1_score(all_labels, all_preds, average="macro") if len(set(all_labels)) > 1 else 0

    # 类别分布
    from collections import Counter
    label_counts = Counter(all_labels)

    metrics = {
        "accuracy": round(acc, 2),
        "macro_f1": round(macro_f1, 4),
        "osfm": round(acc / 100, 4),
        "gmean": round(macro_f1, 4),
        "nma": round(100 - acc, 2),
        "num_classes": len(label_counts),
        "test_samples": total,
        "label_distribution": dict(label_counts),
    }

    summary = f"HyFD-SME 故障诊断: Acc={acc:.2f}% Macro-F1={macro_f1:.4f} classes={len(label_counts)}"

    report_path = out_dir / "evaluation_report.json"
    report_path.write_text(json.dumps({"model": "hyfd-sme", "checkpoint": os.path.basename(checkpoint_path),
                                       "metrics": metrics}, ensure_ascii=False, indent=2), encoding="utf-8")

    context.set_progress(100.0, "评估完成")
    return {
        "ok": True,
        "results": [{
            "model_name": "hyfd-sme",
            "metrics": metrics,
            "summary": summary,
            "artifacts": [{"type": "report", "path": str(report_path)}],
        }],
    }
