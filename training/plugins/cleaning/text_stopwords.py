"""Text stop-word removal plugin."""

import re
from pathlib import Path


DEFAULT_STOP_WORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "has",
    "he", "in", "is", "it", "its", "of", "on", "that", "the", "to", "was",
    "were", "will", "with", "this", "these", "those", "or", "not", "but",
    "we", "you", "they", "i",
    "的", "了", "和", "是", "在", "我", "有", "就", "不", "人", "都", "一",
    "一个", "上", "也", "很", "到", "说", "要", "去", "你", "会", "着", "没有",
}

PARAMETERS = [
    {
        "name": 'stop_words',
        "type": 'string',
        "label": '额外停用词',
        "default": '',
        "min": None,
        "max": None,
        "options": [],
        "description": '用户自定义的额外停用词，逗号分隔',
        "required": False,
    },
    {
        "name": 'apply',
        "type": 'bool',
        "label": '写入清洗结果',
        "default": True,
        "min": None,
        "max": None,
        "options": [],
        "description": '是否将去停用词后的文本写入磁盘',
        "required": False,
    },
]


def run(payload: dict, context) -> dict:
    parameters = payload.get("parameters", {}) or {}
    samples = payload.get("input", {}).get("samples", []) or []
    output_dir = Path(payload.get("output", {}).get("output_dir", "."))
    apply_changes = bool(parameters.get("apply", True))

    extra_words = _parse_stop_words(parameters.get("stop_words"))
    stop_words = DEFAULT_STOP_WORDS | {str(w).lower() for w in extra_words}

    if not samples:
        return {"ok": True, "suggestions": [], "logs": []}

    total = max(len(samples), 1)
    suggestions = []

    for idx, sample in enumerate(samples):
        if context.is_cancel_requested():
            return {"ok": False, "error_code": "CANCELLED", "message": "任务已取消", "details": {}}
        context.set_progress((idx + 1) * 100 / total, f"停用词过滤 {idx + 1}/{total}")

        sample_path = _sample_path(sample)
        if not sample_path or not sample_path.is_file():
            continue

        text = _read_text(sample_path)
        if text is None:
            continue

        tokens = _tokenize(text)
        cleaned_source = _remove_stop_words(text, stop_words)
        filtered = _tokenize(cleaned_source)
        removed = len(tokens) - len(filtered)
        if removed:
            confidence = _clamp(removed / max(len(tokens), 1))
            cleaned = " ".join(filtered)
            cleaned = re.sub(r"\s+", " ", cleaned).strip()
            output_path = ""
            if apply_changes:
                output_dir.mkdir(parents=True, exist_ok=True)
                out_path = output_dir / f"nostop_{sample_path.name}"
                out_path.write_text(cleaned, encoding="utf-8")
                output_path = str(out_path)
            suggestions.append({
                "sample_id": sample["id"],
                "issue_type": "text_stopwords",
                "suggested_action": "repair",
                "confidence": confidence,
                "message": f"Removed {removed} stop words ({len(tokens)} tokens total)",
                "details": {"removed_count": removed, "total_tokens": len(tokens),
                            "output_file_path": output_path, "processing_result": "stopwords_removed"},
            })

    return {"ok": True, "suggestions": suggestions, "logs": []}


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


def _parse_stop_words(value) -> set[str]:
    if not value:
        return set()
    if isinstance(value, str):
        return {word.strip() for word in re.split(r"[,，;\s]+", value) if word.strip()}
    try:
        return {str(word).strip() for word in value if str(word).strip()}
    except TypeError:
        word = str(value).strip()
        return {word} if word else set()


def _tokenize(text: str) -> list[str]:
    return re.findall(r"[一-鿿]+|[A-Za-z0-9_]+", text)


def _remove_stop_words(text: str, stop_words: set[str]) -> str:
    cleaned = text
    for word in sorted(stop_words, key=len, reverse=True):
        if re.search(r"[A-Za-z0-9_]", word):
            cleaned = re.sub(rf"\b{re.escape(word)}\b", " ", cleaned, flags=re.IGNORECASE)
        else:
            cleaned = cleaned.replace(word, " ")
    return cleaned


def _clamp(v: float) -> float:
    return round(max(0.0, min(1.0, v)), 4)
