# -*- coding: utf-8 -*-
"""
自定义算法插件模板。

使用方法：
  1. 复制此文件，重命名为 your_algorithm.py
  2. 修改 PARAMETERS 列表，声明你的算法参数
  3. 实现 run(payload, context) 函数
  4. 在 ISG 应用 "算法配置" 页面注册此插件

================================================================================
PARAMETERS 参数声明规范
================================================================================

PARAMETERS 是一个 list[dict]，每个 dict 描述一个参数，支持以下字段：

  name        - (必填) 参数变量名，英文，如 "threshold"。代码中通过
                parameters.get("threshold") 获取
  type        - (必填) 参数类型: string / int / float / bool / select
  label       - (必填) 参数显示名称，中文，如 "阈值"
  default     - (必填) 默认值，类型需与 type 匹配
  min         - (可选) 最小值，仅 int/float 类型生效
  max         - (可选) 最大值，仅 int/float 类型生效
  options     - (可选) 枚举选项列表，仅 select 类型生效，如 ["A", "B", "C"]
  description - (可选) 参数说明文本
  required    - (可选) 是否必填，默认 false

================================================================================
run(payload, context) 函数规范
================================================================================

  payload = {
      "parameters": {...},       # 参数字典，key=参数name, value=用户设定的值
      "algorithm_key": "...",    # 算法唯一标识
      "input": {
          "dataset_id": ...,     # 源数据集 ID
          "dataset_path": "...", # 源数据集路径
          "samples": [...]       # 样本列表
      },
      "output": {
          "output_dir": "..."    # 输出目录
      },
      "target_count": ...        # 期望生成数量
  }

  context 提供:
      context.set_progress(percent, message)  # 更新进度 0-100
      context.log(level, message, payload)    # 记录日志
      context.is_cancel_requested() -> bool   # 检查是否取消

  返回值:
      成功: {"ok": True, "outputs": [...], "logs": [...]}
      失败: {"ok": False, "error_code": "...", "message": "..."}
      取消: {"ok": False, "error_code": "CANCELLED", "message": "..."}
================================================================================
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

# ============================================================================
# 参数声明 — 修改此列表以定义你的算法参数
# ============================================================================

PARAMETERS: list[dict[str, Any]] = [
    {
        "name": "threshold",
        "type": "float",
        "label": "阈值",
        "default": 0.5,
        "min": 0.0,
        "max": 1.0,
        "options": [],
        "description": "判定阈值，范围 0~1",
        "required": False,
    },
    {
        "name": "enable_feature",
        "type": "bool",
        "label": "启用特性",
        "default": True,
        "options": [],
        "description": "是否启用某特性",
        "required": False,
    },
    {
        "name": "mode",
        "type": "select",
        "label": "处理模式",
        "default": "normal",
        "options": ["normal", "aggressive", "conservative"],
        "description": "算法处理强度模式",
        "required": False,
    },
]


# ============================================================================
# 算法入口 — 实现你的算法逻辑
# ============================================================================

def run(payload: dict[str, Any], context: Any) -> dict[str, Any]:
    """算法执行入口。"""
    parameters = payload.get("parameters", {}) or {}
    output_dir = Path(payload.get("output", {}).get("output_dir") or ".")
    output_dir.mkdir(parents=True, exist_ok=True)

    samples = payload.get("input", {}).get("samples", []) or []
    if not samples:
        return {"ok": False, "error_code": "NO_INPUT_SAMPLES", "message": "无输入样本"}

    target_count = max(1, int(payload.get("target_count") or len(samples)))

    # ---- 读取参数 ----
    threshold = float(parameters.get("threshold", 0.5))
    enable_feature = _as_bool(parameters.get("enable_feature", True))
    mode = str(parameters.get("mode", "normal"))

    # ---- 处理样本 ----
    outputs: list[dict[str, Any]] = []
    for index in range(target_count):
        if context.is_cancel_requested():
            return {"ok": False, "error_code": "CANCELLED", "message": "任务已取消"}

        sample = samples[index % len(samples)]
        source_path = Path(sample.get("sample_path") or sample.get("path") or "")
        if not source_path.exists():
            continue

        # TODO: 在此处实现你的算法逻辑
        # 示例：直接复制文件
        import shutil
        output_path = output_dir / f"{source_path.stem}_out_{index:04d}{source_path.suffix or '.dat'}"
        shutil.copy2(source_path, output_path)

        outputs.append({
            "source_sample_id": sample.get("id"),
            "output_path": str(output_path),
            "relative_path": output_path.name,
            "metadata": {
                "method": "custom_algorithm",
                "algorithm_key": payload.get("algorithm_key", ""),
                "parameters": {"threshold": threshold, "enable_feature": enable_feature, "mode": mode},
            },
            "status": "created",
        })
        context.set_progress((index + 1) * 100 / target_count, f"已处理 {index + 1}/{target_count}")

    return {"ok": True, "outputs": outputs, "logs": []}


def _as_bool(value: Any) -> bool:
    """辅助函数：将值转为布尔类型。"""
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "y", "是"}
