
"""
Sonar-OLTR ResNet18 骨干训练插件。

基于ImageNet预训练ResNet18对声呐图像进行分类训练，
保存最佳验证精度的模型checkpoint。
"""
from __future__ import annotations
from pathlib import Path
import os
import random
import warnings

warnings.filterwarnings('ignore', message=r'.*deprecated.*(?:pretrained|weights).*',
                        module=r'torchvision.*')

_IMAGE_EXTS = {'.png', '.jpg', '.jpeg', '.bmp', '.gif', '.tiff', '.tif', '.webp'}

def _build_samples_map(samples: list[dict], dataset_path: str | None = None) -> list[dict]:
    result = []
    for s in samples:
        labels = s.get('labels') or []
        if not labels:
            continue
        fp = s.get('path') or s.get('file_path') or ''
        if not fp:
            continue
        if os.path.splitext(fp)[1].lower() not in _IMAGE_EXTS:
            continue
        if dataset_path and not os.path.isabs(fp):
            fp = os.path.join(dataset_path, fp)
        if os.path.isfile(fp):
            label = labels[0]
            if isinstance(label, dict):
                label = label.get('class_name') or label.get('name') or label.get('label') or str(label)
            result.append({'label': str(label), 'path': fp})
    return result


PARAMETERS = [
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
        "description": '训练批次大小',
        "required": False,
    },
    {
        "name": 'epochs',
        "type": 'int',
        "label": '训练轮次',
        "default": 10,
        "min": 1,
        "max": 500,
        "options": [],
        "description": '训练epoch数量',
        "required": False,
    },
    {
        "name": 'learning_rate',
        "type": 'float',
        "label": '学习率',
        "default": 0.01,
        "min": 1e-06,
        "max": 1.0,
        "options": [],
        "description": '初始学习率（SGD优化器）',
        "required": False,
    },
    {
        "name": 'train_ratio',
        "type": 'float',
        "label": '训练集比例',
        "default": 0.6,
        "min": 0.1,
        "max": 0.9,
        "options": [],
        "description": '数据集划分中训练集占比',
        "required": False,
    },
    {
        "name": 'val_ratio',
        "type": 'float',
        "label": '验证集比例',
        "default": 0.2,
        "min": 0.05,
        "max": 0.5,
        "options": [],
        "description": '数据集划分中验证集占比',
        "required": False,
    },
]


def run(payload: dict, context) -> dict:
    try:
        return _run_training(payload, context)
    except Exception as exc:
        import traceback
        return {
            'ok': False,
            'error_code': 'TRAINING_CRASH',
            'message': f'Training crashed: {exc}\n{traceback.format_exc()}',
        }


