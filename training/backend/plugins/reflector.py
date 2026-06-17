# -*- coding: utf-8 -*-
"""从 .py 插件文件中反射 PARAMETERS 参数列表。"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any


_REQUIRED_FIELDS = {"name", "type", "default"}
_ALLOWED_TYPES = {"string", "int", "float", "bool", "select"}


def _setup_package_context(module, path: Path) -> None:
    """检测文件内容中是否有相对导入，如有则设置包的上下文。

    对于 plugins/generation/xxx.py，设置 __package__ = "plugins.generation"。
    """
    try:
        content = path.read_text(encoding="utf-8")
    except Exception:
        return

    has_relative = any(
        line.strip().startswith(("from .", "from .."))
        for line in content.split("\n")
    )
    if not has_relative:
        return

    # 从路径推断包名：plugins/generation/xxx.py → plugins.generation
    parts = list(path.parts)
    # 找到 "plugins" 在路径中的位置
    try:
        plugins_idx = parts.index("plugins")
    except ValueError:
        return

    # 包名从 plugins 开始，直到文件所在目录
    pkg_parts = parts[plugins_idx:-1]  # 去掉文件名
    if pkg_parts:
        module.__package__ = ".".join(pkg_parts)


def reflect_parameters(script_path: Path) -> dict[str, Any]:
    """加载 .py 脚本，提取并校验 PARAMETERS 变量。

    Returns:
        {"ok": True, "parameters": [...]}
        {"ok": False, "error": "..."}
    """
    path = Path(script_path).resolve()
    if not path.exists():
        return {"ok": False, "error": f"文件不存在: {path}"}
    if path.suffix.lower() != ".py":
        return {"ok": False, "error": "仅支持 .py 文件"}

    module_name = f"_isg_reflect_{path.stem}"

    try:
        spec = importlib.util.spec_from_file_location(module_name, path)
        if spec is None or spec.loader is None:
            return {"ok": False, "error": f"无法解析模块: {path}"}

        module = importlib.util.module_from_spec(spec)

        # 检测是否需要包的相对导入支持
        _setup_package_context(module, path)

        sys.modules[module_name] = module
        spec.loader.exec_module(module)

        parameters = getattr(module, "PARAMETERS", None)
        if parameters is None:
            return {"ok": False, "error": "脚本中未找到 PARAMETERS 变量。请在 .py 文件中声明 PARAMETERS = [...]"}

        valid, error = _validate_parameters(parameters)
        if not valid:
            return {"ok": False, "error": f"PARAMETERS 格式错误: {error}"}

        normalized = _normalize_parameters(parameters)
        return {"ok": True, "parameters": normalized}

    except Exception as exc:
        return {"ok": False, "error": f"脚本加载失败: {exc}"}
    finally:
        sys.modules.pop(module_name, None)


def _validate_parameters(params: Any) -> tuple[bool, str]:
    if not isinstance(params, list):
        return False, "PARAMETERS 必须是 list 类型"
    for i, item in enumerate(params):
        if not isinstance(item, dict):
            return False, f"第 {i} 项不是 dict 类型"
        missing = _REQUIRED_FIELDS - set(item.keys())
        if missing:
            return False, f"第 {i} 项缺少必填字段: {missing}"
        ptype = item.get("type", "")
        if ptype not in _ALLOWED_TYPES:
            return False, f"第 {i} 项 type='{ptype}' 不合法，允许: {_ALLOWED_TYPES}"
        if ptype == "select":
            options = item.get("options", [])
            if not isinstance(options, list) or len(options) == 0:
                return False, f"第 {i} 项 type='select' 但 options 为空或非列表"
        if ptype in ("int", "float"):
            for key in ("min", "max"):
                val = item.get(key)
                if val is not None and not isinstance(val, (int, float)):
                    return False, f"第 {i} 项 {key}={val} 不是数值类型"
    return True, ""


def _normalize_parameters(params: list[dict]) -> list[dict]:
    result = []
    for item in params:
        normalized = {
            "name": str(item.get("name", "")),
            "type": str(item.get("type", "string")),
            "label": str(item.get("label", item.get("name", ""))),
            "default": item.get("default", ""),
            "min": item.get("min"),
            "max": item.get("max"),
            "options": list(item.get("options") or []),
            "description": str(item.get("description", "")),
            "required": bool(item.get("required", False)),
        }
        result.append(normalized)
    return result
