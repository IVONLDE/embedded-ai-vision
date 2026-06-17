from __future__ import annotations

from pathlib import Path
import re

import numpy as np


PARAMETERS = [
    {
        "name": "intermediate_language",
        "type": "select",
        "label": "中间语言",
        "default": "en",
        "min": None,
        "max": None,
        "options": ["en", "ja", "ko"],
        "description": "回译的中间语言代码",
        "required": False,
    },
    {
        "name": "back_translate_probability",
        "type": "float",
        "label": "回译概率",
        "default": 1.0,
        "min": 0.0,
        "max": 1.0,
        "options": [],
        "description": "对每个样本执行回译的概率",
        "required": False,
    },
    {
        "name": "sentence_restructure_strength",
        "type": "float",
        "label": "句式重构强度",
        "default": 0.3,
        "min": 0.0,
        "max": 1.0,
        "options": [],
        "description": "回译后的句式重组强度",
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
    bt_prob = max(0.0, min(float(parameters.get("back_translate_probability", parameters.get("bt_prob", parameters.get("回译概率", 1.0))) or 1.0), 1.0))
    recon = max(0.0, min(float(parameters.get("sentence_restructure_strength", parameters.get("recon", parameters.get("句式重构强度", 0.3))) or 0.3), 1.0))
    language = str(parameters.get("intermediate_language", parameters.get("lang", parameters.get("中间语言", "en"))) or "en").strip().lower()

    zh2mid = {
        "好": ["good", "fine", "nice"],
        "坏": ["bad", "poor", "worse"],
        "大": ["big", "large", "huge"],
        "小": ["small", "tiny", "little"],
        "快": ["fast", "quick", "rapid"],
        "慢": ["slow", "sluggish", "gradual"],
        "提升": ["improve", "boost", "enhance"],
        "增强": ["enhance", "strengthen", "boost"],
        "保持": ["maintain", "keep", "preserve"],
        "同时": ["at the same time", "meanwhile", "and"],
        "因此": ["therefore", "so", "thus"],
        "因为": ["because", "since", "as"],
        "更加": ["more", "even more", "further"],
    }
    if language == "ja":
        zh2mid = {
            "好": ["良い", "いい"],
            "坏": ["悪い", "良くない"],
            "大": ["大きい", "巨大な"],
            "小": ["小さい", "小規模な"],
            "快": ["速い", "迅速な"],
            "慢": ["遅い", "ゆっくりした"],
            "提升": ["向上", "改善"],
            "增强": ["強化", "向上"],
            "保持": ["維持", "保つ"],
            "同时": ["同時に", "一方で"],
            "因此": ["そのため", "したがって"],
            "因为": ["なぜなら", "だから"],
            "更加": ["さらに", "いっそう"],
        }
    elif language == "ko":
        zh2mid = {
            "好": ["좋다", "훌륭하다"],
            "坏": ["나쁘다", "좋지 않다"],
            "大": ["크다", "거대하다"],
            "小": ["작다", "작은 규모"],
            "快": ["빠르다", "신속하다"],
            "慢": ["느리다", "완만하다"],
            "提升": ["향상", "개선"],
            "增强": ["강화", "향상"],
            "保持": ["유지", "보존"],
            "同时": ["동시에", "그리고"],
            "因此": ["따라서", "그러므로"],
            "因为": ["왜냐하면", "때문에"],
            "更加": ["더", "더욱"],
        }

    def translate_to_mid(text: str) -> str:
        out = text
        for zh, mids in sorted(zh2mid.items(), key=lambda item: len(item[0]), reverse=True):
            if zh in out:
                out = out.replace(zh, f" {str(np.random.choice(mids))} ")
        return re.sub(r"\s+", " ", out).strip()

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

        if np.random.rand() > bt_prob:
            out_text = text
        else:
            mid_text = translate_to_mid(text)
            tokens = re.findall(r"[A-Za-z]+|[^A-Za-z]+", mid_text)
            mapped = []
            for tok in tokens:
                if re.fullmatch(r"[A-Za-z]+", tok or ""):
                    mapped.append(tok)
                else:
                    mapped.append(tok)
            out_text = re.sub(r"\s+", "", "".join(mapped))

            if np.random.rand() < recon and "。" in out_text:
                segs = [s for s in re.split(r"([。！？])", out_text) if s]
                chunks = []
                current = ""
                for seg in segs:
                    current += seg
                    if seg in "。！？":
                        chunks.append(current)
                        current = ""
                if current:
                    chunks.append(current)
                if len(chunks) >= 3:
                    middle = chunks[1:-1]
                    np.random.shuffle(middle)
                    out_text = chunks[0] + "".join(middle) + chunks[-1]

        out = output_dir / f"{sp.stem}_bt_{index:04d}{sp.suffix or '.txt'}"
        out.write_text(out_text, encoding="utf-8")
        outputs.append(
            {
                "source_sample_id": sample.get("id"),
                "output_path": str(out),
                "relative_path": out.name,
                "metadata": {
                    "method": "back_translation",
                    "intermediate_language": language,
                    "back_translate_probability": bt_prob,
                    "sentence_restructure_strength": recon,
                },
                "status": "created",
            }
        )
        context.set_progress((index + 1) * 100 / target_count, f"Back trans {index + 1}/{target_count}")

    return {"ok": True, "outputs": outputs, "logs": []}
