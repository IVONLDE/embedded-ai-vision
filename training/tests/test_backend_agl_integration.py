from pathlib import Path

import cv2
import numpy as np


class DummyContext:
    def __init__(self):
        self.logs = []
        self.progress = []
        self.cancelled = False

    def log(self, level, message, payload=None):
        self.logs.append((level, message, payload or {}))

    def set_progress(self, progress, message=""):
        self.progress.append((progress, message))

    def is_cancel_requested(self):
        return self.cancelled


def test_agl_algorithm_manager_imports_without_torch():
    from agl.algorithm_manager import AlgorithmManager

    manager = AlgorithmManager()
    assert isinstance(manager._torch_available(), bool)


def test_agl_torch_gated_algorithm_fails_closed_without_torch(monkeypatch):
    from backend.integrations.agl_generation import run_agl_algorithm
    import agl.algorithm_manager as agl_module

    monkeypatch.setattr(agl_module, "torch", None)
    monkeypatch.setattr(agl_module, "nn", None)
    monkeypatch.setattr(agl_module, "optim", None)

    result = run_agl_algorithm(
        algorithm_key="agl.image.gan",
        sample_path="missing.jpg",
        parameters={},
        output_dir=".",
        index=1,
    )
    assert result is None


def test_agl_generation_plugin_runs_geometric_transformation(tmp_path):
    from backend.plugins.builtin.agl_generation import run

    source = tmp_path / "source.jpg"
    output_dir = tmp_path / "outputs"
    image = np.full((12, 12, 3), 127, dtype=np.uint8)
    assert cv2.imwrite(str(source), image) is True

    payload = {
        "algorithm_key": "agl.image.geometric",
        "parameters": {"旋转角度": 15, "缩放比例": 1.0, "水平翻转": False, "垂直翻转": False},
        "input": {"samples": [{"id": 1, "path": str(source)}]},
        "output": {"output_dir": str(output_dir)},
        "target_count": 1,
    }
    context = DummyContext()
    result = run(payload, context)

    assert result["ok"] is True
    assert len(result["outputs"]) == 1
    output_path = Path(result["outputs"][0]["output_path"])
    assert output_path.is_file()
    assert result["outputs"][0]["metadata"]["algorithm_key"] == "agl.image.geometric"
    assert any(message == "agl-generation-complete" for _, message, _ in context.logs)
