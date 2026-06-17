import json
from pathlib import Path


PARAMETERS = []

def run(payload: dict, context) -> dict:
    """Compare baseline and target dataset sample counts as a simple evaluation metric."""
    baseline_samples = payload.get("input", {}).get("baseline_dataset", {}).get("samples", [])
    target_samples = payload.get("input", {}).get("target_dataset", {}).get("samples", [])

    baseline_count = len(baseline_samples)
    target_count = len(target_samples)
    ratio = target_count / max(baseline_count, 1)

    output_dir = Path(payload["output"]["output_dir"])
    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / "report.json"
    report_path.write_text(json.dumps({
        "baseline_count": baseline_count,
        "target_count": target_count,
        "ratio": round(ratio, 2),
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    return {
        "ok": True,
        "metrics": {
            "baseline_samples": baseline_count,
            "target_samples": target_count,
            "sample_ratio": round(ratio, 2),
        },
        "artifacts": [{"type": "report", "path": str(report_path)}],
        "summary": f"Target has {target_count} samples vs baseline {baseline_count} (ratio: {ratio:.2f})",
    }
