from __future__ import annotations

from pathlib import Path


PARAMETERS = [
    {
        "name": 'hamming_threshold',
        "type": 'int',
        "label": '感知哈希距离阈值',
        "default": 6,
        "min": 1,
        "max": 64,
        "options": [],
        "description": '两个图像 dHash 的汉明距离不大于该值时视为近似重复',
        "required": False,
    },
    {
        "name": 'min_confidence',
        "type": 'float',
        "label": '最低置信度',
        "default": 0.75,
        "min": 0.0,
        "max": 1.0,
        "options": [],
        "description": '输出建议的最低置信度下限',
        "required": False,
    },
    {
        "name": 'hash_size',
        "type": 'int',
        "label": '哈希尺寸',
        "default": 8,
        "min": 4,
        "max": 16,
        "options": [],
        "description": 'dHash 基础尺寸，默认生成 64 位指纹',
        "required": False,
    },
]


def run(payload: dict, context) -> dict:
    """Detect perceptually near-duplicate image samples with a handwritten dHash."""
    parameters = payload.get("parameters", {}) or {}
    samples = payload.get("input", {}).get("samples", []) or []
    hamming_threshold = int(parameters.get("hamming_threshold", 6))
    min_confidence = float(parameters.get("min_confidence", 0.75))
    hash_size = max(4, min(16, int(parameters.get("hash_size", 8))))

    image_items = []
    total = max(len(samples), 1)
    for index, sample in enumerate(samples):
        if context.is_cancel_requested():
            return {"ok": False, "error_code": "CANCELLED", "message": "任务已取消", "details": {}}
        context.set_progress((index + 1) * 50 / total, f"读取图像 {index + 1}/{len(samples)}")

        sample_type = str(sample.get("sample_type") or sample.get("modality") or payload.get("modality") or "").lower()
        sample_path = sample.get("sample_path") or sample.get("path") or sample.get("file_path")
        if not _is_image_sample(sample_path, sample_type):
            continue

        pixels = _load_grayscale_pixels(Path(sample_path))
        if not pixels:
            context.log("warning", "image-near-duplicate-skip", {"sample_id": sample.get("id"), "path": sample_path})
            continue
        image_items.append({
            "sample": sample,
            "sample_path": sample_path,
            "sample_type": sample_type or "image",
            "hash": _difference_hash(pixels, hash_size),
        })

    suggestions = []
    fingerprints = []
    total_images = max(len(image_items), 1)
    for index, item in enumerate(image_items):
        if context.is_cancel_requested():
            return {"ok": False, "error_code": "CANCELLED", "message": "任务已取消", "details": {}}
        context.set_progress(50 + (index + 1) * 50 / total_images, f"比对近似重复 {index + 1}/{len(image_items)}")

        best = None
        for candidate in fingerprints:
            distance = _hamming_distance(item["hash"], candidate["hash"])
            if best is None or distance < best["distance"]:
                best = {"distance": distance, "candidate": candidate}

        if best and best["distance"] <= hamming_threshold:
            max_distance = max(len(item["hash"]), 1)
            similarity = 1.0 - (best["distance"] / max_distance)
            confidence = max(min_confidence, min(1.0, round(similarity, 4)))
            duplicate_of = best["candidate"]["sample"]
            suggestions.append({
                "sample_id": item["sample"]["id"],
                "issue_type": "near_duplicate_image",
                "suggested_action": "delete",
                "confidence": confidence,
                "message": f"Image is visually similar to sample {duplicate_of['id']} (dHash distance {best['distance']}).",
                "details": {
                    "processing_result": "near_duplicate_detected",
                    "duplicate_of_sample_id": duplicate_of["id"],
                    "duplicate_of_path": best["candidate"]["sample_path"],
                    "sample_path": item["sample_path"],
                    "sample_type": item["sample_type"],
                    "hamming_distance": best["distance"],
                    "hamming_threshold": hamming_threshold,
                    "similarity": round(similarity, 4),
                    "hash_size": hash_size,
                },
            })
        else:
            fingerprints.append(item)

    return {"ok": True, "suggestions": suggestions, "logs": []}


