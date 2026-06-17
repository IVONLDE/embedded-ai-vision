"""Image cleaning plugin that filters low-resolution or unreadable images."""

from __future__ import annotations

import struct
from pathlib import Path
from typing import Any


PARAMETERS: list[dict[str, Any]] = [
    {
        "name": "min_width",
        "type": "int",
        "label": "最小宽度",
        "default": 640,
        "min": 1,
        "max": 10000,
        "options": [],
        "description": "图片宽度低于该值时标记为低分辨率",
        "required": False,
    },
    {
        "name": "min_height",
        "type": "int",
        "label": "最小高度",
        "default": 480,
        "min": 1,
        "max": 10000,
        "options": [],
        "description": "图片高度低于该值时标记为低分辨率",
        "required": False,
    },
    {
        "name": "min_file_kb",
        "type": "int",
        "label": "最小文件大小(KB)",
        "default": 20,
        "min": 0,
        "max": 102400,
        "options": [],
        "description": "文件体积低于该值时也会直接过滤",
        "required": False,
    },
]


def run(payload: dict[str, Any], context: Any) -> dict[str, Any]:
    parameters = payload.get("parameters", {}) or {}
    samples = payload.get("input", {}).get("samples", []) or []
    min_width = max(1, int(_parameter_value(parameters, "min_width", 640)))
    min_height = max(1, int(_parameter_value(parameters, "min_height", 480)))
    min_file_kb = max(0, int(_parameter_value(parameters, "min_file_kb", 20)))

    if not samples:
        return {"ok": True, "suggestions": [], "logs": []}

    suggestions: list[dict[str, Any]] = []
    total = max(1, len(samples))

    for index, sample in enumerate(samples):
        if context.is_cancel_requested():
            return {"ok": False, "error_code": "CANCELLED", "message": "任务已取消"}

        context.set_progress((index + 1) * 100 / total, f"图片质量巡检 {index + 1}/{total}")
        sample_path = _sample_path(sample)
        if not sample_path or not sample_path.is_file():
            continue

        width, height = _read_image_size(sample_path)
        file_kb = round(sample_path.stat().st_size / 1024.0, 2)

        if width is None or height is None:
            suggestions.append(
                {
                    "sample_id": sample["id"],
                    "issue_type": "image_unreadable",
                    "suggested_action": "delete",
                    "confidence": 0.99,
                    "message": "图片头信息无法解析，已标记为过滤删除",
                    "details": {
                        "file_path": str(sample_path),
                        "file_size_kb": file_kb,
                        "detected_format": _detect_image_type(sample_path) or "unknown",
                        "processing_result": "filtered_out",
                    },
                }
            )
            continue

        too_small = width < min_width or height < min_height
        too_light = file_kb < min_file_kb
        if not too_small and not too_light:
            continue

        score_parts = []
        if too_small:
            score_parts.append(0.7)
        if too_light:
            score_parts.append(0.3)
        confidence = round(min(0.99, sum(score_parts)), 2)

        message_parts = []
        if too_small:
            message_parts.append(
                f"分辨率 {width}x{height} 低于阈值 {min_width}x{min_height}"
            )
        if too_light:
            message_parts.append(f"文件体积 {file_kb}KB 低于阈值 {min_file_kb}KB")

        suggestions.append(
            {
                "sample_id": sample["id"],
                "issue_type": "image_low_resolution",
                "suggested_action": "delete",
                "confidence": confidence,
                "message": "；".join(message_parts),
                "details": {
                    "file_path": str(sample_path),
                    "width": width,
                    "height": height,
                    "min_width": min_width,
                    "min_height": min_height,
                    "file_size_kb": file_kb,
                    "min_file_kb": min_file_kb,
                    "detected_format": _detect_image_type(sample_path) or "unknown",
                    "processing_result": "filtered_out",
                },
            }
        )

    return {"ok": True, "suggestions": suggestions, "logs": []}


def _sample_path(sample: dict[str, Any]) -> Path | None:
    raw = sample.get("sample_path") or sample.get("path") or sample.get("file_path")
    if not raw:
        return None
    return Path(str(raw))


def _parameter_value(parameters: dict[str, Any], key: str, default: Any) -> Any:
    value = parameters.get(key)
    return default if value is None else value


def _read_image_size(path: Path) -> tuple[int | None, int | None]:
    image_type = _detect_image_type(path)
    if image_type == "png":
        return _read_png_size(path)
    if image_type == "jpeg":
        return _read_jpeg_size(path)
    if image_type == "gif":
        return _read_gif_size(path)
    return None, None


def _detect_image_type(path: Path) -> str | None:
    with path.open("rb") as f:
        header = f.read(16)
    if header.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if header.startswith(b"\xff\xd8"):
        return "jpeg"
    if header.startswith((b"GIF87a", b"GIF89a")):
        return "gif"
    return None


def _read_png_size(path: Path) -> tuple[int | None, int | None]:
    with path.open("rb") as f:
        header = f.read(24)
    if len(header) < 24 or header[:8] != b"\x89PNG\r\n\x1a\n":
        return None, None
    width, height = struct.unpack(">II", header[16:24])
    return int(width), int(height)


def _read_gif_size(path: Path) -> tuple[int | None, int | None]:
    with path.open("rb") as f:
        header = f.read(10)
    if len(header) < 10 or header[:6] not in (b"GIF87a", b"GIF89a"):
        return None, None
    width, height = struct.unpack("<HH", header[6:10])
    return int(width), int(height)


def _read_jpeg_size(path: Path) -> tuple[int | None, int | None]:
    with path.open("rb") as f:
        if f.read(2) != b"\xff\xd8":
            return None, None
        while True:
            marker_prefix = f.read(1)
            if not marker_prefix:
                return None, None
            if marker_prefix != b"\xff":
                continue
            marker = f.read(1)
            while marker == b"\xff":
                marker = f.read(1)
            if not marker or marker in (b"\xd8", b"\xd9"):
                continue
            size_bytes = f.read(2)
            if len(size_bytes) != 2:
                return None, None
            block_size = struct.unpack(">H", size_bytes)[0]
            if block_size < 2:
                return None, None
            if marker in {
                b"\xc0",
                b"\xc1",
                b"\xc2",
                b"\xc3",
                b"\xc5",
                b"\xc6",
                b"\xc7",
                b"\xc9",
                b"\xca",
                b"\xcb",
                b"\xcd",
                b"\xce",
                b"\xcf",
            }:
                block = f.read(block_size - 2)
                if len(block) < 5:
                    return None, None
                height, width = struct.unpack(">HH", block[1:5])
                return int(width), int(height)
            f.seek(block_size - 2, 1)
