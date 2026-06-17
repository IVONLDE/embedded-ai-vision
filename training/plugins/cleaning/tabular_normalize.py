"""Tabular normalization plugin. Applies min-max or z-score normalization to numeric columns."""

from pathlib import Path


PARAMETERS = [
    {
        "name": 'normalization',
        "type": 'select',
        "label": '归一化方法',
        "default": 'minmax',
        "min": None,
        "max": None,
        "options": ['minmax', 'zscore'],
        "description": 'minmax: 最小-最大归一化; zscore: z分数标准化',
        "required": False,
    },
    {
        "name": 'apply',
        "type": 'bool',
        "label": '写入修复结果',
        "default": True,
        "min": None,
        "max": None,
        "options": [],
        "description": '是否将归一化后的表格写入磁盘',
        "required": False,
    },
]


def run(payload: dict, context) -> dict:
    parameters = payload.get("parameters", {}) or {}
    samples = payload.get("input", {}).get("samples", []) or []
    output_dir = Path(payload.get("output", {}).get("output_dir", "."))
    method = parameters.get("normalization", "minmax")
    apply_changes = bool(parameters.get("apply", True))

    if not samples:
        return {"ok": True, "suggestions": [], "logs": []}

    total = max(len(samples), 1)
    suggestions = []

    for idx, sample in enumerate(samples):
        if context.is_cancel_requested():
            return {"ok": False, "error_code": "CANCELLED", "message": "任务已取消", "details": {}}
        context.set_progress((idx + 1) * 100 / total, f"归一化检测 {idx + 1}/{total}")

        sample_path = _sample_path(sample)
        if not sample_path or not sample_path.is_file():
            continue

        result = _normalize(sample_path, output_dir, method, apply_changes)
        if result is not None:
            suggestions.append({
                "sample_id": sample["id"],
                "issue_type": "unnormalized_values",
                "suggested_action": "repair",
                "confidence": 0.8,
                "message": f"Normalized {len(result['columns'])} numeric columns ({method})",
                "details": {"columns": result["columns"], "method": method,
                            "output_file_path": result["output_path"],
                            "processing_result": "normalized"},
            })

    return {"ok": True, "suggestions": suggestions, "logs": []}


def _sample_path(sample: dict):
    path = sample.get("sample_path") or sample.get("path") or sample.get("file_path")
    if not path:
        return None
    return Path(path)


def _read_table(path: Path):
    try:
        import pandas as pd
    except Exception:
        return None
    try:
        lower = path.suffix.lower()
        if lower == ".csv":
            return pd.read_csv(str(path))
        if lower in {".xlsx", ".xls"}:
            return pd.read_excel(str(path))
        if lower == ".json":
            return pd.read_json(str(path))
        return None
    except Exception:
        return None


def _write_table(df, path: Path):
    lower = path.suffix.lower()
    if lower == ".csv":
        df.to_csv(str(path), index=False)
    elif lower in {".xlsx", ".xls"}:
        df.to_excel(str(path), index=False)
    elif lower == ".json":
        df.to_json(str(path), orient="records", force_ascii=False)


def _normalize(path: Path, output_dir: Path, method: str, apply: bool) -> dict | None:
    try:
        import numpy as np
    except Exception:
        return None
    df = _read_table(path)
    if df is None:
        return None

    numeric_cols = list(df.select_dtypes(include=[np.number]).columns)
    if not numeric_cols:
        return None

    result = df.copy()
    for col in numeric_cols:
        series = result[col].astype(float)
        if method == "zscore":
            std = series.std()
            result[col] = 0.0 if not std or std == 0 else (series - series.mean()) / std
        else:
            mn, mx = series.min(), series.max()
            result[col] = 0.0 if mn == mx else (series - mn) / (mx - mn)

    output_path = ""
    if apply:
        output_dir.mkdir(parents=True, exist_ok=True)
        out_path = output_dir / f"normalized_{path.name}"
        _write_table(result, out_path)
        output_path = str(out_path)

    return {"columns": [str(c) for c in numeric_cols], "output_path": output_path}
