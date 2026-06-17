"""
Sonar-OLTR PLUD 开放集识别评估插件。

加载训练任务的 ResNet18 模型 checkpoint，执行：
  1. MAV (Mean Activation Vector) 收集 -- 对已知类训练数据做前向传播
  2. Weibull 分布拟合 (libmr 极值理论)
  3. OpenMax 概率重校准
  4. 多指标评估: Accuracy, OSFM, Macro-F1, Gmean, NMA

不涉及二次训练，仅加载训练好的模型做前向测试。
"""
from __future__ import annotations
from pathlib import Path
import os
import random
import json
import warnings

warnings.filterwarnings('ignore', message=r'.*deprecated.*(?:pretrained|weights).*',
                        module=r'torchvision.*')


_IMAGE_EXTS = {'.png', '.jpg', '.jpeg', '.bmp', '.gif', '.tiff', '.tif', '.webp'}

def _build_samples_map(samples: list[dict], dataset_path: str | None = None) -> list[dict]:
    """从 payload 样本列表提取 (label, path) 映射。"""
    result = []
    for s in samples:
        labels = s.get("labels") or []
        if not labels:
            continue
        fp = s.get("path") or s.get("file_path") or ""
        if not fp:
            continue
        if os.path.splitext(fp)[1].lower() not in _IMAGE_EXTS:
            continue
        if dataset_path and not os.path.isabs(fp):
            fp = os.path.join(dataset_path, fp)
        if os.path.isfile(fp):
            label = labels[0]
            if isinstance(label, dict):
                label = label.get("class_name") or label.get("name") or label.get("label") or str(label)
            result.append({"label": str(label), "path": fp})
    return result


# ====== OpenMax / Weibull 工具函数 ======

def _compute_channel_distances(mavs, features, eu_weight=0.5):
    """计算每个通道到 MAV 的距离分布。"""
    import scipy.spatial.distance as spd
    import numpy as np
    eucos_dists, eu_dists, cos_dists = [], [], []
    for ch, mcv in enumerate(mavs):
        eu_dists.append([spd.euclidean(mcv, feat[ch]) for feat in features])
        cos_dists.append([spd.cosine(mcv, feat[ch]) for feat in features])
        eucos_dists.append([spd.euclidean(mcv, feat[ch]) * eu_weight
                            + spd.cosine(mcv, feat[ch]) for feat in features])
    return {
        "eucos": np.array(eucos_dists),
        "cosine": np.array(cos_dists),
        "euclidean": np.array(eu_dists),
    }


def _fit_weibull(means, dists, categories, tailsize=20, distance_type="eucos"):
    """用 libmr 对距离分布尾部拟合 Weibull 分布 (极值理论 EVT)。"""
    import libmr
    import numpy as np
    wb_model = {}
    for mean, dist, cat_name in zip(means, dists, categories):
        wb_model[cat_name] = {}
        wb_model[cat_name][f"distances_{distance_type}"] = dist[distance_type]
        wb_model[cat_name]["mean_vec"] = mean
        wb_model[cat_name]["weibull_model"] = []
        for ch in range(mean.shape[0]):
            mr = libmr.MR()
            tailtofit = np.sort(dist[distance_type][ch, :])[-tailsize:]
            mr.fit_high(tailtofit, len(tailtofit))
            wb_model[cat_name]["weibull_model"].append(mr)
    return wb_model


def _compute_openmax_prob(scores, scores_u):
    """OpenMax 概率计算: 已知类概率 + 未知类概率。"""
    import numpy as np
    prob_scores, prob_unknowns = [], []
    for s, su in zip(scores, scores_u):
        s_clipped = np.clip(s, -100, 100)
        su_clipped = np.clip(np.sum(su), -100, 100)
        ch_scores = np.exp(s_clipped)
        ch_unknown = np.exp(su_clipped)
        total_denom = np.sum(ch_scores) + ch_unknown
        if total_denom < 1e-300:
            total_denom = 1.0
        prob_scores.append(ch_scores / total_denom)
        prob_unknowns.append(ch_unknown / total_denom)
    scores = np.mean(prob_scores, axis=0)
    unknowns = np.mean(prob_unknowns, axis=0)
    return scores.tolist() + [unknowns]


def _softmax(x):
    import numpy as np
    e_x = np.exp(x - np.max(x))
    return e_x / e_x.sum()


