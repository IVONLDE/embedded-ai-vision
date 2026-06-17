"""Tabular outlier handling plugin. Detects and clips outliers using IQR or z-score method."""

from pathlib import Path


PARAMETERS = [
    {
        "name": 'outlier_method',
        "type": 'select',
        "label": '检测方法',
        "default": 'iqr',
        "min": None,
        "max": None,
        "options": ['iqr', 'zscore'],
        "description": 'iqr: 四分位距法; zscore: z分数法',
        "required": False,
    },
    {
        "name": 'zscore_threshold',
        "type": 'float',
        "label": 'z分数阈值',
        "default": 3.0,
        "min": 1.0,
        "max": 10.0,
        "options": [],
        "description": 'z分数超过此阈值视为异常值',
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
        "description": '是否将处理后的表格写入磁盘',
        "required": False,
    },
]


def run(payload: dict, context) -> dict:
    parameters = payload.get("parameters", {}) or {}
    samples = payload.get("input", {}).get("samples", []) or []
    output_dir = Path(payload.get("output", {}).get("output_dir", "."))
    method = parameters.get("outlier_method", "iqr")
    zscore_threshold = float(parameters.get("zscore_threshold", 3.0))
    apply_changes = bool(parameters.get("apply", True))

    if not samples:
        return {"ok": True, "suggestions": [], "logs": []}

    total = max(len(samples), 1)
    suggestions = []

    for idx, sample in enumerate(samples):
        if context.is_cancel_requested():
            return {"ok": False, "error_code": "CANCELLED", "message": "任务已取消", "details": {}}
        context.set_progress((idx + 1) * 100 / total, f"异常值检测 {idx + 1}/{total}")

        sample_path = _sample_path(sample)
        if not sample_path or not sample_path.is_file():
            continue

        result = _handle_outliers(sample_path, output_dir, method, zscore_threshold, apply_changes)
        if result is not None:
            suggestions.append({
                "sample_id": sample["id"],
                "issue_type": "outliers",
                "suggested_action": "repair",
                "confidence": result["confidence"],
                "message": f"Found {result['outlier_count']} outliers ({method} method)",
                "details": {"outlier_count": result["outlier_count"],
                            "numeric_columns": result["numeric_columns"],
                            "method": method, "output_file_path": result["output_path"],
                            "processing_result": "outliers_clipped"},
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


def _handle_outliers(path: Path, output_dir: Path, method: str,
                     z_threshold: float, apply: bool) -> dict | None:
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

    result_df = df.copy()
    outlier_count = 0
    for col in numeric_cols:
        series = result_df[col]
        if method == "zscore":
            std = series.std()
            if not std or std == 0:
                continue
            mean = series.mean()
            lower, upper = mean - z_threshold * std, mean + z_threshold * std
            mask = ((series - mean).abs() / std) > z_threshold
        else:
            q1, q3 = series.quantile(0.25), series.quantile(0.75)
            iqr = q3 - q1
            if not iqr or iqr == 0:
                continue
            lower, upper = q1 - 1.5 * iqr, q3 + 1.5 * iqr
            mask = (series < lower) | (series > upper)
        outlier_count += int(mask.sum())
        result_df.loc[mask, col] = series.clip(lower, upper)

    if outlier_count == 0:
        return None

    total_cells = max(len(df) * len(numeric_cols), 1)
    output_path = ""
    if apply:
        output_dir.mkdir(parents=True, exist_ok=True)
        out_path = output_dir / f"nooutlier_{path.name}"
        _write_table(result_df, out_path)
        output_path = str(out_path)

    return {"outlier_count": outlier_count, "numeric_columns": numeric_cols,
            "confidence": _clamp(outlier_count / total_cells), "output_path": output_path}


def _clamp(v: float) -> float:
    return round(max(0.0, min(1.0, v)), 4)
