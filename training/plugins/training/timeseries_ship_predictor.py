"""
船舶位置时序预测训练插件 (LSTM/GRU/Transformer)。

从数据集的 CSV 文件中读取船舶 AIS 数据（经度、纬度、航速、航向），
构建时序序列，训练深度学习模型预测船舶未来位置。
"""
from __future__ import annotations
from pathlib import Path
import os, sys, json, pickle, logging
import numpy as np
import pandas as pd

_TIMESERIES_ROOT = Path(__file__).resolve().parent.parent / "timeseries"
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

PARAMETERS = [
    {
        "name": "model_type",
        "type": "string",
        "label": "模型类型",
        "default": "LSTM",
        "min": None, "max": None,
        "options": ["LSTM", "GRU", "TRANSFORMER"],
        "description": "时序预测模型架构",
        "required": False,
    },
    {
        "name": "hidden_size",
        "type": "int",
        "label": "隐藏层大小",
        "default": 64,
        "min": 16, "max": 512,
        "options": [],
        "description": "LSTM/GRU 隐藏单元数 或 Transformer d_model",
        "required": False,
    },
    {
        "name": "num_layers",
        "type": "int",
        "label": "网络层数",
        "default": 2,
        "min": 1, "max": 8,
        "options": [],
        "description": "循环层或 Transformer 层数",
        "required": False,
    },
    {
        "name": "epochs",
        "type": "int",
        "label": "训练轮次",
        "default": 50,
        "min": 1, "max": 500,
        "options": [],
        "description": "训练 epoch 数量",
        "required": False,
    },
    {
        "name": "batch_size",
        "type": "int",
        "label": "批大小",
        "default": 64,
        "min": 8, "max": 512,
        "options": [],
        "description": "批次大小",
        "required": False,
    },
    {
        "name": "learning_rate",
        "type": "float",
        "label": "学习率",
        "default": 0.001,
        "min": 0.00001, "max": 0.1,
        "options": [],
        "description": "优化器学习率",
        "required": False,
    },
    {
        "name": "lookback_window",
        "type": "int",
        "label": "回顾窗口",
        "default": 20,
        "min": 5, "max": 100,
        "options": [],
        "description": "用过去多少个时间步预测未来",
        "required": False,
    },
    {
        "name": "prediction_window",
        "type": "int",
        "label": "预测窗口",
        "default": 10,
        "min": 1, "max": 50,
        "options": [],
        "description": "预测未来多少个时间步",
        "required": False,
    },
    {
        "name": "train_ratio",
        "type": "float",
        "label": "训练集比例",
        "default": 0.7,
        "min": 0.3, "max": 0.9,
        "options": [],
        "description": "数据集划分中训练集占比",
        "required": False,
    },
    {
        "name": "val_ratio",
        "type": "float",
        "label": "验证集比例",
        "default": 0.15,
        "min": 0.05, "max": 0.4,
        "options": [],
        "description": "数据集划分中验证集占比 (测试集=1-train_ratio-val_ratio)",
        "required": False,
    },
]


def run(payload: dict, context) -> dict:
    try:
        return _run_training(payload, context)
    except Exception as exc:
        import traceback
        return {"ok": False, "error_code": "TRAINING_CRASH",
                "message": f"Training crashed: {exc}\n{traceback.format_exc()}"}


