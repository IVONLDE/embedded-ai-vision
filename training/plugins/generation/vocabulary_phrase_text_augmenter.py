from __future__ import annotations

from pathlib import Path
import re

import numpy as np


PARAMETERS = [
    {
        "name": "replacement_ratio",
        "type": "float",
        "label": "替换比例",
        "default": 0.3,
        "min": 0.0,
        "max": 1.0,
        "options": [],
        "description": "词汇/短语被替换的比例",
        "required": False,
    },
    {
        "name": "pos_constraint",
        "type": "string",
        "label": "词性约束",
        "default": "",
        "min": None,
        "max": None,
        "options": [],
        "description": "限制替换的词性，留空表示不限制",
        "required": False,
    },
    {
        "name": "phrase_level",
        "type": "bool",
        "label": "短语级替换",
        "default": True,
        "min": None,
        "max": None,
        "options": [],
        "description": "是否进行短语级别替换",
        "required": False,
    },
]


def run(payload: dict, context) -> dict:
    parameters = payload.get("parameters", {}) or {}
    output_dir = Path(payload.get("output", {}).get("output_dir") or ".")
    output_dir.mkdir(parents=True, exist_ok=True)

    samples = payload.get("input", {}).get("samples", []) or []
    if not samples:
        return {"ok": False, "error_code": "NO_INPUT_SAMPLES"}

    target_count = max(1, int(payload.get("target_count") or len(samples)))
    ratio = max(0.0, min(float(parameters.get("replacement_ratio", parameters.get("ratio", parameters.get("替换比例", 0.3))) or 0.3), 1.0))
    phrase = bool(parameters.get("phrase_level", parameters.get("phrase", parameters.get("短语级替换", True))))

    word_syn = {
        "好": ["优秀", "良好", "不错"],
        "坏": ["糟糕", "不佳", "恶劣"],
        "大": ["巨大", "庞大", "宏大"],
        "小": ["微小", "细小", "轻微"],
        "快": ["迅速", "快速", "敏捷"],
        "慢": ["缓慢", "迟缓", "较慢"],
        "高": ["较高", "更高", "高水平"],
        "低": ["较低", "更低", "低水平"],
        "新": ["崭新", "全新", "更新"],
        "旧": ["陈旧", "老旧", "过时"],
        "强": ["强劲", "显著", "有力"],
        "弱": ["较弱", "微弱", "有限"],
        "明": ["明亮", "清晰", "鲜明"],
        "暗": ["昏暗", "暗淡", "阴暗"],
    }
    phrase_syn = {
        "提升": ["增强", "提高", "改善"],
        "增强": ["提升", "加强", "提高"],
        "鲁棒性": ["可靠性", "适应性"],
        "泛化": ["泛化能力", "推广"],
        "保持": ["维持", "持续保持"],
        "同时": ["并且", "而且"],
        "由于": ["因为", "因而"],
        "因此": ["所以", "因而"],
        "更加": ["更为", "更"],
    }

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

        out = text
        if phrase:
            for k in sorted(phrase_syn.keys(), key=len, reverse=True):
                if k in out and np.random.rand() < ratio:
                    out = out.replace(k, str(np.random.choice(phrase_syn[k])))

        chars = list(out)
        candidates = [i for i, ch in enumerate(chars) if ch in word_syn]
        if candidates:
            np.random.shuffle(candidates)
            num_replace = max(1, int(len(candidates) * ratio))
            for pos in candidates[:num_replace]:
                key = chars[pos]
                chars[pos] = str(np.random.choice(word_syn[key]))

        out = "".join(chars)
        out_path = output_dir / f"{sp.stem}_vocab_{index:04d}{sp.suffix or '.txt'}"
        out_path.write_text(out, encoding="utf-8")
        outputs.append(
            {
                "source_sample_id": sample.get("id"),
                "output_path": str(out_path),
                "relative_path": out_path.name,
                "metadata": {"method": "vocabulary_phrase", "ratio": ratio, "phrase_level": phrase},
                "status": "created",
            }
        )
        context.set_progress((index + 1) * 100 / target_count, f"Vocab/phrase {index + 1}/{target_count}")

    return {"ok": True, "outputs": outputs, "logs": []}
