"""Text deduplicate cleaning plugin. Removes duplicate lines or tokens."""

import re
from pathlib import Path


PARAMETERS = [
    {
        "name": 'deduplicate_mode',
        "type": 'select',
        "label": '去重模式',
        "default": 'line',
        "min": None,
        "max": None,
        "options": ['line', 'token'],
        "description": 'line: 按行去重; token: 按词去重',
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
        "description": '是否将去重后的文本写入磁盘',
        "required": False,
    },
]


def run(payload: dict, context) -> dict:
    parameters = payload.get("parameters", {}) or {}
    samples = payload.get("input", {}).get("samples", []) or []
    output_dir = Path(payload.get("output", {}).get("output_dir", "."))
    mode = parameters.get("deduplicate_mode", "line")
    apply_changes = bool(parameters.get("apply", True))

    if not samples:
        return {"ok": True, "suggestions": [], "logs": []}

    total = max(len(samples), 1)
    suggestions = []

    for idx, sample in enumerate(samples):
        if context.is_cancel_requested():
            return {"ok": False, "error_code": "CANCELLED", "message": "任务已取消", "details": {}}
        context.set_progress((idx + 1) * 100 / total, f"文本去重 {idx + 1}/{total}")

        sample_path = _sample_path(sample)
        if not sample_path or not sample_path.is_file():
            continue

        text = _read_text(sample_path)
        if text is None:
            continue

        cleaned, dup_count = _deduplicate(text, mode)
        if dup_count:
            total_units = len(_tokenize(text)) if mode == "token" else len([l for l in text.splitlines() if l.strip()])
            confidence = _clamp(dup_count / max(total_units, 1))
            output_path = ""
            if apply_changes:
                output_path = _write_cleaned(sample_path, output_dir, cleaned)
            suggestions.append({
                "sample_id": sample["id"],
                "issue_type": "text_duplicate",
                "suggested_action": "repair",
                "confidence": confidence,
                "message": f"Found {dup_count} duplicate {'tokens' if mode == 'token' else 'lines'}",
                "details": {"duplicate_count": dup_count, "mode": mode,
                            "output_file_path": output_path, "processing_result": "deduplicated"},
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


def _tokenize(text: str) -> list[str]:
    return re.findall(r"[一-鿿]|[A-Za-z0-9_]+", text)


def _deduplicate(text: str, mode: str) -> tuple[str, int]:
    if mode == "token":
        seen = set()
        result = []
        dup_count = 0
        for token in _tokenize(text):
            key = token.lower()
            if key in seen:
                dup_count += 1
                continue
            seen.add(key)
            result.append(token)
        return " ".join(result), dup_count

    lines = [line.strip() for line in text.splitlines() if line.strip()]
    seen = set()
    result_lines = []
    dup_count = 0
    for line in lines:
        key = line.lower()
        if key in seen:
            dup_count += 1
            continue
        seen.add(key)
        result_lines.append(line)
    cleaned = "\n".join(result_lines) if lines else text
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned, dup_count


def _write_cleaned(orig: Path, output_dir: Path, cleaned: str) -> str:
    output_dir.mkdir(parents=True, exist_ok=True)
    out_path = output_dir / f"dedup_{orig.name}"
    out_path.write_text(cleaned, encoding="utf-8")
    return str(out_path)


def _clamp(v: float) -> float:
    return round(max(0.0, min(1.0, v)), 4)
