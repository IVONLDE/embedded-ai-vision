"""Minimal demo training plugin.

Simulates a training loop across epochs, updates progress in the DB, and
produces a mock model checkpoint file so the full train→evaluate pipeline
can be exercised end-to-end.
"""

from __future__ import annotations

import json
import time
from pathlib import Path


PARAMETERS = [
    {
        "name": 'epochs',
        "type": 'int',
        "label": '训练轮次',
        "default": 3,
        "min": 1,
        "max": 1000,
        "options": [],
        "description": '模拟训练的epoch数量',
        "required": False,
    },
]


def run(payload: dict, context: dict | None = None) -> dict:
    """Simulate training and write a fake checkpoint."""
    task_id = payload.get("task_id", 0)
    input_data = payload.get("input", {})
    output_dir = Path(payload.get("output", {}).get("output_dir", ""))
    parameters = payload.get("parameters", {})
    samples = input_data.get("samples", [])
    epochs = int(parameters.get("epochs", 3))

    output_dir.mkdir(parents=True, exist_ok=True)

    sample_count = len(samples)
    total_steps = epochs * max(sample_count, 1)

    progress = context.set_progress if context else None
    is_cancelled = context.is_cancel_requested if context else None

    step = 0
    for epoch in range(epochs):
        if is_cancelled and is_cancelled():
            return {"ok": False, "error_code": "CANCELLED", "message": "Training cancelled"}

        # simulate per-sample processing time
        for _ in samples:
            time.sleep(0.02)
            step += 1
            if progress and step % max(total_steps // 10, 1) == 0:
                progress(step / total_steps * 100.0, f"Epoch {epoch + 1}/{epochs} step {step}/{total_steps}")

    # Write a mock checkpoint
    checkpoint_path = output_dir / "model_checkpoint.pt"
    checkpoint_data = {
        "task_id": task_id,
        "model": "demo_classifier",
        "epochs": epochs,
        "sample_count": sample_count,
        "hyperparameters": parameters,
        "accuracy": round(0.7 + (epochs * 0.05), 4),
        "loss": round(0.5 - (epochs * 0.03), 4),
    }
    checkpoint_path.write_text(json.dumps(checkpoint_data, ensure_ascii=False, indent=2), encoding="utf-8")

    return {
        "ok": True,
        "outputs": [
            {
                "artifact_path": str(checkpoint_path),
                "artifact_type": "model_checkpoint",
                "metrics": {
                    "accuracy": checkpoint_data["accuracy"],
                    "loss": checkpoint_data["loss"],
                    "epochs": epochs,
                    "sample_count": sample_count,
                },
                "summary": f"Demo classifier trained for {epochs} epochs on {sample_count} samples. "
                f"Final accuracy: {checkpoint_data['accuracy']}, loss: {checkpoint_data['loss']}",
            }
        ],
    }
