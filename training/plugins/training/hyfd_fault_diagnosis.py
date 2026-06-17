"""
HyFD-SME 船舶主机故障诊断训练插件。

使用排气温度时序数据，通过混合模型(TDF特征+ResNet34+注意力机制)
对6类主机故障进行诊断分类。
"""
from __future__ import annotations
from pathlib import Path
import os, sys, json, logging
import numpy as np
os.environ["CUBLAS_WORKSPACE_CONFIG"] = ":4096:8"

_FAULT_ROOT = Path(__file__).resolve().parent.parent / "fault_diagnosis"
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

PARAMETERS = [
    {
        "name": "epochs", "type": "int", "label": "训练轮次", "default": 100,
        "min": 10, "max": 500, "options": [], "description": "训练epoch数量", "required": False,
    },
    {
        "name": "batch_size", "type": "int", "label": "批大小", "default": 256,
        "min": 32, "max": 1024, "options": [], "description": "批次大小", "required": False,
    },
    {
        "name": "learning_rate", "type": "float", "label": "学习率", "default": 0.001,
        "min": 0.0001, "max": 0.01, "options": [], "description": "最大学习率", "required": False,
    },
    {
        "name": "window_size", "type": "int", "label": "滑动窗口", "default": 64,
        "min": 32, "max": 256, "options": [], "description": "时序窗口大小", "required": False,
    },
    {
        "name": "stride", "type": "int", "label": "窗口步长", "default": 16,
        "min": 1, "max": 64, "options": [], "description": "滑动窗口步长", "required": False,
    },
    {
        "name": "random_seed", "type": "int", "label": "随机种子", "default": 777,
        "min": 0, "max": 99999, "options": [], "description": "数据划分随机种子", "required": False,
    },
    {
        "name": "snr", "type": "string", "label": "信噪比(dB)", "default": "None",
        "min": None, "max": None, "options": ["None", "-4", "-2", "0", "2", "4"],
        "description": "添加噪声的信噪比，None=不加噪", "required": False,
    },
    {
        "name": "train_ratio", "type": "float", "label": "训练集比例", "default": 0.7,
        "min": 0.5, "max": 0.9, "options": [], "description": "训练集占比", "required": False,
    },
    {
        "name": "val_ratio", "type": "float", "label": "验证集比例", "default": 0.1,
        "min": 0.05, "max": 0.3, "options": [], "description": "验证集占比", "required": False,
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

    epochs = int(params.get("epochs", 100))
    batch_size = int(params.get("batch_size", 256))
    lr = float(params.get("learning_rate", 0.001))
    window_size = int(params.get("window_size", 64))
    stride = int(params.get("stride", 16))
    random_seed = int(params.get("random_seed", 777))
    snr_str = str(params.get("snr", "None"))
    snr = None if snr_str in ("None", "", "none", "null") else int(snr_str)
    train_ratio = float(params.get("train_ratio", 0.7))
    val_ratio = float(params.get("val_ratio", 0.1))

    # 找 CSV
    samples = inp.get("samples", [])
    csv_path = None
    for s in samples:
        fp = s.get("file_path", s.get("path", ""))
        if fp.lower().endswith(".csv") and os.path.isfile(fp):
            csv_path = fp
            break
    if not csv_path:
        return {"ok": False, "error_code": "NO_CSV", "message": "数据集中未找到 CSV 文件"}

    context.set_progress(1.0, f"加载数据: {csv_path}")

    # 加载数据
    import pandas as pd
    df = pd.read_csv(csv_path)
    if "MEAN TEMP" not in df.columns or "label" not in df.columns:
        return {"ok": False, "error_code": "INVALID_CSV",
                "message": f"CSV 需要 MEAN TEMP 和 label 列，实际: {list(df.columns)}"}

    # 加噪
    if snr is not None:
        for i in range(6):
            label_mask = df["label"] == i
            if not label_mask.any():
                continue
            P_signal = np.mean(df.loc[label_mask, "MEAN TEMP"] ** 2)
            snr_linear = 10 ** (snr / 10)
            noise_std = np.sqrt(P_signal / snr_linear)
            noise = np.random.normal(0, noise_std, label_mask.sum())
            df.loc[label_mask, "MEAN TEMP"] = df.loc[label_mask, "MEAN TEMP"] + noise

    # 滑动窗口
    cols = []
    for i in range(0, len(df) - window_size, stride):
        temp_data = df.iloc[i:i + window_size, 0].values
        label_data = df.iloc[i:i + window_size, 1].values
        if np.max(label_data) == np.min(label_data):
            cols.append(np.append(temp_data, int(np.min(label_data))))
    data = pd.DataFrame(cols, columns=[f"t-{j}" for j in range(window_size, 0, -1)] + ["label"])

    X = data.iloc[:, :-1].values.astype(np.float32)
    y = data.iloc[:, -1].values.astype(np.int64)

    nc = len(np.unique(y))
    context.set_progress(3.0, f"窗口数: {len(X)}, 类别: {nc}")

    # 划分
    from sklearn.model_selection import train_test_split
    test_ratio = max(0.05, 1.0 - train_ratio - val_ratio)
    X_temp, X_test, y_temp, y_test = train_test_split(X, y, test_size=test_ratio, random_state=random_seed, stratify=y)
    val_rel = val_ratio / (train_ratio + val_ratio) if (train_ratio + val_ratio) > 0 else 0.15
    X_train, X_val, y_train, y_val = train_test_split(X_temp, y_temp, test_size=val_rel, random_state=random_seed, stratify=y_temp)

    # TDF 特征
    def extract_tdf(arr):
        data = arr.astype(np.float64)
        m = np.mean(data); mn = np.min(data); mx = np.max(data); s = np.std(data)
        md = np.median(data); diff = data - m
        m2 = np.mean(diff**2); m3 = np.mean(diff**3); m4 = np.mean(diff**4)
        sk = m3/(m2**1.5) if m2>0 else 0; ku = m4/(m2**2)-3 if m2>0 else 0
        a, b = np.percentile(data, [25, 75])
        return [round(m,3), s, mn, mx, sk, ku, md, a, b, mx-mn, np.sqrt(np.mean(np.square(data))), np.var(data)]

    def make_tdf(X_arr):
        return np.array([extract_tdf(r) for r in X_arr], dtype=np.float32)

    X_train_tdf = make_tdf(X_train)
    X_val_tdf = make_tdf(X_val)
    X_test_tdf = make_tdf(X_test)

    X_train = np.concatenate([X_train_tdf, X_train], axis=1)
    X_val = np.concatenate([X_val_tdf, X_val], axis=1)
    X_test_final = np.concatenate([X_test_tdf, X_test], axis=1)

    context.set_progress(5.0, f"train={len(X_train)} val={len(X_val)} test={len(X_test)}")

    # 保存测试数据
    np.savez(out_dir / "test_data.npz", X_test=X_test_final, y_test=y_test)

    # 模型
    sys.path.insert(0, str(_FAULT_ROOT))
    import torch; import torch.nn as nn; import torch.optim as optim
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
    context.set_progress(8.0, f"模型参数: {sum(p.numel() for p in model.parameters())}")

    # 数据集
    from torch.utils.data import DataLoader, TensorDataset
    from torch.autograd import Variable

    train_ds = TensorDataset(torch.FloatTensor(X_train), torch.LongTensor(y_train))
    val_ds = TensorDataset(torch.FloatTensor(X_val), torch.LongTensor(y_val))
    train_dl = DataLoader(train_ds, batch_size=batch_size, shuffle=True)
    val_dl = DataLoader(val_ds, batch_size=batch_size, shuffle=False)

    criterion = nn.CrossEntropyLoss()
    optimizer = optim.AdamW(model.parameters(), lr=0)
    scheduler = optim.lr_scheduler.CosineAnnealingWarmRestarts(optimizer, T_0=100, T_mult=1, eta_min=lr*0.01)

    best_acc = 0
    best_path = out_dir / "best_model.pth"
    patience = 0

    for ep in range(epochs):
        if context.is_cancel_requested():
            return {"ok": False, "error_code": "CANCELLED", "message": "训练已取消"}

        model.train()
        train_acc, train_loss = 0, 0
        for batch, label in train_dl:
            tdf_b = Variable(batch[:, :12].unsqueeze(1).float().to(device))
            raw_b = Variable(batch[:, 12:].unsqueeze(1).float().to(device))
            label = label.to(device)

            optimizer.zero_grad()
            out = model(tdf_b, raw_b)
            loss = criterion(out, label)
            loss.backward()
            optimizer.step()
            train_loss += loss.item()
            train_acc += (out.argmax(1) == label).sum().item() / len(label)
        train_acc = train_acc / len(train_dl) * 100
        train_loss /= len(train_dl)

        model.eval()
        val_acc = 0
        with torch.no_grad():
            for batch, label in val_dl:
                tdf_b = Variable(batch[:, :12].unsqueeze(1).float().to(device))
                raw_b = Variable(batch[:, 12:].unsqueeze(1).float().to(device))
                label = label.to(device)
                val_acc += (model(tdf_b, raw_b).argmax(1) == label).sum().item() / len(label)
        val_acc = val_acc / len(val_dl) * 100

        scheduler.step()

        if val_acc > best_acc:
            best_acc = val_acc
            patience = 0
            torch.save({"model_state": model.state_dict(), "window_size": window_size, "stride": stride}, best_path)
        else:
            patience += 1

        pct = 10.0 + (ep + 1) / epochs * 85.0
        context.set_progress(pct, f"E{ep+1}/{epochs} tr_acc={train_acc:.1f}% val_acc={val_acc:.1f}%")

        if patience > 30:
            break

    context.set_progress(98.0, f"最佳验证精度: {best_acc:.1f}%")
    return {
        "ok": True,
        "outputs": [{
            "artifact_path": str(best_path),
            "metadata": {"best_val_acc": round(best_acc, 2), "num_classes": nc,
                         "train_count": len(X_train), "val_count": len(X_val), "test_count": len(X_test)},
        }],
        "logs": [f"HyFD-SME: best_val_acc={best_acc:.1f}%"],
    }
