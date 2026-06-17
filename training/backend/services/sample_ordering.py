from __future__ import annotations

from collections import OrderedDict
from itertools import zip_longest
from pathlib import PurePosixPath
from typing import Iterable, TypeVar

T = TypeVar("T")


def interleave_by_top_folder(samples: Iterable[T]) -> list[T]:
    groups: "OrderedDict[str, list[T]]" = OrderedDict()
    for sample in samples:
        relative_path = str(getattr(sample, "relative_path", "") or getattr(sample, "name", "") or "")
        parts = PurePosixPath(relative_path.replace("\\", "/")).parts
        key = parts[0] if len(parts) > 1 else ""
        groups.setdefault(key, []).append(sample)

    if len(groups) <= 1:
        return [sample for group in groups.values() for sample in group]

    ordered: list[T] = []
    for row in zip_longest(*groups.values()):
        ordered.extend(sample for sample in row if sample is not None)
    return ordered
