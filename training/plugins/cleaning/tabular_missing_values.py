"""Tabular missing value handling plugin. Fills or drops missing values in CSV/Excel/JSON files."""

from pathlib import Path


PARAMETERS = [
    {
        "name": 'missing_strategy',
        "type": 'select',
        "label": '填充策略',
        "default": 'mean',
        "min": None,
        "max": None,
        "options": ['mean', 'median', 'constant', 'drop'],
        "description": 'mean: 均值填充; median: 中位数填充; constant: 常数填充; drop: 删除含空行',
        "required": False,
    },
    {
        "name": 'fill_value',
        "type": 'float',
        "label": '填充常数值',
        "default": 0.0,
        "min": None,
        "max": None,
        "options": [],
        "description": '当策略为constant时使用的填充值',
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
        "description": '是否将填充后的表格写入磁盘',
        "required": False,
    },
]


def run(payload: dict, context) -> dict:
    parameters = payload.get("parameters", {}) or {}
    samples = payload.get("input", {}).get("samples", []) or []
    output_dir = Path(payload.get("output", {}).get("output_dir", "."))
    strategy = parameters.get("missing_strategy", "mean")
    fill_value = float(parameters.get("fill_value", 0)) if "fill_value" in parameters else 0
    apply_changes = bool(parameters.get("apply", True))

    if not samples:
        return {"ok": True, "suggestions": [], "logs": []}

    total = max(len(samples), 1)
    suggestions = []

    for idx, sample in enumerate(samples):
        if context.is_cancel_requested():
            return {"ok": False, "error_code": "CANCELLED", "message": "任务已取消", "details": {}}
        context.set_progress((idx + 1) * 100 / total, f"缺失值检测 {idx + 1}/{total}")

        sample_path = _sample_path(sample)
        if not sample_path or not sample_path.is_file():
            continue

        result = _handle_missing(sample_path, output_dir, strategy, fill_value, apply_changes)
        if result is not None:
            suggestions.append({
                "sample_id": sample["id"],
                "issue_type": "missing_values",
                "suggested_action": "repair",
                "confidence": result["confidence"],
                "message": f"Found {result['missing_count']} missing values (strategy: {strategy})",
                "details": {"missing_count": result["missing_count"], "total_cells": result["total_cells"],
                            "strategy": strategy, "output_file_path": result["output_path"],
                            "processing_result": "missing_filled"},
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


def _handle_missing(path: Path, output_dir: Path, strategy: str,
                    fill_value: float, apply: bool) -> dict | None:
    df = _read_table(path)
    if df is None:
        return None

    total_cells = max(df.shape[0] * df.shape[1], 1)
    missing_count = int(df.isna().sum().sum())
    if missing_count == 0:
        return None

    output_path = ""
    if apply:
        try:
            import pandas as pd
            import numpy as np
        except Exception:
            return None
        result = df.copy()
        for col in result.columns:
            if not result[col].isna().any():
                continue
            if strategy == "drop":
                result = result.dropna()
                break
            if pd.api.types.is_numeric_dtype(result[col]):
                if strategy == "median":
                    val = result[col].median()
                elif strategy == "constant":
                    val = fill_value
                else:
                    val = result[col].mean()
            else:
                mode = result[col].mode(dropna=True)
                val = fill_value if strategy == "constant" or mode.empty else mode.iloc[0]
            result[col] = result[col].fillna(val)
        output_dir.mkdir(parents=True, exist_ok=True)
        out_path = output_dir / f"filled_{path.name}"
        _write_table(result, out_path)
        output_path = str(out_path)

    confidence = _clamp(missing_count / total_cells)
    return {"missing_count": missing_count, "total_cells": total_cells,
            "confidence": confidence, "output_path": output_path}


def _clamp(v: float) -> float:
    return round(max(0.0, min(1.0, v)), 4)
