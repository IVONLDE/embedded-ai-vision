"""
AudioClassification 音频分类训练插件。

基于 AudioClassification-Pytorch 框架，支持 CAMPPlus/EcapaTdnn 等模型
对音频数据集进行分类训练，保存最佳模型checkpoint。

从前端注册:
  module_path: plugins.training.audio_classifier (或直接上传此脚本)
  callable_name: run
  category: training
  modality: audio
"""
from __future__ import annotations

import os
import sys
import traceback
import json
from pathlib import Path

_AUDIO_EXTS = {'.wav', '.mp3', '.flac', '.ogg', '.aac', '.m4a'}


def _build_samples_map(samples: list[dict], dataset_path: str | None = None) -> list[dict]:
    result = []
    for s in samples:
        labels = s.get('labels') or []
        if not labels:
            continue
        fp = s.get('path') or s.get('file_path') or ''
        if not fp:
            continue
        if os.path.splitext(fp)[1].lower() not in _AUDIO_EXTS:
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
        "name": 'model_name',
        "type": 'select',
        "label": '模型',
        "default": 'CAMPPlus',
        "options": ['CAMPPlus', 'EcapaTdnn', 'Res2Net', 'TDNN', 'PANNS', 'ERes2Net', 'ResNetSE'],
        "description": '音频分类模型架构',
        "required": False,
    },
    {
        "name": 'feature_method',
        "type": 'select',
        "label": '特征提取方法',
        "default": 'Fbank',
        "options": ['Fbank', 'MelSpectrogram', 'MFCC', 'Spectrogram'],
        "description": '音频特征提取方法',
        "required": False,
    },
    {
        "name": 'batch_size',
        "type": 'int',
        "label": '批大小',
        "default": 32,
        "min": 1,
        "max": 256,
        "description": '训练批次大小',
        "required": False,
    },
    {
        "name": 'epochs',
        "type": 'int',
        "label": '训练轮次',
        "default": 30,
        "min": 1,
        "max": 500,
        "description": '训练epoch数量',
        "required": False,
    },
    {
        "name": 'learning_rate',
        "type": 'float',
        "label": '学习率',
        "default": 0.001,
        "min": 1e-06,
        "max": 0.1,
        "description": '初始学习率（Adam优化器）',
        "required": False,
    },
    {
        "name": 'max_duration',
        "type": 'float',
        "label": '音频最大时长(秒)',
        "default": 3.0,
        "min": 0.5,
        "max": 30.0,
        "description": '超过该时长的音频会被裁剪',
        "required": False,
    },
    {
        "name": 'train_ratio',
        "type": 'float',
        "label": '训练集比例',
        "default": 0.75,
        "min": 0.3,
        "max": 0.9,
        "description": '数据集划分中训练集占比，剩余为测试集',
        "required": False,
    },
]


class _DummyWriter:
    """空日志写入器，替代 macls 的 VisualDL writer。"""
    def add_scalar(self, *args, **kwargs): pass
    def add_scalars(self, *args, **kwargs): pass
    def close(self): pass


def run(payload: dict, context) -> dict:
    try:
        return _run_training(payload, context)
    except Exception as exc:
        return {
            'ok': False,
            'error_code': 'TRAINING_CRASH',
            'message': f'Training crashed: {exc}\n{traceback.format_exc()}',
        }