def _calc_distance(query_score, mcv, eu_weight, distance_type="eucos"):
    """计算查询样本到 MAV 的距离。"""
    import scipy.spatial.distance as spd
    import numpy as np
    if np.any(np.isnan(query_score)) or np.any(np.isinf(query_score)):
        return 1e10
    if np.any(np.isnan(mcv)) or np.any(np.isinf(mcv)):
        return 1e10
    try:
        if distance_type == "eucos":
            return spd.euclidean(mcv, query_score) * eu_weight + spd.cosine(mcv, query_score)
        elif distance_type == "euclidean":
            return spd.euclidean(mcv, query_score)
        elif distance_type == "cosine":
            return spd.cosine(mcv, query_score)
        return spd.euclidean(mcv, query_score) * eu_weight + spd.cosine(mcv, query_score)
    except ValueError:
        return 1e10


def _query_weibull(cat_name, wb_model, distance_type="eucos"):
    return [
        wb_model[cat_name]["mean_vec"],
        wb_model[cat_name][f"distances_{distance_type}"],
        wb_model[cat_name]["weibull_model"],
    ]


def _openmax(wb_model, categories, input_score, eu_weight, alpha=10,
             distance_type="eucos", if_logit=False):
    """OpenMax 概率重校准: 利用 Weibull 模型对 Softmax 分数做开放集修正。"""
    import numpy as np

    # alpha 不能超过当前有效类别数，否则 omega 赋值会出现长度不匹配。
    effective_alpha = min(
        int(alpha),
        int(input_score.shape[-1]) if input_score.ndim > 0 else 0,
        len(categories),
    )
    omega = np.zeros(input_score.shape[-1])
    if effective_alpha > 0:
        ranked_list = input_score.argsort().ravel()[::-1][:effective_alpha]
        alpha_weights = [
            ((effective_alpha + 1) - i) / float(effective_alpha)
            for i in range(1, effective_alpha + 1)
        ]
        omega[ranked_list] = alpha_weights

    scores, scores_u = [], []
    for ch, input_score_channel in enumerate(input_score):
        score_channel, score_channel_u = [], []
        for c, cat_name in enumerate(categories):
            mav, dist, model = _query_weibull(cat_name, wb_model, distance_type)
            ch_dist = _calc_distance(input_score_channel, mav[ch], eu_weight, distance_type)
            wscore = model[ch].w_score(ch_dist)
            modified_score = input_score_channel[c] * (1 - wscore * omega[c])
            score_channel.append(modified_score)
            score_channel_u.append(input_score_channel[c] - modified_score)
        scores.append(score_channel)
        scores_u.append(score_channel_u)

    scores = np.asarray(scores)
    scores_u = np.asarray(scores_u)
    if np.any(np.isnan(scores)) or np.any(np.isinf(scores)):
        softmax_prob = _softmax(np.array(input_score.ravel()))
        return softmax_prob, softmax_prob
    openmax_prob = np.array(_compute_openmax_prob(scores, scores_u))
    softmax_prob = _softmax(np.array(input_score.ravel()))

    if if_logit:
        scores_m = np.mean(scores, axis=0)
        scores_u_m = np.mean(np.sum(scores_u, axis=1), axis=0)
        openmax_logit = np.array(scores_m.tolist() + [scores_u_m])
        softmax_logit = input_score.ravel()
        return openmax_prob, softmax_prob, openmax_logit, softmax_logit
    return openmax_prob, softmax_prob


# ====== 评估指标函数 ======

def _cal_osfm(y_true, y_pred):
    """计算 Open-Set F-Measure (OSFM)。"""
    import numpy as np
    from sklearn.metrics import confusion_matrix
    if hasattr(y_true, "cpu"):
        y_true = y_true.cpu()
    if hasattr(y_pred, "cpu"):
        y_pred = y_pred.cpu()
    cm = confusion_matrix(y_true, y_pred)
    pred_sum = np.sum(cm, axis=0)
    true_sum = np.sum(cm, axis=1)
    known_class_num = cm.shape[0] - 1
    if known_class_num <= 0:
        return float("nan")
    precision_sum = 0.0
    recall_sum = 0.0
    for i in range(known_class_num):
        TP = cm[i][i]
        if pred_sum[i] > 0:
            precision_sum += TP / pred_sum[i]
        if true_sum[i] > 0:
            recall_sum += TP / true_sum[i]
    precision_avg = precision_sum / known_class_num
    recall_avg = recall_sum / known_class_num
    if (precision_avg + recall_avg) == 0:
        return 0.0
    return (2 * precision_avg * recall_avg) / (precision_avg + recall_avg)