def _is_image_sample(sample_path: str | None, sample_type: str) -> bool:
    if sample_type in {"image", "图像", "picture", "photo"}:
        return True
    if not sample_path:
        return False
    return Path(sample_path).suffix.lower() in {".pgm", ".ppm", ".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff"}


def _load_grayscale_pixels(path: Path) -> list[list[int]]:
    if not path.is_file():
        return []

    loaded = _load_with_pillow(path)
    if loaded:
        return loaded
    loaded = _load_with_cv2(path)
    if loaded:
        return loaded
    return _load_netpbm(path)


def _load_with_pillow(path: Path) -> list[list[int]]:
    try:
        from PIL import Image
    except Exception:
        return []
    try:
        image = Image.open(path).convert("L")
        width, height = image.size
        values = list(image.getdata())
        return [values[row * width:(row + 1) * width] for row in range(height)]
    except Exception:
        return []


def _load_with_cv2(path: Path) -> list[list[int]]:
    try:
        import cv2
    except Exception:
        return []
    image = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
    if image is None:
        return []
    return [[int(value) for value in row] for row in image.tolist()]


def _load_netpbm(path: Path) -> list[list[int]]:
    data = path.read_bytes()
    tokens, offset = _read_netpbm_header(data)
    if len(tokens) < 4 or tokens[0] not in {b"P2", b"P3", b"P5", b"P6"}:
        return []
    magic = tokens[0]
    width = int(tokens[1])
    height = int(tokens[2])
    max_value = max(int(tokens[3]), 1)
    if width <= 0 or height <= 0:
        return []

    if magic in {b"P2", b"P3"}:
        values = [int(token) for token in data[offset:].split()]
        if magic == b"P3":
            values = [_rgb_to_gray(values[i], values[i + 1], values[i + 2]) for i in range(0, len(values) - 2, 3)]
    elif magic == b"P5":
        values = list(data[offset:offset + width * height])
    else:
        rgb = data[offset:offset + width * height * 3]
        values = [_rgb_to_gray(rgb[i], rgb[i + 1], rgb[i + 2]) for i in range(0, len(rgb) - 2, 3)]

    if len(values) < width * height:
        return []
    if max_value != 255:
        values = [round(value * 255 / max_value) for value in values]
    return [values[row * width:(row + 1) * width] for row in range(height)]


def _read_netpbm_header(data: bytes) -> tuple[list[bytes], int]:
    tokens = []
    index = 0
    while len(tokens) < 4 and index < len(data):
        while index < len(data) and data[index] in b" \t\r\n":
            index += 1
        if index < len(data) and data[index] == ord("#"):
            while index < len(data) and data[index] not in b"\r\n":
                index += 1
            continue
        start = index
        while index < len(data) and data[index] not in b" \t\r\n":
            index += 1
        if start != index:
            tokens.append(data[start:index])
    while index < len(data) and data[index] in b" \t\r\n":
        index += 1
    return tokens, index


def _rgb_to_gray(red: int, green: int, blue: int) -> int:
    return round(0.299 * red + 0.587 * green + 0.114 * blue)


def _difference_hash(pixels: list[list[int]], hash_size: int) -> tuple[int, ...]:
    width = hash_size + 1
    height = hash_size
    resized = _resize_nearest(pixels, width, height)
    bits = []
    for row in resized:
        for column in range(hash_size):
            bits.append(1 if row[column] > row[column + 1] else 0)
    return tuple(bits)


def _resize_nearest(pixels: list[list[int]], width: int, height: int) -> list[list[int]]:
    source_height = len(pixels)
    source_width = len(pixels[0]) if source_height else 0
    if source_width == 0 or source_height == 0:
        return []
    resized = []
    for y in range(height):
        source_y = min(source_height - 1, round(y * (source_height - 1) / max(height - 1, 1)))
        row = []
        for x in range(width):
            source_x = min(source_width - 1, round(x * (source_width - 1) / max(width - 1, 1)))
            row.append(int(pixels[source_y][source_x]))
        resized.append(row)
    return resized


def _hamming_distance(left: tuple[int, ...], right: tuple[int, ...]) -> int:
    return sum(1 for a, b in zip(left, right) if a != b) + abs(len(left) - len(right))