def _run_training(payload: dict, context) -> dict:
    import random
    import torch
    import yaml

    params = payload.get('parameters', {}) or {}
    inp = payload.get('input', {})
    out_dir = Path(payload['output']['output_dir'])
    out_dir.mkdir(parents=True, exist_ok=True)

    samples = inp.get('samples', [])
    ds_path = inp.get('dataset_path', '')
    smap = _build_samples_map(samples, ds_path)
    if len(smap) < 10:
        return {
            'ok': False,
            'error_code': 'INSUFFICIENT_DATA',
            'message': f'训练至少需要10个样本，当前仅{len(smap)}个',
        }

    # 获取 AudioClassification 项目路径
    ac_project = params.get('ac_project_path', '')
    if not ac_project:
        candidate = Path(__file__).resolve().parent.parent
        if candidate.exists():
            ac_project = str(candidate)

    if ac_project and ac_project not in sys.path:
        sys.path.insert(0, ac_project)

    try:
        from macls.trainer import MAClsTrainer
    except ImportError:
        return {
            'ok': False,
            'error_code': 'MISSING_DEPENDENCY',
            'message': '找不到AudioClassification-Pytorch项目，请设置ac_project_path参数',
        }

    # monkey-patch: macls 库 get_crop_feature_len 中 torch.randn 参数为 float 的 bug
    import macls.data_utils.reader as _macls_reader
    _orig_crop = _macls_reader.MAClsDataset.get_crop_feature_len
    def _patched_crop(self):
        self.max_duration = int(self.max_duration)
        return _orig_crop(self)
    _macls_reader.MAClsDataset.get_crop_feature_len = _patched_crop

    model_name = params.get('model_name', 'CAMPPlus')
    feature_method = params.get('feature_method', 'Fbank')
    bs = int(params.get('batch_size', 32))
    epochs = int(params.get('epochs', 30))
    lr = float(params.get('learning_rate', 0.001))
    max_dur = float(params.get('max_duration', 3.0))
    tr = float(params.get('train_ratio', 0.75))

    # 按类分组并划分训练/测试集
    random.seed(42)
    class_to_samples = {}
    for sm in smap:
        class_to_samples.setdefault(sm['label'], []).append(sm['path'])

    class_names = sorted(class_to_samples.keys())
    num_class = len(class_names)
    label_to_id = {n: i for i, n in enumerate(class_names)}

    train_samples = []
    test_samples = []
    for cls_name, paths in class_to_samples.items():
        random.shuffle(paths)
        n = len(paths)
        n_train = max(1, int(n * tr))
        lid = label_to_id[cls_name]
        for p in paths[:n_train]:
            train_samples.append((p, lid))
        for p in paths[n_train:]:
            test_samples.append((p, lid))

    context.set_progress(5.0, f'{num_class}类, train={len(train_samples)} test={len(test_samples)}')

    # 写入数据列表文件
    data_dir = out_dir / 'data_lists'
    data_dir.mkdir(parents=True, exist_ok=True)

    train_list_path = data_dir / 'train_list.txt'
    test_list_path = data_dir / 'test_list.txt'
    label_list_path = data_dir / 'label_list.txt'

    with open(train_list_path, 'w', encoding='utf-8') as f:
        for p, lid in train_samples:
            f.write(f'{p}\t{lid}\n')

    with open(test_list_path, 'w', encoding='utf-8') as f:
        for p, lid in test_samples:
            f.write(f'{p}\t{lid}\n')

    with open(label_list_path, 'w', encoding='utf-8') as f:
        for name in class_names:
            f.write(f'{name}\n')

    # 构建配置
    configs = {
        'dataset_conf': {
            'dataset': {
                'min_duration': 0.4, 'max_duration': max_dur,
                'sample_rate': 16000, 'use_dB_normalization': True, 'target_dB': -20,
            },
            'dataLoader': {
                'batch_size': bs, 'drop_last': True, 'num_workers': 0,
            },
            'eval_conf': {
                'batch_size': max(1, bs // 4), 'max_duration': max_dur * 3,
            },
            'train_list': str(train_list_path),
            'test_list': str(test_list_path),
            'label_list_path': str(label_list_path),
        },
        'preprocess_conf': {
            'use_hf_model': False,
            'feature_method': feature_method,
            'method_args': {'sample_frequency': 16000, 'num_mel_bins': 80},
        },
        'model_conf': {
            'model': model_name,
            'model_args': {'num_class': num_class},
        },
        'optimizer_conf': {
            'optimizer': 'Adam',
            'optimizer_args': {'lr': lr, 'weight_decay': 1e-5},
            'scheduler': 'WarmupCosineSchedulerLR',
            'scheduler_args': {
                'min_lr': 1e-5, 'max_lr': lr,
                'warmup_epoch': max(1, epochs // 6),
            },
        },
        'train_conf': {
            'enable_amp': False, 'use_compile': False,
            'label_smoothing': 0.0, 'max_epoch': epochs,
            'log_interval': max(1, len(train_samples) // bs // 5),
        },
    }

    device = 'cuda' if torch.cuda.is_available() else 'cpu'
    use_gpu = device == 'cuda'
    context.log('info', f'audio-training-start',
                {'model': model_name, 'classes': num_class, 'samples': len(smap), 'device': device})

    save_model_dir = out_dir / 'model_checkpoints'

    import warnings
    warnings.filterwarnings('ignore', message='Windows系统不支持多线程读取数据')
    trainer = MAClsTrainer(configs=configs, use_gpu=use_gpu)

    trainer._MAClsTrainer__setup_dataloader(is_train=True)
    trainer._MAClsTrainer__setup_model(input_size=trainer.audio_featurizer.feature_dim, is_train=True)

    # 新版 macls 中 train() 初始化这些值，手动调 __train_epoch 需要补上
    trainer.max_step = len(trainer.train_loader) * trainer.configs.train_conf.max_epoch
    trainer.train_step = 0
    trainer.train_eta_sec = None

    best_acc = 0.0
    best_model_path = ''
    nranks = 1
    local_rank = 0

    for epoch_id in range(epochs):
        if context.is_cancel_requested():
            return {'ok': False, 'error_code': 'CANCELLED', 'message': '训练已取消'}

        trainer._MAClsTrainer__train_epoch(epoch_id=epoch_id + 1, local_rank=local_rank, writer=_DummyWriter(), nranks=nranks)

        eval_loss, eval_acc = trainer.evaluate()

        if eval_acc >= best_acc:
            best_acc = eval_acc
            best_dir = save_model_dir / 'best_model'
            best_dir.mkdir(parents=True, exist_ok=True)
            best_model_path = str(best_dir / 'model.pth')
            torch.save(trainer.model.state_dict(), best_model_path)

        epoch_dir = save_model_dir / f'epoch_{epoch_id + 1}'
        epoch_dir.mkdir(parents=True, exist_ok=True)
        torch.save(trainer.model.state_dict(), epoch_dir / 'model.pth')

        progress = 5.0 + 90.0 * (epoch_id + 1) / epochs
        context.set_progress(
            progress,
            f'Epoch {epoch_id + 1}/{epochs} '
            f'Train: loss={trainer.train_loss:.4f} acc={trainer.train_acc:.4f} '
            f'Test: loss={eval_loss:.4f} acc={eval_acc:.4f}'
        )

    model_meta = {
        'model_name': model_name, 'feature_method': feature_method,
        'num_classes': num_class, 'class_names': class_names,
        'label_to_id': label_to_id, 'best_accuracy': float(best_acc), 'device': device,
    }
    with open(save_model_dir / 'model_meta.json', 'w', encoding='utf-8') as f:
        json.dump(model_meta, f, ensure_ascii=False, indent=2)

    context.set_progress(100.0, f'训练完成: best_accuracy={best_acc:.4f}')

    return {
        'ok': True,
        'outputs': [{
            'artifact_path': best_model_path,
            'artifact_type': 'model_checkpoint',
            'metadata': model_meta,
            'summary': f'音频分类模型 {model_name} 训练完成，{num_class}类，{len(smap)}样本，最佳准确率: {best_acc:.4f}',
        }],
    }
