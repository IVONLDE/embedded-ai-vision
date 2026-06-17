"""Text stemming cleaning plugin. Applies lightweight rule-based English stemming."""

import re
from pathlib import Path


PARAMETERS = [
    {
        "name": 'apply',
        "type": 'bool',
        "label": '写入清洗结果',
        "default": True,
        "min": None,
        "max": None,
        "options": [],
        "description": '是否将词干提取后的文本写入磁盘',
        "required": False,
    },
]


def run(payload: dict, context) -> dict:
    parameters = payload.get("parameters", {}) or {}
    samples = payload.get("input", {}).get("samples", []) or []
    output_dir = Path(payload.get("output", {}).get("output_dir", "."))
    apply_changes = bool(parameters.get("apply", True))

    if not samples:
        return {"ok": True, "suggestions": [], "logs": []}

    total = max(len(samples), 1)
    suggestions = []

    for idx, sample in enumerate(samples):
        if context.is_cancel_requested():
            return {"ok": False, "error_code": "CANCELLED", "message": "任务已取消", "details": {}}
        context.set_progress((idx + 1) * 100 / total, f"词干提取 {idx + 1}/{total}")

        sample_path = _sample_path(sample)
        if not sample_path or not sample_path.is_file():
            continue

        text = _read_text(sample_path)
        if text is None:
            continue

        tokens = re.findall(r"[一-鿿]|[A-Za-z0-9_]+", text)
        stemmed = [_stem_token(t) for t in tokens]
        changed = sum(1 for a, b in zip(tokens, stemmed) if a != b)
        if changed:
            confidence = _clamp(changed / max(len(tokens), 1))
            cleaned = " ".join(stemmed)
            cleaned = re.sub(r"\s+", " ", cleaned).strip()
            output_path = ""
            if apply_changes:
                output_dir.mkdir(parents=True, exist_ok=True)
                out_path = output_dir / f"stemmed_{sample_path.name}"
                out_path.write_text(cleaned, encoding="utf-8")
                output_path = str(out_path)
            suggestions.append({
                "sample_id": sample["id"],
                "issue_type": "text_unstemmed",
                "suggested_action": "repair",
                "confidence": confidence,
                "message": f"Stemmed {changed} tokens ({len(tokens)} total)",
                "details": {"changed_count": changed, "total_tokens": len(tokens),
                            "output_file_path": output_path, "processing_result": "stemmed"},
            })

    return {"ok": True, "suggestions": suggestions, "logs": []}


_SUFFIX_RULES: list[tuple[str, int, str]] = [
    # (suffix, min_len, replacement) — replacement empty means strip
    ("ingly", 7, ""),
    ("edly", 6, ""),
    ("ing", 5, ""),
    ("ed", 4, ""),
    ("ies", 5, "y"),
    ("es", 4, ""),
    ("s", 4, ""),
]


def _stem_token(token: str) -> str:
    lower = token.lower()
    # Don't stem CJK characters
    if re.fullmatch(r"[一-鿿]", token):
        return token
    for suffix, min_len, replacement in _SUFFIX_RULES:
        if lower.endswith(suffix) and len(lower) >= min_len:
            stem = lower[:-len(suffix)] + replacement
            return stem if stem else lower
    return lower


def _sample_path(sample: dict):
    path = sample.get("sample_path") or sample.get("path") or sample.get("file_path")
    if not path:
        return None
    return Path(path)


def _read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        try:
            return path.read_text(encoding="latin-1")
        except Exception:
            return None


def _clamp(v: float) -> float:
    return round(max(0.0, min(1.0, v)), 4)
