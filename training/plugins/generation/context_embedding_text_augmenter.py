from __future__ import annotations

from pathlib import Path
import re

import numpy as np


PARAMETERS = [
    {
        "name": "mask_ratio",
        "type": "float",
        "label": "Mask比例",
        "default": 0.25,
        "min": 0.0,
        "max": 1.0,
        "options": [],
        "description": "被替换的词语比例",
        "required": False,
    },
    {
        "name": "cross_lingual_strength",
        "type": "float",
        "label": "跨语言增强强度",
        "default": 0.35,
        "min": 0.0,
        "max": 1.0,
        "options": [],
        "description": "跨语言表达替换强度",
        "required": False,
    },
]


PHRASE_REPLACEMENTS = {
    "很好": ["表现良好", "质量较好", "效果不错"],
    "很快": ["速度较快", "响应迅速", "处理较快"],
    "很强": ["强度较高", "效果显著", "能力较强"],
    "明显": ["显著", "清晰可见", "较为突出"],
    "系统": ["平台", "模型", "流程"],
    "算法": ["方法", "模型", "处理流程"],
    "图像": ["图片", "影像", "视觉样本"],
    "数据": ["样本", "数据内容", "输入数据"],
    "good": ["solid", "effective", "reliable"],
    "fast": ["quick", "rapid", "responsive"],
    "strong": ["robust", "pronounced", "high-intensity"],
    "image": ["visual sample", "picture", "frame"],
    "data": ["sample data", "input data", "dataset content"],
}

CONNECTOR_REPLACEMENTS = {
    "同时": "并且",
    "此外": "另外",
    "因此": "所以",
    "但是": "不过",
    "和": "以及",
    "and": "as well as",
    "however": "nevertheless",
}


def run(payload: dict, context) -> dict:
    parameters = payload.get("parameters", {}) or {}
    output_dir = Path(payload.get("output", {}).get("output_dir") or ".")
    output_dir.mkdir(parents=True, exist_ok=True)

    samples = payload.get("input", {}).get("samples", []) or []
    if not samples:
        return {"ok": False, "error_code": "NO_INPUT_SAMPLES"}

    target_count = max(1, int(payload.get("target_count") or len(samples)))
    mask_ratio = _clamp_float(parameters.get("mask_ratio", 0.25), 0.0, 1.0)
    cross = _clamp_float(parameters.get("cross_lingual_strength", parameters.get("cross", 0.35)), 0.0, 1.0)

    outputs = []
    for index in range(target_count):
        if context.is_cancel_requested():
            return {"ok": False, "error_code": "CANCELLED"}

        sample = samples[index % len(samples)]
        sp = Path(sample.get("sample_path") or sample.get("path") or sample.get("file_path") or "")
        try:
            text = sp.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        if not text:
            continue

        out_text = _replace_phrases(text, mask_ratio)
        if cross > 0:
            out_text = _replace_connectors(out_text, cross)
        if out_text == text:
            out_text = _fallback_rewrite(text)

        of = output_dir / f"{sp.stem}_ctxemb_{index:04d}{sp.suffix or '.txt'}"
        of.write_text(out_text, encoding="utf-8")
        outputs.append(
            {
                "source_sample_id": sample.get("id"),
                "output_path": str(of),
                "relative_path": of.name,
                "metadata": {
                    "method": "context_embedding",
                    "mask_ratio": mask_ratio,
                    "cross_lingual_strength": cross,
                },
                "status": "created",
            }
        )
        context.set_progress((index + 1) * 100 / target_count, f"Ctx embed {index + 1}/{target_count}")

    return {"ok": True, "outputs": outputs, "logs": []}


def _replace_phrases(text: str, ratio: float) -> str:
    candidates = [phrase for phrase in PHRASE_REPLACEMENTS if phrase in text]
    if not candidates:
        return text
    count = max(1, int(len(candidates) * ratio))
    np.random.shuffle(candidates)
    out = text
    for phrase in candidates[:count]:
        replacement = str(np.random.choice(PHRASE_REPLACEMENTS[phrase]))
        out = out.replace(phrase, replacement, 1)
    return out


def _replace_connectors(text: str, strength: float) -> str:
    out = text
    for src, dst in CONNECTOR_REPLACEMENTS.items():
        if src in out and np.random.rand() < strength:
            out = out.replace(src, dst, 1)
    return out


def _fallback_rewrite(text: str) -> str:
    if re.search(r"[\u4e00-\u9fff]", text):
        return text.rstrip() + "\n补充说明：该样本已进行上下文表达增强。"
    return text.rstrip() + "\nAdditional context: this sample has been contextually augmented."


def _clamp_float(value, low, high):
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        parsed = low
    return max(low, min(parsed, high))
