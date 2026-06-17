from __future__ import annotations

from pathlib import Path
from typing import Union

import cv2
import numpy as np


def read_image(path: Union[Path, str], flags: int = cv2.IMREAD_COLOR):
    data = np.frombuffer(Path(path).read_bytes(), dtype=np.uint8)
    return cv2.imdecode(data, flags)


def write_image(path: Union[Path, str], image) -> bool:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    ext = output_path.suffix or ".jpg"
    ok, encoded = cv2.imencode(ext, image)
    if not ok:
        return False
    output_path.write_bytes(encoded.tobytes())
    return True
