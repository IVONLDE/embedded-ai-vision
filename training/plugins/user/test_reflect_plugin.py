# -*- coding: utf-8 -*-
"""测试插件 — 用于验证参数反射功能。"""
from __future__ import annotations

from pathlib import Path
from typing import Any

PARAMETERS: list[dict[str, Any]] = [
    {
        "name": "threshold",
        "type": "float",
        "label": "检测阈值",
        "default": 0.75,
        "min": 0.0,
        "max": 1.0,
        "options": [],
        "description": "判定阈值，越大越严格",
        "required": False,
    },
    {
        "name": "max_iterations",
        "type": "int",
        "label": "最大迭代次数",
        "default": 100,
        "min": 1,
        "max": 10000,
        "options": [],
        "description": "算法最多迭代次数",
        "required": False,
    },
    {
        "name": "mode",
        "type": "select",
        "label": "处理模式",
        "default": "balanced",
        "options": ["fast", "balanced", "thorough"],
        "description": "算法处理强度",
        "required": True,
    },
    {
        "name": "enable_logging",
        "type": "bool",
        "label": "启用日志",
        "default": True,
        "options": [],
        "description": "是否输出详细日志",
        "required": False,
    },
    {
        "name": "output_prefix",
        "type": "string",
        "label": "输出前缀",
        "default": "result_",
        "options": [],
        "description": "输出文件的前缀名",
        "required": False,
    },
]


def run(payload: dict[str, Any], context: Any) -> dict[str, Any]:
    """测试算法入口。"""
    parameters = payload.get("parameters", {})
    output_dir = Path(payload.get("output", {}).get("output_dir") or ".")
    output_dir.mkdir(parents=True, exist_ok=True)

    samples = payload.get("input", {}).get("samples", [])
    if not samples:
        return {"ok": False, "error_code": "NO_INPUT_SAMPLES", "message": "无输入样本"}

    target_count = max(1, int(payload.get("target_count") or len(samples)))

    outputs = []
    for i in range(target_count):
        if context.is_cancel_requested():
            return {"ok": False, "error_code": "CANCELLED", "message": "已取消"}
        sample = samples[i % len(samples)]
        sp = Path(sample.get("sample_path") or "")
        out = output_dir / f"{parameters.get('output_prefix', 'out_')}{i:04d}{sp.suffix or '.dat'}"
        outputs.append({
            "source_sample_id": sample.get("id"),
            "output_path": str(out),
            "relative_path": out.name,
            "metadata": {"method": "test_plugin"},
            "status": "created",
        })
        context.set_progress((i + 1) * 100 / target_count, f"{i+1}/{target_count}")

    return {"ok": True, "outputs": outputs, "logs": []}
