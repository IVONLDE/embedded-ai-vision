from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from ._image_io import read_image, write_image


PARAMETERS = [
    {
        "name": "occlusion_type",
        "type": "select",
        "label": "遮挡类型",
        "default": "random_erase",
        "min": None,
        "max": None,
        "options": ["random_erase", "cutout", "gridmask"],
        "description": "遮挡增强方式",
        "required": False,
    },
    {
        "name": "erase_count",
        "type": "int",
        "label": "擦除次数",
        "default": 1,
        "min": 1,
        "max": 20,
        "options": [],
        "description": "随机擦除的矩形数量",
        "required": False,
    },
    {
        "name": "area_ratio",
        "type": "float",
        "label": "面积比例",
        "default": 0.2,
        "min": 0.01,
        "max": 0.5,
        "options": [],
        "description": "擦除区域占图像面积的比例上限",
        "required": False,
    },
]


def run(payload: dict, context) -> dict:
    """擦除遮挡增强：Random Erasing / Cutout / GridMask。"""
    parameters = payload.get("parameters", {}) or {}
    output_dir = Path(payload.get("output", {}).get("output_dir") or ".")
    output_dir.mkdir(parents=True, exist_ok=True)

    samples = payload.get("input", {}).get("samples", []) or []
    if not samples:
        return {"ok": False, "error_code": "NO_INPUT_SAMPLES", "message": "未提供源样本。"}

    target_count = max(1, int(payload.get("target_count") or len(samples)))

    mode = str(
        parameters.get(
            "occlusion_type",
            parameters.get("mode", parameters.get("遮挡类型", "random_erase")),
        )
        or "random_erase"
    ).lower()
    fill_mode = str(parameters.get("fill_mode", parameters.get("填充值模式", "mean")) or "mean").lower()
    erase_count = int(parameters.get("erase_count", parameters.get("擦除次数", 1)) or 1)
    area_ratio = float(parameters.get("area_ratio", parameters.get("擦除面积比例", 0.2)) or 0.2)
    min_aspect = float(parameters.get("min_aspect", parameters.get("最小宽高比", 0.3)) or 0.3)
    max_aspect = float(parameters.get("max_aspect", parameters.get("最大宽高比", 3.0)) or 3.0)
    cutout_count = int(parameters.get("cutout_count", parameters.get("切块数量", 1)) or 1)
    cut_ratio = float(parameters.get("cut_ratio", parameters.get("切块面积比例", 0.25)) or 0.25)
    grid_size = int(parameters.get("grid_size", parameters.get("栅格大小", 32)) or 32)
    mask_ratio = float(parameters.get("mask_ratio", parameters.get("遮罩比例", 0.4)) or 0.4)

    outputs = []
    for index in range(target_count):
        if context.is_cancel_requested():
            return {"ok": False, "error_code": "CANCELLED", "message": "任务已取消。"}

        sample = samples[index % len(samples)]
        source_path = Path(sample.get("sample_path") or sample.get("path") or sample.get("file_path") or "")
        img = read_image(source_path)
        if img is None:
            continue

        if len(img.shape) == 2:
            img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)

        h, w = img.shape[:2]
        out = img.copy()

        fill_color = _resolve_fill_color(out, fill_mode)

        if mode in {"random_erase", "random_erasing"}:
            for _ in range(max(1, erase_count)):
                _apply_random_erasing(out, h, w, area_ratio, min_aspect, max_aspect, fill_mode, fill_color)
        elif mode == "cutout":
            for _ in range(max(1, cutout_count)):
                _apply_cutout(out, h, w, cut_ratio, fill_mode, fill_color)
        elif mode == "gridmask":
            out = _apply_gridmask(out, h, w, grid_size, mask_ratio, fill_color)
        else:
            for _ in range(max(1, erase_count)):
                _apply_random_erasing(out, h, w, area_ratio, min_aspect, max_aspect, fill_mode, fill_color)

        output_path = output_dir / f"{source_path.stem}_occlusion_{index:04d}{source_path.suffix or '.jpg'}"
        if not write_image(output_path, out):
            return {"ok": False, "error_code": "IMAGE_WRITE_ERROR", "message": f"Cannot write image: {output_path}"}

        outputs.append(
            {
                "source_sample_id": sample.get("id"),
                "output_path": str(output_path),
                "relative_path": output_path.name,
                "metadata": {
                    "method": "occlusion",
                    "algorithm_key": payload.get("algorithm_key", "generation.image.occlusion"),
                    "parameters": {
                        "occlusion_type": mode,
                        "erase_count": erase_count,
                        "area_ratio": area_ratio,
                        "fill_mode": fill_mode,
                        "cutout_count": cutout_count,
                        "cut_ratio": cut_ratio,
                        "grid_size": grid_size,
                        "mask_ratio": mask_ratio,
                    },
                },
                "status": "created",
            }
        )
        context.set_progress((index + 1) * 100 / target_count, f"擦除遮挡 {index + 1}/{target_count}")

    return {"ok": True, "outputs": outputs, "logs": []}


def _resolve_fill_color(img, fill_mode: str):
    if fill_mode == "mean":
        return tuple(int(x) for x in np.mean(img.reshape(-1, img.shape[2]), axis=0))
    if fill_mode == "zero":
        return (0, 0, 0)
    return None


def _apply_random_erasing(out, h, w, area_ratio, min_aspect, max_aspect, fill_mode, fill_color):
    target_area = h * w * area_ratio
    aspect = np.random.uniform(min_aspect, max_aspect)
    hh = int(round(np.sqrt(target_area / aspect)))
    ww = int(round(aspect * hh))
    if hh <= 0 or ww <= 0:
        return
    hh = min(hh, max(1, h // 2))
    ww = min(ww, max(1, w // 2))
    x = int(np.random.randint(0, max(1, w - ww)))
    y = int(np.random.randint(0, max(1, h - hh)))
    _fill_rect(out, x, y, ww, hh, fill_mode, fill_color)


def _apply_cutout(out, h, w, cut_ratio, fill_mode, fill_color):
    ww = int(np.sqrt(w * h * cut_ratio))
    hh = ww
    ww = min(ww, max(1, w // 2))
    hh = min(hh, max(1, h // 2))
    x = int(np.random.randint(0, max(1, w - ww)))
    y = int(np.random.randint(0, max(1, h - hh)))
    _fill_rect(out, x, y, ww, hh, fill_mode, fill_color)


def _apply_gridmask(out, h, w, grid_size, mask_ratio, fill_color):
    mask = np.ones((h, w), dtype=np.uint8)
    gs = max(1, grid_size)
    stripe = max(1, int(gs * mask_ratio))
    for yy in range(0, h, gs):
        for xx in range(0, w, gs):
            if np.random.rand() < 0.5:
                mask[yy : min(h, yy + stripe), xx : min(w, xx + gs)] = 0
            else:
                mask[yy : min(h, yy + gs), xx : min(w, xx + stripe)] = 0
    mask_3 = np.repeat(mask[:, :, None], 3, axis=2)
    if fill_color is None:
        fill_color = (0, 0, 0)
    return (out * mask_3 + (1 - mask_3) * np.array(fill_color, dtype=np.uint8)).astype(np.uint8)


def _fill_rect(out, x, y, ww, hh, fill_mode, fill_color):
    if fill_mode == "random":
        fill_color = tuple(int(v) for v in np.random.randint(0, 256, size=(3,)))
    if fill_color is None:
        fill_color = (0, 0, 0)
    cv2.rectangle(out, (x, y), (x + ww, y + hh), fill_color, thickness=-1)
