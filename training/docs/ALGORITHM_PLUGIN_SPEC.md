# ISG 算法插件开发规范 v1.0

## 概述

ISG 算法插件是一个标准 Python 模块（`.py` 文件），实现 `run(payload, context)` 入口函数，并声明模块级 `PARAMETERS` 列表。插件注册后，系统自动反射参数列表，在 UI 中生成对应的参数配置控件。

## 文件结构

```python
# -*- coding: utf-8 -*-
"""插件简要说明。"""
from __future__ import annotations

from pathlib import Path
from typing import Any

# ============================================================
# PARAMETERS — 参数声明（必填）
# ============================================================

PARAMETERS: list[dict[str, Any]] = [
    {
        "name": "threshold",        # 参数变量名（英文，代码中使用此 key 读取）
        "type": "float",            # 类型：string / int / float / bool / select
        "label": "阈值",            # UI 中显示的中文名称
        "default": 0.5,             # 默认值
        "min": 0.0,                 # 最小值（仅 int/float 类型生效，可选）
        "max": 1.0,                 # 最大值（仅 int/float 类型生效，可选）
        "options": [],              # 枚举选项列表（仅 select 类型生效）
        "description": "判定阈值",  # 参数说明文本
        "required": False,          # 是否必填
    },
]

# ============================================================
# run — 算法入口（必填）
# ============================================================

def run(payload: dict[str, Any], context: Any) -> dict[str, Any]:
    """算法执行入口。

    Args:
        payload: 包含 parameters, input, output 等字段（见下文）
        context: 提供进度上报、日志、取消检查等方法

    Returns:
        {"ok": True, "outputs": [...], "logs": [...]}  成功
        {"ok": False, "error_code": "...", "message": "..."}  失败
    """
    ...
```

## PARAMETERS 字段规范

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `name` | str | 是 | 参数变量名，英文小写+下划线，如 `threshold`。代码中通过 `parameters.get("threshold")` 获取 |
| `type` | str | 是 | `string` / `int` / `float` / `bool` / `select` |
| `label` | str | 是 | UI 显示名称，中文，如 `"检测阈值"` |
| `default` | * | 是 | 默认值，类型须与 `type` 匹配 |
| `min` | float | 否 | 最小值，仅 `int`/`float` 生效 |
| `max` | float | 否 | 最大值，仅 `int`/`float` 生效 |
| `options` | list | 否 | 枚举选项，仅 `select` 生效，如 `["A", "B", "C"]` |
| `description` | str | 否 | 参数说明文本 |
| `required` | bool | 否 | 是否必填，默认 `false` |

### 类型约定

| type 值 | default 示例 | 说明 |
|---------|-------------|------|
| `string` | `"normal"` | 字符串 |
| `int` | `100` | 整数 |
| `float` | `0.5` | 浮点数 |
| `bool` | `True` / `False` | 布尔值 |
| `select` | `"A"` | 枚举选择，`options` 必填且非空 |

> **注意：** 不再使用 `number`、`integer`、`json` 等类型名。整数用 `int`，浮点数用 `float`。

## run() 函数规范

### 函数签名

```python
def run(payload: dict[str, Any], context: Any) -> dict[str, Any]:
```

### payload 结构

```python
payload = {
    "algorithm_key": "generation.image.geometric_transform",  # 算法唯一标识
    "parameters": {           # 用户配置的参数字典，key = PARAMETERS 中的 name
        "rotation_degrees": 10.0,
        "scale": 1.0,
    },
    "input": {
        "dataset_id": 1,                  # 源数据集 ID
        "dataset_path": "/data/datasets/abc",  # 源数据集路径
        "samples": [                      # 样本列表
            {
                "id": 1,
                "sample_path": "/data/datasets/abc/img_001.jpg",
                "modality": "image",
                "labels_json": ["ship"],
            },
        ],
    },
    "output": {
        "output_dir": "/data/tasks/42/output",  # 输出目录（已创建）
    },
    "target_count": 100,  # 期望生成数量（生成/增强类）
}
```

### context 方法

| 方法 | 说明 |
|------|------|
| `context.set_progress(percent, message)` | 更新进度 0–100，message 为描述文本 |
| `context.log(level, message, payload)` | 记录日志，level: "info" / "warn" / "error" |
| `context.is_cancel_requested() -> bool` | 检查是否收到取消请求，应周期性检查 |

### 返回值

**成功（清洗建议类）：**
```python
{
    "ok": True,
    "suggestions": [
        {
            "sample_id": 1,
            "issue_type": "blur",
            "suggested_action": "repair",
            "confidence": 0.85,
            "message": "图像模糊度 45.2",
            "details": {"blur_score": 45.2, "output_path": "/path/to/repaired.jpg"},
        }
    ],
    "logs": [],
}
```

**成功（生成/增强类）：**
```python
{
    "ok": True,
    "outputs": [
        {
            "source_sample_id": 1,
            "output_path": "/data/tasks/42/output/img_001_geo_0000.jpg",
            "relative_path": "img_001_geo_0000.jpg",
            "metadata": {"method": "geometric_transform", "parameters": {...}},
            "status": "created",
        }
    ],
    "logs": [],
}
```

**失败：**
```python
{
    "ok": False,
    "error_code": "NO_INPUT_SAMPLES",  # 大写+下划线
    "message": "无输入样本",
}
```

**取消：**
```python
{
    "ok": False,
    "error_code": "CANCELLED",
    "message": "任务已取消",
}
```

## 读取参数的推荐方式

```python
def run(payload: dict[str, Any], context: Any) -> dict[str, Any]:
    parameters = payload.get("parameters", {}) or {}

    # 数值类型
    threshold = float(parameters.get("threshold", 0.5))
    max_iter = int(parameters.get("max_iterations", 100))

    # 字符串/选择类型
    mode = str(parameters.get("mode", "normal"))

    # 布尔类型 — 使用辅助函数
    enable = _as_bool(parameters.get("enable_logging", True))

    # 列表类型
    stop_words = list(parameters.get("stop_words") or [])

    ...

def _as_bool(value) -> bool:
    """将任意值转为布尔类型。"""
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "y", "是"}
```

## 命名约定

1. **参数 name 字段：** 英文小写 + 下划线，如 `blur_threshold`、`learning_rate`
2. **参数 label 字段：** 简短中文，如 `"模糊阈值"`、`"学习率"`
3. **算法 key：** 用 `.` 分隔命名空间，如 `generation.image.geometric_transform`
4. **算法 name：** UI 展示用中文名，如 `"几何变换"`

## 完整示例

参见 `plugins/user/_TEMPLATE.py`。

## 注意事项

1. `PARAMETERS` 必须是模块级变量，不能定义在函数内部
2. 无参数插件仍需声明 `PARAMETERS = []`（空列表）
3. 不要在 `run()` 中修改 `PARAMETERS`
4. 所有文件 I/O 使用 `pathlib.Path`，路径用 `/` 分隔
5. 大文件或耗时操作应周期性调用 `context.is_cancel_requested()`
6. 插件可放置在 `plugins/user/` 目录，或通过 `module_path` 引用已安装的包
