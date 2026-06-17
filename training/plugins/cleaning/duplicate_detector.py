from pathlib import Path


PARAMETERS = []

def run(payload: dict, context) -> dict:
    """Detect duplicate samples by comparing SHA256 hashes."""
    samples = payload.get("input", {}).get("samples", [])
    if not samples:
        return {"ok": True, "suggestions": [], "logs": []}

    seen = {}
    suggestions = []
    total = len(samples)
    for idx, sample in enumerate(samples):
        if context.is_cancel_requested():
            return {"ok": False, "error_code": "CANCELLED", "message": "任务已取消", "details": {}}
        context.set_progress((idx + 1) * 100 / total, f"检测重复 {idx + 1}/{total}")
        sha = sample.get("sha256") or sample.get("metadata", {}).get("sha256", "")
        if sha and sha in seen:
            suggestions.append({
                "sample_id": sample["id"],
                "issue_type": "duplicate",
                "suggested_action": "delete",
                "confidence": 1.0,
                "message": f"Duplicate of sample {seen[sha]}",
                "details": {"duplicate_of": seen[sha], "sha256": sha},
                "output_path": "",
            })
        else:
            seen[sha] = sample["id"]

    return {"ok": True, "suggestions": suggestions, "logs": []}
