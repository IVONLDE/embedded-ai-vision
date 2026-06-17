from __future__ import annotations

from pathlib import Path

from ...integrations import get_agl_algorithm_spec, run_agl_algorithm


def run(payload: dict, context) -> dict:
    algorithm_key = (payload.get("algorithm_key") or "").strip()
    if not algorithm_key:
        return {"ok": False, "error_code": "VALIDATION_ERROR", "message": "algorithm_key is required."}

    try:
        spec = get_agl_algorithm_spec(algorithm_key)
    except ValueError as exc:
        return {"ok": False, "error_code": "UNSUPPORTED_ALGORITHM", "message": str(exc)}

    samples = list(payload.get("input", {}).get("samples", []))
    if not samples:
        return {"ok": False, "error_code": "VALIDATION_ERROR", "message": "At least one input sample is required."}

    target_count = int(payload.get("target_count") or payload.get("parameters", {}).get("target_count") or len(samples))
    if target_count <= 0:
        return {"ok": False, "error_code": "VALIDATION_ERROR", "message": "target_count must be greater than zero."}

    output_dir_value = payload.get("output", {}).get("output_dir") or getattr(context, "output_dir", "")
    if not output_dir_value:
        return {"ok": False, "error_code": "VALIDATION_ERROR", "message": "output_dir is required."}

    output_dir = Path(output_dir_value).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    outputs: list[dict] = []
    context.log("info", "agl-generation-start", {"algorithm_key": algorithm_key, "target_count": target_count})

    for index in range(target_count):
        if context.is_cancel_requested():
            context.log("warning", "agl-generation-cancelled", {"generated_count": len(outputs)})
            return {"ok": False, "error_code": "CANCELLED", "message": "Generation cancelled by request."}

        sample = samples[index % len(samples)]
        generated_path = run_agl_algorithm(
            algorithm_key=algorithm_key,
            sample_path=sample["path"],
            parameters=payload.get("parameters", {}),
            output_dir=str(output_dir),
            index=index + 1,
        )
        if not generated_path:
            return {
                "ok": False,
                "error_code": "ALGORITHM_RUNTIME_ERROR",
                "message": f"AGL algorithm failed for key {spec.key}.",
            }

        generated_file = Path(generated_path)
        outputs.append(
            {
                "source_sample_id": sample["id"],
                "output_path": str(generated_file),
                "relative_path": generated_file.name,
                "metadata": {
                    "algorithm_key": spec.key,
                    "algorithm_name": spec.name,
                    "modality": spec.modality,
                },
            }
        )
        context.set_progress(((index + 1) / target_count) * 100.0, f"Generated {index + 1}/{target_count}")

    context.log("info", "agl-generation-complete", {"generated_count": len(outputs), "algorithm_key": algorithm_key})
    return {"ok": True, "outputs": outputs}
