from __future__ import annotations

from pathlib import Path

import numpy as np


PARAMETERS = [
    {
        "name": 'style_label',
        "type": 'select',
        "label": '目标风格',
        "default": 'formal',
        "min": None,
        "max": None,
        "options": ['formal', 'casual', 'concise'],
        "description": 'formal: 正式; casual: 口语化; concise: 简洁',
        "required": False,
    },
    {
        "name": 'conciseness_strength',
        "type": 'float',
        "label": '简洁压缩强度',
        "default": 0.5,
        "min": 0.0,
        "max": 1.0,
        "options": [],
        "description": '简洁风格下的压缩强度',
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
    style = str(parameters.get("style_label", parameters.get("style", parameters.get("风格标签", "formal"))) or "formal").strip().lower()
    concise = max(0.0, min(float(parameters.get("conciseness_strength", parameters.get("concise", parameters.get("简洁强度", 0.5))) or 0.5), 1.0))

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
        if style in ("formal", "academic"):
            rep = {"搞": "进行", "挺": "相当", "很": "较为", "非常": "十分",
                   "特别": "尤其", "可能": "或许", "感觉": "认为"}
            for a, b in rep.items():
                if a in out and np.random.rand() < 0.8:
                    out = out.replace(a, b)
            out = out.replace("，", "，")
            out = out.replace("但是", "然而").replace("不过", "然而").replace("所以", "因此")
            if "。" in out and np.random.rand() < 0.8:
                out = "总体而言，" + out
        elif style in ("casual", "colloquial"):
            rep = {"进行": "搞", "相当": "挺", "较为": "挺", "十分": "很",
                   "尤其": "特别", "或许": "可能", "认为": "觉得"}
            for a, b in rep.items():
                if a in out and np.random.rand() < 0.8:
                    out = out.replace(a, b)
            if np.random.rand() < 0.5:
                out = out.replace("，", "，真的，")
            if "。" in out and np.random.rand() < 0.8:
                out = out.replace("。", "。挺自然的。", 1)
        elif style in ("concise", "succinct"):
            drop = ["其实", "可能", "感觉", "大概", "大致", "非常", "真的", "挺"]
            for p in drop:
                if p in out and np.random.rand() < concise:
                    out = out.replace(p, "")
            out = out.replace("并且", "且").replace("同时", "且")
            parts = [s.strip() for s in out.split("。") if s.strip()]
            if len(parts) > 2 and np.random.rand() < concise:
                out = "。".join(parts[: max(1, len(parts) // 2)]) + "。"

        of = output_dir / f"{sp.stem}_style_{index:04d}{sp.suffix or '.txt'}"
        of.write_text(out, encoding="utf-8")
        outputs.append({
            "source_sample_id": sample.get("id"),
            "output_path": str(of),
            "relative_path": of.name,
            "metadata": {"method": "style_controlled", "style": style},
            "status": "created",
        })
        context.set_progress((index + 1) * 100 / target_count, f"Style ctrl {index+1}/{target_count}")

    return {"ok": True, "outputs": outputs, "logs": []}
