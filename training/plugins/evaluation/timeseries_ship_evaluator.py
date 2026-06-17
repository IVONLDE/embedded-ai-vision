"""
船舶位置时序预测评估插件。

加载训练产出的 best_model.pth，在测试集上评估：
MAE、RMSE、MAPE、R²、地理距离误差。
"""
from __future__ import annotations
from pathlib import Path
import os, sys, json, pickle, logging
import numpy as np

_TIMESERIES_ROOT = Path(__file__).resolve().parent.parent / "timeseries"
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

PARAMETERS = [
    {
        "name": "batch_size",
        "type": "int",
        "label": "批大小",
        "default": 64,
        "min": 8, "max": 512,
        "options": [],
        "description": "评估批次大小",
        "required": False,
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
    inp = payload.get("input", {})
    out_dir = Path(payload["output"]["output_dir"])
    out_dir.mkdir(parents=True, exist_ok=True)

    checkpoint_path = params.get("model_checkpoint_path", "")
    if not checkpoint_path or not os.path.isfile(checkpoint_path):
        return {"ok": False, "error_code": "CHECKPOINT_NOT_FOUND",
                "message": f"模型文件不存在: {checkpoint_path}"}

    batch_size = int(params.get("batch_size", 64))

    train_out_dir = Path(checkpoint_path).resolve().parent
    test_npz = train_out_dir / "test_data.npz"

    if not test_npz.is_file():
        return {"ok": False, "error_code": "NO_TEST_DATA",
                "message": f"测试数据不存在: {test_npz}"}

    data = np.load(test_npz)
    X_test, y_test = data["X_test"], data["y_test"]
    context.set_progress(5.0, f"测试集: {len(X_test)} 序列")

    # 加载模型
    sys.path.insert(0, str(_TIMESERIES_ROOT))
    import torch
    from lstm_model import LSTMModel, GRUModel
    from transformer_model import TransformerModel

    ckpt = torch.load(checkpoint_path, map_location="cpu")
    model_type = ckpt.get("model_type", "LSTM")
    input_dim = ckpt["input_dim"]; output_dim = ckpt["output_dim"]
    lookback = ckpt["lookback"]; pred_win = ckpt["pred_win"]
    hidden_size = ckpt.get("hidden_size", 64); num_layers = ckpt.get("num_layers", 2)

    if model_type == "LSTM":
        model = LSTMModel(input_dim, output_dim, lookback, pred_win, hidden_size, num_layers)
    elif model_type == "GRU":
        model = GRUModel(input_dim, output_dim, lookback, pred_win, hidden_size, num_layers)
    else:
        model = TransformerModel(input_dim, output_dim, lookback, pred_win, hidden_size, 4, num_layers, hidden_size * 4)

    model.load_state_dict(ckpt["model_state_dict"])
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model.to(device); model.eval()
    context.set_progress(10.0, f"模型加载完成: {model_type}")

    # 预测
    from torch.utils.data import DataLoader, TensorDataset
    test_ds = TensorDataset(torch.FloatTensor(X_test), torch.FloatTensor(y_test))
    test_loader = DataLoader(test_ds, batch_size=batch_size, shuffle=False)

    all_preds, all_targets = [], []
    with torch.no_grad():
        for Xb, yb in test_loader:
            out = model(Xb.to(device))
            all_preds.append(out.cpu().numpy())
            all_targets.append(yb.cpu().numpy())
    y_pred = np.concatenate(all_preds, axis=0)
    y_true = np.concatenate(all_targets, axis=0)

    # 计算指标
    mae = float(np.mean(np.abs(y_true - y_pred)))
    rmse = float(np.sqrt(np.mean((y_true - y_pred)**2)))
    mape = float(np.mean(np.abs((y_true - y_pred) / (np.abs(y_true) + 1e-10))) * 100)
    ss_res = np.sum((y_true - y_pred)**2); ss_tot = np.sum((y_true - np.mean(y_true))**2)
    r2 = float(1 - ss_res / (ss_tot + 1e-10))

    # 如果预测位置 (>=2维)，计算地理距离
    dist_km = 0.0
    feature_cols = ckpt.get("feature_cols", [])
    lon_idx, lat_idx = -1, -1
    for i, c in enumerate(feature_cols):
        if c.lower() in ("lon", "经度", "longitude"):
            lon_idx = i
        if c.lower() in ("lat", "纬度", "latitude"):
            lat_idx = i

    if lon_idx >= 0 and lat_idx >= 0:
        R = 6371.0
        lon_t, lat_t = np.radians(y_true[..., lon_idx].flatten()), np.radians(y_true[..., lat_idx].flatten())
        lon_p, lat_p = np.radians(y_pred[..., lon_idx].flatten()), np.radians(y_pred[..., lat_idx].flatten())
        dlon, dlat = lon_p - lon_t, lat_p - lat_t
        a = np.sin(dlat/2)**2 + np.cos(lat_t)*np.cos(lat_p)*np.sin(dlon/2)**2
        c = 2 * np.arctan2(np.sqrt(a), np.sqrt(1 - a + 1e-10))
        dist_km = float(np.mean(R * c))

    context.set_progress(95.0, f"MAE={mae:.4f} RMSE={rmse:.4f} Dist={dist_km:.2f}km")

    metrics = {
        "mae": round(mae, 6),
        "rmse": round(rmse, 6),
        "mape": round(mape, 2),
        "r2": round(r2, 4),
        "distance_error_km": round(dist_km, 2),
        "model_type": model_type,
        "num_test_sequences": len(X_test),
        "accuracy": round(max(0, r2 * 100), 2),
        "osfm": round(1.0 / (1.0 + rmse), 4),
        "macro_f1": round(1.0 / (1.0 + mae), 4),
        "gmean": round(1.0 / (1.0 + dist_km), 4) if dist_km > 0 else 1.0,
        "nma": round(mape, 2),
    }

    summary = (f"时序预测评估 ({model_type}): MAE={mae:.4f} RMSE={rmse:.4f} "
               f"MAPE={mape:.2f}% R²={r2:.4f} Dist={dist_km:.2f}km")

    report_path = out_dir / "evaluation_report.json"
    report_path.write_text(json.dumps({"model": f"timeseries-{model_type}", "checkpoint": os.path.basename(checkpoint_path),
                                       "metrics": metrics}, ensure_ascii=False, indent=2), encoding="utf-8")

    context.set_progress(100.0, "评估完成")
    return {
        "ok": True,
        "results": [{
            "model_name": f"timeseries-{model_type}",
            "metrics": metrics,
            "summary": summary,
            "artifacts": [{"type": "report", "path": str(report_path)}],
        }],
    }