def _cal_gmean(y_true, y_pred):
    """计算各类别准确率的几何平均 (G-Mean)。"""
    import numpy as np
    from sklearn.metrics import confusion_matrix
    from scipy.stats.mstats import gmean
    if hasattr(y_true, "cpu"):
        y_true = y_true.cpu()
    if hasattr(y_pred, "cpu"):
        y_pred = y_pred.cpu()
    cm = confusion_matrix(y_true, y_pred)
    diag = np.diagonal(cm)
    n_per_class = np.sum(cm, axis=1)
    if 0 in n_per_class:
        return None
    acc_per_class = diag / n_per_class
    return float(gmean(acc_per_class))


def _cal_nma(y_true, y_pred):
    """计算归一化宏准确率 (Normalized Macro Accuracy)。"""
    import numpy as np
    if hasattr(y_true, "cpu"):
        y_true = y_true.cpu()
    if hasattr(y_pred, "cpu"):
        y_pred = y_pred.cpu()
    labels = np.unique(y_true)
    n = len(labels)
    if n == 0:
        return float("nan")
    acc_list = []
    for lbl in labels:
        mask = y_true == lbl
        if mask.sum() == 0:
            continue
        acc_list.append((y_pred[mask] == lbl).sum() / mask.sum())
    if not acc_list:
        return float("nan")
    return float(np.mean(acc_list))


# ====== PLUD 主流程 ======

PARAMETERS = [
    {
        "name": 'model_checkpoint_path',
        "type": 'string',
        "label": '模型检查点路径',
        "default": '',
        "min": None,
        "max": None,
        "options": [],
        "description": '训练好的模型检查点文件路径（必填）',
        "required": True,
    },
    {
        "name": 'backbone',
        "type": 'string',
        "label": '骨干网络',
        "default": 'resnet18',
        "min": None,
        "max": None,
        "options": [],
        "description": '预训练骨干网络名称',
        "required": False,
    },
    {
        "name": 'batch_size',
        "type": 'int',
        "label": '批大小',
        "default": 32,
        "min": 1,
        "max": 512,
        "options": [],
        "description": '批次大小',
        "required": False,
    },
    {
        "name": 'train_class_num',
        "type": 'int',
        "label": '已知类数量',
        "default": 5,
        "min": 1,
        "max": 100,
        "options": [],
        "description": '开放集识别中的已知类别数',
        "required": False,
    },
    {
        "name": 'weibull_tail',
        "type": 'int',
        "label": 'Weibull尾部大小',
        "default": 20,
        "min": 1,
        "max": 1000,
        "options": [],
        "description": '拟合Weibull分布时使用的尾部样本数',
        "required": False,
    },
    {
        "name": 'weibull_alpha',
        "type": 'int',
        "label": 'OpenMax alpha',
        "default": 2,
        "min": 1,
        "max": 10,
        "options": [],
        "description": 'OpenMax重校准的top-k alpha参数',
        "required": False,
    },
    {
        "name": 'weibull_threshold',
        "type": 'float',
        "label": '未知类概率阈值',
        "default": 0.5,
        "min": 0.0,
        "max": 1.0,
        "options": [],
        "description": '判定为未知类的概率阈值',
        "required": False,
    },
]


def run(payload: dict, context) -> dict:
    try:
        return _run_plud(payload, context)
    except Exception as exc:
        import traceback
        return {
            'ok': False,
            'error_code': 'EVALUATION_CRASH',
            'message': f'Evaluation crashed: {exc}\n{traceback.format_exc()}',
        }


