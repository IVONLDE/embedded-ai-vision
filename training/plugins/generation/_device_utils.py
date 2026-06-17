from __future__ import annotations


def resolve_torch_device(torch, payload: dict | None = None, parameters: dict | None = None):
    if getattr(torch, "cuda", None) and torch.cuda.is_available():
        torch.cuda.set_device(0)
        return torch.device("cuda:0")

    if _is_npu_available():
        import torch_npu  # noqa: F401

        torch_npu.npu.set_device(0)
        return torch.device("npu:0")

    return torch.device("cpu")


def _is_npu_available() -> bool:
    try:
        import torch_npu  # noqa: F401
    except ImportError:
        return False

    try:
        import torch

        return bool(getattr(torch, "npu", None) and torch.npu.is_available())
    except Exception:
        return False