def _run_training(payload: dict, context) -> dict:
    params = payload.get("parameters", {}) or {}
    inp = payload.get("input", {})
    out_dir = Path(payload["output"]["output_dir"])
    out_dir.mkdir(parents=True, exist_ok=True)

    model_type = str(params.get("model_type", "LSTM")).upper()
    hidden_size = int(params.get("hidden_size", 64))
    num_layers = int(params.get("num_layers", 2))
    epochs = int(params.get("epochs", 50))
    batch_size = int(params.get("batch_size", 64))
    lr = float(params.get("learning_rate", 0.001))
    lookback = int(params.get("lookback_window", 20))
    pred_win = int(params.get("prediction_window", 10))
    train_ratio = float(params.get("train_ratio", 0.7))
    val_ratio = float(params.get("val_ratio", 0.15))

    # 从数据集找 CSV 文件
    samples = inp.get("samples", [])
    csv_path = None
    for s in samples:
        fp = s.get("file_path", s.get("path", ""))
        if fp.lower().endswith(".csv") and os.path.isfile(fp):
            csv_path = fp
            break
    if not csv_path:
        return {"ok": False, "error_code": "NO_CSV", "message": "数据集中未找到 CSV 文件，时序预测需要 AIS 数据"}

    context.set_progress(1.0, f"加载数据: {csv_path}")

    # 加载 CSV
    data = pd.read_csv(csv_path)
    # 自动检测列名 (支持中英文)
    feature_cols = []
    for candidate in [["lon", "lat", "sog", "cog"], ["经度", "纬度", "航速", "航向"],
                       ["longitude", "latitude", "speed", "course"], ["longitude", "latitude", "speed", "heading"],
                       ["LON", "LAT", "SOG", "COG"]]:
        if all(c in data.columns for c in candidate):
            feature_cols = candidate
            break
    if not feature_cols:
        feature_cols = list(data.columns[:4])
        logger.warning(f"未识别标准列名，使用前4列: {feature_cols}")

    data = data[feature_cols].dropna()
    if len(data) < lookback + pred_win + 10:
        return {"ok": False, "error_code": "INSUFFICIENT_DATA",
                "message": f"有效数据不足: {len(data)} 行, 需要 >={lookback + pred_win}"}

    context.set_progress(3.0, f"数据: {len(data)} 行, 特征: {feature_cols}")

    # 标准化
    mean = data.mean().values.astype(np.float32)
    std = data.std().values.astype(np.float32)
    std[std < 1e-8] = 1.0
    values = ((data.values - mean) / std).astype(np.float32)

    # 按时序划分 (不随机)
    n = len(values)
    tr_end = int(n * train_ratio)
    val_end = int(n * (train_ratio + val_ratio))
    train_data = values[:tr_end]
    val_data = values[tr_end:val_end]
    test_data = values[val_end:]

    # 构建序列
    X_train, y_train = _build_sequences(train_data, lookback, pred_win)
    X_val, y_val = _build_sequences(val_data, lookback, pred_win)
    X_test, y_test = _build_sequences(test_data, lookback, pred_win)

    context.set_progress(5.0, f"序列: train={len(X_train)} val={len(X_val)} test={len(X_test)}")

    # 保存测试集和预处理器
    _save_preprocessor(out_dir, mean, std, feature_cols, lookback, pred_win)
    np.savez(out_dir / "test_data.npz", X_test=X_test, y_test=y_test)

    # 创建模型
    sys.path.insert(0, str(_TIMESERIES_ROOT))
    import torch
    from base_model import BaseTimeSeriesModel
    from lstm_model import LSTMModel, GRUModel
    from transformer_model import TransformerModel

    input_dim = len(feature_cols)
    output_dim = len(feature_cols)

    if model_type == "LSTM":
        model = LSTMModel(input_dim, output_dim, lookback, pred_win, hidden_size, num_layers)
    elif model_type == "GRU":
        model = GRUModel(input_dim, output_dim, lookback, pred_win, hidden_size, num_layers)
    else:
        model = TransformerModel(input_dim, output_dim, lookback, pred_win, hidden_size, 4, num_layers, hidden_size * 4)

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model.to(device)
    context.set_progress(8.0, f"模型: {model_type}, 参数: {sum(p.numel() for p in model.parameters())}")

    # 训练
    import torch.nn as nn
    import torch.optim as optim
    from torch.utils.data import DataLoader, TensorDataset

    train_ds = TensorDataset(torch.FloatTensor(X_train), torch.FloatTensor(y_train))
    val_ds = TensorDataset(torch.FloatTensor(X_val), torch.FloatTensor(y_val))
    train_loader = DataLoader(train_ds, batch_size=batch_size, shuffle=True)
    val_loader = DataLoader(val_ds, batch_size=batch_size, shuffle=False)

    criterion = nn.MSELoss()
    optimizer = optim.Adam(model.parameters(), lr=lr, weight_decay=0.001)
    scheduler = optim.lr_scheduler.ReduceLROnPlateau(optimizer, mode='min', patience=10, factor=0.5)

    best_val_loss = float('inf')
    patience_counter = 0
    best_model_path = out_dir / "best_model.pth"

    for ep in range(epochs):
        if context.is_cancel_requested():
            return {"ok": False, "error_code": "CANCELLED", "message": "训练已被用户取消"}

        model.train()
        train_loss = 0.0
        for Xb, yb in train_loader:
            Xb, yb = Xb.to(device), yb.to(device)
            optimizer.zero_grad()
            loss = criterion(model(Xb), yb)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            optimizer.step()
            train_loss += loss.item()
        train_loss /= len(train_loader)

        model.eval()
        val_loss = 0.0
        with torch.no_grad():
            for Xb, yb in val_loader:
                Xb, yb = Xb.to(device), yb.to(device)
                val_loss += criterion(model(Xb), yb).item()
        val_loss /= len(val_loader)

        scheduler.step(val_loss)
        if val_loss < best_val_loss:
            best_val_loss = val_loss
            patience_counter = 0
            torch.save({"model_state_dict": model.state_dict(), "model_type": model_type,
                        "input_dim": input_dim, "output_dim": output_dim, "lookback": lookback,
                        "pred_win": pred_win, "hidden_size": hidden_size, "num_layers": num_layers,
                        "feature_cols": feature_cols}, best_model_path)
        else:
            patience_counter += 1

        pct = 10.0 + (ep + 1) / epochs * 85.0
        context.set_progress(pct, f"E{ep+1}/{epochs} loss={train_loss:.4f} val={val_loss:.4f}")

        if patience_counter >= 20:
            break

    context.set_progress(98.0, f"训练完成, best_val_loss={best_val_loss:.4f}")
    return {
        "ok": True,
        "outputs": [{
            "artifact_path": str(best_model_path),
            "metadata": {"model_type": model_type, "epochs": epochs, "best_val_loss": round(best_val_loss, 4),
                         "feature_cols": feature_cols, "train_count": len(X_train),
                         "val_count": len(X_val), "test_count": len(X_test)},
        }],
        "logs": [f"Timeseries training: {model_type}, val_loss={best_val_loss:.4f}"],
    }


def _build_sequences(data, lookback, pred_win):
    X, y = [], []
    for i in range(len(data) - lookback - pred_win + 1):
        X.append(data[i:i + lookback])
        y.append(data[i + lookback:i + lookback + pred_win])
    return np.array(X, dtype=np.float32), np.array(y, dtype=np.float32)


def _save_preprocessor(out_dir, mean, std, feature_cols, lookback, pred_win):
    with open(out_dir / "preprocessor.pkl", "wb") as f:
        pickle.dump({"mean": mean, "std": std, "feature_cols": list(feature_cols),
                     "lookback": lookback, "pred_win": pred_win}, f)
