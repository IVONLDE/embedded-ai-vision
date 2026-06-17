from __future__ import annotations

from pathlib import Path
import re

import numpy as np


PARAMETERS = [
    {
        "name": 'reorder_granularity',
        "type": 'select',
        "label": '重排粒度',
        "default": 'sentence',
        "min": None,
        "max": None,
        "options": ['sentence', 'paragraph'],
        "description": 'sentence: 句子级; paragraph: 段落级',
        "required": False,
    },
    {
        "name": 'shuffle_strength',
        "type": 'float',
        "label": '打乱强度',
        "default": 0.5,
        "min": 0.0,
        "max": 1.0,
        "options": [],
        "description": '打乱的比例强度',
        "required": False,
    },
    {
        "name": 'preserve_first_last',
        "type": 'bool',
        "label": '保留首尾',
        "default": True,
        "min": None,
        "max": None,
        "options": [],
        "description": '是否保留首句/首段和尾句/尾段不变',
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
    gran = str(parameters.get("gran", parameters.get("重排粒度", "句子")) or "句子").strip()
    shuf = max(0.0, min(float(parameters.get("shuf", parameters.get("打乱强度", 0.5)) or 0.5), 1.0))
    keep_ends = bool(parameters.get("keep_ends", parameters.get("保留首尾", True)))

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

        if gran == "段落":
            blocks = re.split(r"\n\s*\n", text.strip())
            blocks = [b for b in blocks if b.strip()]
            if len(blocks) >= 2:
                k = int(max(1, len(blocks) * shuf))
                idxs = list(range(len(blocks)))
                np.random.shuffle(idxs)
                idxs = idxs[:k]
                if keep_ends and len(blocks) >= 3:
                    idxs = [i for i in idxs if i not in (0, len(blocks) - 1)]
                    if not idxs:
                        idxs = [1]
                new_blocks = blocks[:]
                shuffled = [blocks[i] for i in idxs]
                np.random.shuffle(shuffled)
                for i, b in zip(idxs, shuffled):
                    new_blocks[i] = b
                out = "\n\n".join(new_blocks)
            else:
                out = text
        else:
            pat = r"[^。！？!?]+[。！？!?]"
            sents = re.findall(pat, text)
            rem = re.sub(pat, "", text).strip()
            if rem:
                sents.append(rem)
            if len(sents) >= 2:
                k = int(max(1, len(sents) * shuf))
                idxs = list(range(len(sents)))
                np.random.shuffle(idxs)
                idxs = idxs[:k]
                if keep_ends and len(sents) >= 3:
                    idxs = [i for i in idxs if i not in (0, len(sents) - 1)]
                    if not idxs:
                        idxs = [1]
                new_sents = sents[:]
                shuffled = [sents[i] for i in idxs]
                np.random.shuffle(shuffled)
                for i, s in zip(idxs, shuffled):
                    new_sents[i] = s
                out = "".join(new_sents)
            else:
                out = text

        of = output_dir / f"{sp.stem}_reorder_{index:04d}{sp.suffix or '.txt'}"
        of.write_text(out, encoding="utf-8")
        outputs.append({
            "source_sample_id": sample.get("id"),
            "output_path": str(of),
            "relative_path": of.name,
            "metadata": {"method": "sentence_reordering", "granularity": gran},
            "status": "created",
        })
        context.set_progress((index + 1) * 100 / target_count, f"Reorder {index+1}/{target_count}")

    return {"ok": True, "outputs": outputs, "logs": []}
