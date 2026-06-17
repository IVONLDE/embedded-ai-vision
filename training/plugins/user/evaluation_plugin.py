"""
AudioClassification 音频分类评估插件。

加载训练好的模型checkpoint对测试集进行评估，输出准确率、loss等指标。

从前端注册:
  module_path: plugins.evaluation.audio_evaluator (或直接上传此脚本)
  callable_name: run
  category: evaluation
  modality: audio
"""
from __future__ import annotations

import os
import sys
import traceback
import json
from pathlib import Path

import numpy as np

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
        "name": 'max_duration',
        "type": 'float',
        "label": '音频最大时长(秒)',
        "default": 20.0,
        "min": 1.0,
        "max": 60.0,
        "description": '评估时音频的最大时长',
        "required": False,
    },
]


def run(payload: dict, context) -> dict:
    try:
        return _run_evaluation(payload, context)
    except Exception as exc:
        return {
            'ok': False,
            'error_code': 'EVALUATION_CRASH',
            'message': f'Evaluation crashed: {exc}\n{traceback.format_exc()}',
        }


def _run_evaluation(payload: dict, context) -> dict:
    import torch

    params = payload.get('parameters', {}) or {}
    inp = payload.get('input', {})
    out_dir = Path(payload['output']['output_dir'])
    out_dir.mkdir(parents=True, exist_ok=True)

    training_task = payload.get('training_task', {}) or {}
    training_result = training_task.get('result', {}) or {}
    checkpoint_path = ''

    if training_result.get('outputs'):
        for o in training_result['outputs']:
            ap = o.get('artifact_path') or o.get('output_path') or ''
            if ap and os.path.isfile(ap):
                checkpoint_path = ap
                break

    if not checkpoint_path:
        checkpoint_path = params.get('model_checkpoint_path', params.get('model_path', ''))
    if not checkpoint_path or not os.path.isfile(checkpoint_path):
        return {
            'ok': False,
            'error_code': 'MISSING_CHECKPOINT',
            'message': f'找不到模型checkpoint: {checkpoint_path}',
        }

    max_dur = float(params.get('max_duration', 20.0))

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
            'message': '找不到AudioClassification-Pytorch项目',
        }

    # monkey-patch: macls 库 get_crop_feature_len 中 torch.randn 参数为 float 的 bug
    import macls.data_utils.reader as _macls_reader
    _orig_crop = _macls_reader.MAClsDataset.get_crop_feature_len
    def _patched_crop(self):
        self.max_duration = int(self.max_duration)
        return _orig_crop(self)
    _macls_reader.MAClsDataset.get_crop_feature_len = _patched_crop

    # 评估服务将样本放在 target_dataset 或 baseline_dataset 中
    target = inp.get('target_dataset', {}) or {}
    baseline = inp.get('baseline_dataset', {}) or {}
    samples = target.get('samples', []) or baseline.get('samples', [])
    ds_path = target.get('path', '') or baseline.get('path', '')
    smap = _build_samples_map(samples, ds_path)
    if not smap:
        return {'ok': False, 'error_code': 'NO_SAMPLES', 'message': '没有可评估的音频样本'}

    context.set_progress(5.0, f'加载 {len(smap)} 个评估样本')

    class_to_samples = {}
    for sm in smap:
        class_to_samples.setdefault(sm['label'], []).append(sm['path'])

    class_names = sorted(class_to_samples.keys())
    num_class = len(class_names)
    label_to_id = {n: i for i, n in enumerate(class_names)}

    data_dir = out_dir / 'eval_data'
    data_dir.mkdir(parents=True, exist_ok=True)

    test_list_path = data_dir / 'eval_list.txt'
    label_list_path = data_dir / 'label_list.txt'

    eval_samples = [(sm['path'], label_to_id[sm['label']]) for sm in smap]

    with open(test_list_path, 'w', encoding='utf-8') as f:
        for p, lid in eval_samples:
            f.write(f'{p}\t{lid}\n')

    with open(label_list_path, 'w', encoding='utf-8') as f:
        for name in class_names:
            f.write(f'{name}\n')

    # 加载模型元信息
    meta_path = os.path.join(os.path.dirname(os.path.dirname(checkpoint_path)), 'model_meta.json')
    if os.path.isfile(meta_path):
        with open(meta_path, 'r', encoding='utf-8') as f:
            model_meta = json.load(f)
        model_name = model_meta.get('model_name', 'CAMPPlus')
        feature_method = model_meta.get('feature_method', 'Fbank')
    else:
        model_meta = {}
        model_name = params.get('model_name', 'CAMPPlus')
        feature_method = params.get('feature_method', 'Fbank')

    from macls.utils.utils import dict_to_object

    configs = dict_to_object({
        'dataset_conf': {
            'dataset': {
                'min_duration': 0.1, 'max_duration': 3,
                'sample_rate': 16000, 'use_dB_normalization': True, 'target_dB': -20,
            },
            'dataLoader': {'batch_size': 32, 'drop_last': True, 'num_workers': 0},
            'eval_conf': {'batch_size': 8, 'max_duration': max_dur},
            'train_list': str(test_list_path),
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
        'train_conf': {
            'enable_amp': False, 'use_compile': False,
            'label_smoothing': 0.0, 'max_epoch': 1,
            'log_interval': 10,
        },
    })

    device = 'cuda' if torch.cuda.is_available() else 'cpu'

    import warnings
    warnings.filterwarnings('ignore', message='Windows系统不支持多线程读取数据')
    import matplotlib
    matplotlib.use('Agg')  # 非交互后端，避免后台线程 GUI 崩溃
    trainer = MAClsTrainer(configs=configs, use_gpu=(device == 'cuda'))
    trainer.stop_eval = False

    context.set_progress(15.0, '加载模型权重...')

    loss, accuracy = trainer.evaluate(
        resume_model=checkpoint_path,
        save_matrix_path=str(out_dir),
    )

    context.set_progress(95.0, f'准确率: {accuracy:.4f}, Loss: {loss:.4f}')

    evaluation_result = {
        'accuracy': float(accuracy),
        'loss': float(loss),
        'num_classes': num_class,
        'num_samples': len(smap),
        'class_names': class_names,
        'device': device,
        'summary': (
            f'音频分类评估完成\n'
            f'━━━━━━━━━━━━━━━━\n'
            f'类别数: {num_class}\n'
            f'评估样本: {len(smap)}\n'
            f'准确率: {accuracy:.4f} ({accuracy * 100:.2f}%)\n'
            f'Loss: {loss:.4f}\n'
            f'设备: {device}\n'
        ),
    }

    report_path = out_dir / 'evaluation_report.json'
    with open(report_path, 'w', encoding='utf-8') as f:
        json.dump(evaluation_result, f, ensure_ascii=False, indent=2)

    context.set_progress(100.0, f'评估完成: accuracy={accuracy:.4f}')

    return {
        'ok': True,
        'results': [{
            'model_name': '音频分类评估',
            'metrics': {
                'accuracy': round(float(accuracy) * 100, 2),
                'loss': round(float(loss), 4),
                'num_classes': num_class,
                'num_samples': len(smap),
            },
            'summary': evaluation_result['summary'],
            'artifacts': [{
                'type': 'report',
                'path': str(report_path),
            }],
        }],
    }