def _run_training(payload: dict, context) -> dict:
    try:
        import torch, torch.nn as nn, torch.optim as optim
        from torch.optim import lr_scheduler
        import torchvision.transforms as transforms
        import torchvision.models as models
        import numpy as np
        from PIL import Image
    except ImportError as e:
        return {'ok': False, 'error_code': 'MISSING_DEPENDENCY',
                'message': f'missing deps: {e}'}

    params = payload.get('parameters', {}) or {}
    inp = payload.get('input', {})
    out_dir = Path(payload['output']['output_dir'])
    out_dir.mkdir(parents=True, exist_ok=True)

    samples = inp.get('samples', [])
    ds_path = inp.get('dataset_path', '')
    smap = _build_samples_map(samples, ds_path)
    if len(smap) < 10:
        return {'ok': False, 'error_code': 'INSUFFICIENT_DATA',
                'message': f'need >=10 samples, got {len(smap)}'}

    device = 'cuda' if torch.cuda.is_available() else 'cpu'
    backbone = params.get('backbone', 'resnet18')
    bs = int(params.get('batch_size', 32))
    epochs = int(params.get('epochs', 10))
    lr = float(params.get('learning_rate', 0.01))
    tr = float(params.get('train_ratio', 0.6))
    vr = float(params.get('val_ratio', 0.2))

    c2s = {}
    for sm in smap:
        c2s.setdefault(sm['label'], []).append(sm['path'])
    cnames = sorted(c2s.keys())
    nc = len(cnames)
    l2i = {n: i for i, n in enumerate(cnames)}
    context.set_progress(2.0, f'{nc} classes, {len(smap)} samples')

    tr_p, tr_l = [], []
    va_p, va_l = [], []
    te_p, te_l = [], []
    for cn, paths in c2s.items():
        random.shuffle(paths)
        n = len(paths)
        nt = max(1, int(n * tr))
        nv = max(1, int(n * vr))
        lid = l2i[cn]
        for p in paths[:nt]:
            tr_p.append(p); tr_l.append(lid)
        for p in paths[nt:nt+nv]:
            va_p.append(p); va_l.append(lid)
        for p in paths[nt+nv:]:
            te_p.append(p); te_l.append(lid)
    context.set_progress(5.0, f'train:{len(tr_p)} val:{len(va_p)} test:{len(te_p)}')

    class SonarDS(torch.utils.data.Dataset):
        def __init__(self, paths, labels, tf=None):
            self.paths = paths; self.labels = labels; self.tf = tf
        def __len__(self): return len(self.paths)
        def __getitem__(self, i):
            img = Image.open(self.paths[i]).convert('RGB')
            if self.tf: img = self.tf(img)
            return img, self.labels[i]

    mean, std = [0.485, 0.456, 0.406], [0.229, 0.224, 0.225]
    tr_tf = transforms.Compose([
        transforms.Resize([224, 224]),
        transforms.RandomHorizontalFlip(),
        transforms.RandomRotation(90),
        transforms.ToTensor(),
        transforms.Normalize(mean=mean, std=std),
    ])
    va_tf = transforms.Compose([
        transforms.Resize([224, 224]),
        transforms.ToTensor(),
        transforms.Normalize(mean=mean, std=std),
    ])
    tr_ds = SonarDS(tr_p, tr_l, tr_tf)
    va_ds = SonarDS(va_p, va_l, va_tf)
    tr_iter = torch.utils.data.DataLoader(tr_ds, batch_size=bs, shuffle=True, num_workers=0)
    va_iter = torch.utils.data.DataLoader(va_ds, batch_size=bs, shuffle=False, num_workers=0)

    context.set_progress(8.0, f'loading {backbone}')
    try:
        net = _build_backbone(models, backbone)
    except Exception:
        return {'ok': False, 'error_code': 'MODEL_LOAD_ERROR',
                'message': f'cannot load {backbone}'}
    df = net.fc.in_features
    net.fc = nn.Linear(df, nc)
    net = net.to(device)

    crit = nn.CrossEntropyLoss()
    op_ids = list(map(id, net.fc.parameters()))
    fp_params = filter(lambda p: id(p) not in op_ids, net.parameters())
    opt = optim.SGD([
        {'params': fp_params},
        {'params': net.fc.parameters(), 'lr': lr * 10},
    ], lr=lr, weight_decay=0.001)
    sched = lr_scheduler.MultiStepLR(opt, [35, 75], gamma=0.7)

    best_va = 0.0; best_mp = ''; logs = []
    for ep in range(epochs):
        if context.is_cancel_requested():
            return {'ok': False, 'error_code': 'CANCELLED', 'message': 'cancelled'}
        net.train()
        tl, tc, tt = 0.0, 0, 0
        for X, y in tr_iter:
            X, y = X.to(device), y.to(device)
            yh = net(X); loss = crit(yh, y)
            opt.zero_grad(); loss.backward(); opt.step()
            tl += loss.item(); tc += (yh.argmax(dim=1)==y).sum().item(); tt += y.shape[0]
        sched.step()
        net.eval()
        vc, vt = 0, 0
        with torch.no_grad():
            for X, y in va_iter:
                X, y = X.to(device), y.to(device)
                vc += (net(X).argmax(dim=1)==y).sum().item(); vt += y.shape[0]
        va = vc / vt * 100 if vt > 0 else 0.0
        ta = tc / tt * 100 if tt > 0 else 0.0
        if va > best_va:
            best_va = va; md = out_dir / 'model'; md.mkdir(parents=True, exist_ok=True)
            best_mp = str(md / f'{backbone}_best.pth')
            torch.save({'epoch': ep+1, 'model_state_dict': net.state_dict(),
                        'val_acc': va, 'backbone': backbone,
                        'num_classes': nc, 'label_to_id': l2i}, best_mp)
        prog = 8.0 + 82.0 * (ep+1) / epochs
        msg = f'E{ep+1}/{epochs} loss={tl/len(tr_iter):.4f} ta={ta:.1f}% va={va:.1f}%'
        context.set_progress(prog, msg); logs.append(msg)

    if te_p:
        te_ds = SonarDS(te_p, te_l, va_tf)
        te_iter = torch.utils.data.DataLoader(te_ds, batch_size=bs, shuffle=False, num_workers=0)
        net.eval(); tec, tet = 0, 0
        with torch.no_grad():
            for X, y in te_iter:
                X, y = X.to(device), y.to(device)
                tec += (net(X).argmax(dim=1)==y).sum().item(); tet += y.shape[0]
        test_acc = tec/tet*100 if tet > 0 else 0.0
        logs.append(f'Test acc: {test_acc:.1f}%')
        context.set_progress(95.0, f'Test: {test_acc:.1f}%')

    context.set_progress(100.0, f'Done: best_val={best_va:.1f}%')
    return {'ok': True, 'outputs': [{
        'artifact_path': best_mp,
        'metadata': {'best_val_acc': best_va, 'backbone': backbone,
                     'num_classes': nc, 'class_names': cnames, 'device': device},
    }], 'logs': logs}


def _build_backbone(models, backbone: str):
    if backbone != 'resnet18':
        raise ValueError(f'unsupported backbone: {backbone}')
    try:
        from torchvision.models import ResNet18_Weights
        return models.resnet18(weights=ResNet18_Weights.DEFAULT)
    except Exception:
        return models.resnet18(weights=None)