def _run_plud(payload: dict, context) -> dict:
    """PLUD 评估入口: 加载训练checkpoint -> MAV收集 -> Weibull拟合 -> OpenMax评估。"""
    try:
        import torch
        import torch.nn as nn
        import torchvision.transforms as transforms
        import torchvision.models as models
        import numpy as np
        import libmr  # noqa: F401
        import scipy.spatial.distance  # noqa: F401
        from sklearn.metrics import (
            accuracy_score,
            f1_score,
            classification_report,
        )
        from PIL import Image
    except ImportError as e:
        return {
            "ok": False,
            "error_code": "MISSING_DEPENDENCY",
            "message": f"missing deps (torch/pretrainedmodels/libmr/scipy/sklearn): {e}",
        }

    # ---- 参数解析 ----
    params = payload.get("parameters", {}) or {}
    inp = payload.get("input", {})
    out_dir = Path(payload["output"]["output_dir"])
    out_dir.mkdir(parents=True, exist_ok=True)

    baseline_data = inp.get("baseline_dataset", {})
    target_data = inp.get("target_dataset", {})

    baseline_samples = baseline_data.get("samples", [])
    target_samples = target_data.get("samples", [])
    baseline_path = baseline_data.get("path", "")

    if not baseline_samples:
        return {
            "ok": False,
            "error_code": "NO_BASELINE_DATA",
            "message": "baseline dataset is empty",
        }

    # 必需: 训练产出的 checkpoint 路径
    checkpoint_path = params.get("model_checkpoint_path", "")
    if not checkpoint_path:
        return {
            "ok": False,
            "error_code": "MISSING_CHECKPOINT",
            "message": "model_checkpoint_path is required. 请先完成训练任务再启动评估。",
        }
    if not os.path.isfile(checkpoint_path):
        return {
            "ok": False,
            "error_code": "CHECKPOINT_NOT_FOUND",
            "message": f"checkpoint not found: {checkpoint_path}",
        }

    device = "cuda" if torch.cuda.is_available() else "cpu"
    backbone = params.get("backbone", "resnet18")
    bs = int(params.get("batch_size", 32))
    train_class_num = int(params.get("train_class_num", 5))
    weibull_tail = int(params.get("weibull_tail", 20))
    weibull_alpha = int(params.get("weibull_alpha", 2))
    weibull_threshold = float(params.get("weibull_threshold", 0.5))

    # ---- 建立 baseline 数据 ----
    bmap = _build_samples_map(baseline_samples, baseline_path)
    if len(bmap) < 10:
        return {
            "ok": False,
            "error_code": "INSUFFICIENT_DATA",
            "message": f"need >=10 samples, got {len(bmap)}",
        }

    c2s: dict[str, list[str]] = {}
    for sm in bmap:
        c2s.setdefault(sm["label"], []).append(sm["path"])
    all_cnames = sorted(c2s.keys())
    total_classes = len(all_cnames)
    if train_class_num >= total_classes:
        train_class_num = total_classes
    l2i = {n: i for i, n in enumerate(all_cnames)}

    context.set_progress(2.0, f"Dataset: {total_classes} classes, {len(bmap)} samples")

    # 随机选择 train_class_num 个已知类（固定种子保证可复现）
    rnd = np.random.RandomState(0)
    class_indices = list(range(total_classes))
    train_classes = rnd.choice(class_indices, train_class_num, replace=False).tolist()
    train_cnames = [all_cnames[i] for i in train_classes]
    context.set_progress(3.0, f"Known classes ({train_class_num}): {train_cnames}")

    # 构建 MAV 收集用训练集 & 测试集 (仅已知类, 6:4 划分)
    tr_p, tr_l = [], []
    te_known_p, te_known_l = [], []
    tr_map = {old: new for new, old in enumerate(sorted(train_classes))}

    for old_id in sorted(train_classes):
        cn = all_cnames[old_id]
        paths = c2s.get(cn, [])
        random.shuffle(paths)
        n = len(paths)
        nt = max(1, int(n * 0.6))
        new_id = tr_map[old_id]
        for p in paths[:nt]:
            tr_p.append(p)
            tr_l.append(new_id)
        for p in paths[nt:]:
            te_known_p.append(p)
            te_known_l.append(new_id)

    context.set_progress(5.0, f"MAV-collection: {len(tr_p)}, Test-known: {len(te_known_p)}")

    # ---- 建立 target 测试数据 (已知类 + 未知类) ----
    tmap = _build_samples_map(target_samples, target_data.get("path", ""))
    unk_label = train_class_num
    old_new_map_test: dict[str, int] = {}
    for sm in tmap:
        cn = sm["label"]
        if cn in l2i:
            old_id = l2i[cn]
            if old_id in train_classes:
                old_new_map_test[cn] = tr_map[old_id]
            else:
                old_new_map_test[cn] = unk_label

    te_p, te_l = [], []
    for sm in tmap:
        cn = sm["label"]
        if cn in old_new_map_test:
            te_p.append(sm["path"])
            te_l.append(old_new_map_test[cn])
    context.set_progress(7.0, f"Target test samples: {len(te_p)}")

    # ---- PyTorch Dataset ----
    class SonarDS(torch.utils.data.Dataset):
        def __init__(self, paths, labels, tf=None):
            self.paths = paths
            self.labels = labels
            self.tf = tf

        def __len__(self):
            return len(self.paths)

        def __getitem__(self, i):
            img = Image.open(self.paths[i]).convert("RGB")
            if self.tf:
                img = self.tf(img)
            return img, self.labels[i]

    mean, std = [0.485, 0.456, 0.406], [0.229, 0.224, 0.225]
    eval_tf = transforms.Compose([
        transforms.Resize([224, 224]),
        transforms.ToTensor(),
        transforms.Normalize(mean=mean, std=std),
    ])

    tr_ds = SonarDS(tr_p, tr_l, eval_tf)
    tr_iter = torch.utils.data.DataLoader(tr_ds, batch_size=bs, shuffle=False, num_workers=0)

    if te_p:
        te_ds = SonarDS(te_p, te_l, eval_tf)
        te_iter = torch.utils.data.DataLoader(te_ds, batch_size=bs, shuffle=False, num_workers=0)
    else:
        te_iter = tr_iter

    # ---- 加载训练 checkpoint ----
    context.set_progress(8.0, f"Loading checkpoint: {os.path.basename(checkpoint_path)}")
    checkpoint = torch.load(checkpoint_path, map_location="cpu")
    ckpt_state = checkpoint.get("model_state_dict")
    ckpt_backbone = checkpoint.get("backbone", backbone)
    ckpt_num_classes = checkpoint.get("num_classes", total_classes)
    best_va = checkpoint.get("val_acc", 0.0)

    if ckpt_state is None:
        return {
            "ok": False,
            "error_code": "INVALID_CHECKPOINT",
            "message": "checkpoint missing model_state_dict",
        }

    context.set_progress(
        10.0,
        f"Checkpoint: {ckpt_backbone}, {ckpt_num_classes} classes, val_acc={best_va:.1f}%",
    )

    # ---- 构建模型, 仅取已知类权重 ----
    try:
        net = _build_backbone(models, ckpt_backbone)
    except Exception:
        return {
            "ok": False,
            "error_code": "MODEL_LOAD_ERROR",
            "message": f"cannot build backbone {ckpt_backbone}",
        }
    df = net.fc.in_features
    net.fc = nn.Linear(df, train_class_num)
    net = net.to(device)

    # 从 checkpoint 中提取已知类对应的分类头权重行
    sorted_known_indices = sorted(train_classes)
    ckpt_weight = ckpt_state.get("fc.weight")
    if ckpt_weight is None:
        ckpt_weight = ckpt_state.get("last_linear.weight")  # [ckpt_num_classes, df]
    ckpt_bias = ckpt_state.get("fc.bias")
    if ckpt_bias is None:
        ckpt_bias = ckpt_state.get("last_linear.bias")       # [ckpt_num_classes]
    if ckpt_weight is None or ckpt_bias is None:
        return {
            "ok": False,
            "error_code": "INVALID_CHECKPOINT",
            "message": "checkpoint missing classification head weights",
        }

    selected_weight = ckpt_weight[torch.tensor(sorted_known_indices, device="cpu")]
    selected_bias = ckpt_bias[torch.tensor(sorted_known_indices, device="cpu")]

    new_state = {}
    for k, v in ckpt_state.items():
        if k in {"fc.weight", "last_linear.weight"}:
            new_state[k] = selected_weight
        elif k in {"fc.bias", "last_linear.bias"}:
            new_state[k] = selected_bias
        else:
            new_state[k] = v

    net.load_state_dict(new_state, strict=False)
    net.eval()
    context.set_progress(15.0, "Model loaded from training checkpoint")

    # ---- PLUD: MAV 收集 (前向传播, 不训练) ----
    context.set_progress(16.0, "Collecting MAV activations...")
    scores_by_class = [[] for _ in range(train_class_num)]
    with torch.no_grad():
        for X, y in tr_iter:
            X, y = X.to(device), y.to(device)
            outputs = net(X)
            for score, t in zip(outputs, y):
                if torch.argmax(score) == t:
                    t_int = int(t.item())
                    if 0 <= t_int < train_class_num:
                        scores_by_class[t_int].append(
                            score.unsqueeze(0).unsqueeze(0).cpu().numpy()
                        )

    # 过滤掉空类(0样本)，避免 np.mean 空数组产生 NaN
    valid_mask = [len(x) > 0 for x in scores_by_class]
    valid_scores = [x for x, ok in zip(scores_by_class, valid_mask) if ok]
    if not valid_scores:
        return {"ok": False, "error_code": "NO_MAV_DATA",
                "message": "All known classes have 0 correctly classified training samples"}
    valid_scores = [np.concatenate(x) for x in valid_scores]
    mavs = np.array([np.mean(x, axis=0) for x in valid_scores])
    dists = [
        _compute_channel_distances(mav, score)
        for mav, score in zip(mavs, valid_scores)
    ]
    valid_categories = [i for i, ok in enumerate(valid_mask) if ok]
    context.set_progress(30.0, f"MAVs computed for {train_class_num} known classes")

    # ---- Weibull 分布拟合 ----
    context.set_progress(32.0, "Fitting Weibull distributions...")
    wb_model = _fit_weibull(mavs, dists, valid_categories, weibull_tail, "euclidean")
    context.set_progress(45.0, "Weibull model fitted")

    # ---- PLUD: OpenMax 评估 ----
    context.set_progress(50.0, "Running OpenMax evaluation...")
    all_scores, all_labels = [], []
    with torch.no_grad():
        for X, y in te_iter:
            X, y = X.to(device), y.to(device)
            outputs = net(X)
            all_scores.append(outputs.cpu().numpy())
            all_labels.append(y.cpu().numpy())
    all_scores = np.concatenate(all_scores, axis=0)
    all_labels = np.concatenate(all_labels, axis=0)

    openmax_preds = []
    for score in all_scores:
        score_exp = score[np.newaxis, :]
        om_prob, _ = _openmax(
            wb_model, valid_categories, score_exp, 0.5,
            weibull_alpha, "euclidean",
        )
        om_label = np.argmax(om_prob)
        openmax_preds.append(
            om_label if np.max(om_prob) >= weibull_threshold else train_class_num
        )

    openmax_preds = np.array(openmax_preds)
    all_labels = np.array(all_labels)
    context.set_progress(75.0, f"Evaluated {len(openmax_preds)} samples")

    # ---- 计算指标 ----
    acc = accuracy_score(all_labels, openmax_preds)

    try:
        osfm = _cal_osfm(all_labels, openmax_preds)
    except Exception:
        osfm = float("nan")

    try:
        mac_f1 = f1_score(all_labels, openmax_preds, average="macro", zero_division=0)
    except Exception:
        mac_f1 = float("nan")

    gm = _cal_gmean(all_labels, openmax_preds)
    if gm is None:
        gm = 0.0

    try:
        nma = _cal_nma(all_labels, openmax_preds)
    except Exception:
        nma = float("nan")

    context.set_progress(90.0, f"Metrics computed: Acc={acc*100:.1f}%")

    osfm_str = f"{osfm:.4f}" if not np.isnan(osfm) else "N/A"
    nma_str = f"{nma:.4f}" if not np.isnan(nma) else "N/A"

    try:
        cls_report = classification_report(
            all_labels, openmax_preds,
            digits=4, zero_division=0, output_dict=True,
        )
    except Exception:
        cls_report = {}

    metrics = {
        "accuracy": round(acc * 100, 2),
        "osfm": osfm,
        "macro_f1": mac_f1,
        "gmean": round(float(gm), 4),
        "nma": nma,
        "train_class_num": train_class_num,
        "total_classes": total_classes,
        "known_classes": train_cnames,
    }

    # 保存报告
    report_path = out_dir / "plud_evaluation_report.json"
    report = {
        "model": "sonar-oltr-plud",
        "backbone": ckpt_backbone,
        "checkpoint": os.path.basename(checkpoint_path),
        "train_class_num": train_class_num,
        "total_classes": total_classes,
        "metrics": metrics,
        "classification_report": cls_report,
    }
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    summary = (
        f"Sonar-OLTR PLUD evaluated on {total_classes} classes "
        f"(known={train_class_num}, backbone={ckpt_backbone}). "
        f"Accuracy={acc*100:.1f}%, OSFM={osfm_str}, "
        f"Macro-F1={mac_f1:.4f}, Gmean={float(gm):.4f}, NMA={nma_str}. "
        f"(model from training, val_acc={best_va:.1f}%)"
    )

    context.set_progress(100.0, "PLUD evaluation complete")

    return {
        "ok": True,
        "results": [{
            "model_name": "sonar-oltr-plud",
            "metrics": metrics,
            "summary": summary,
            "artifacts": [
                {"type": "report", "path": str(report_path)},
            ],
        }],
    }


def _build_backbone(models, backbone: str):
    if backbone != "resnet18":
        raise ValueError(f"unsupported backbone: {backbone}")
    try:
        from torchvision.models import ResNet18_Weights
        return models.resnet18(weights=ResNet18_Weights.DEFAULT)
    except Exception:
        return models.resnet18(weights=None)
