from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from ros_telemetry_analytics.config import REPOSITORY_ROOT, load_pipeline_config
from ros_telemetry_analytics.pipeline import run_pipeline

DEFAULT_PUBLIC_DATASET_MANIFEST = REPOSITORY_ROOT / "configs" / "public_test_datasets.yaml"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while block := source.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def _resolve(value: str | Path) -> Path:
    path = Path(value).expanduser()
    return path.resolve() if path.is_absolute() else (REPOSITORY_ROOT / path).resolve()


def _verify_local_artifact(dataset: dict[str, Any]) -> tuple[str, str]:
    artifact_value = dataset.get("local_artifact")
    if not artifact_value:
        return "not_configured", "No single-file integrity artifact is configured."
    artifact = _resolve(artifact_value)
    if not artifact.is_file():
        return "not_installed", f"Expected local artifact is missing: {artifact}"
    expected_bytes = dataset.get("bytes")
    if expected_bytes is not None and artifact.stat().st_size != int(expected_bytes):
        return "invalid", (
            f"Size mismatch for {artifact}: expected {expected_bytes}, "
            f"found {artifact.stat().st_size}."
        )
    expected_sha256 = dataset.get("sha256")
    if expected_sha256 and _sha256(artifact) != str(expected_sha256):
        return "invalid", f"SHA-256 mismatch for {artifact}."
    return "verified", f"Verified local artifact: {artifact}"


def run_public_robotics_suite(
    manifest_path: Path = DEFAULT_PUBLIC_DATASET_MANIFEST,
    *,
    force: bool = False,
    output_path: Path | None = None,
) -> dict[str, Any]:
    """Run every installed public robotics profile and report absent corpora explicitly."""
    manifest_path = manifest_path.expanduser().resolve()
    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}
    datasets = manifest.get("datasets", {})
    results: list[dict[str, Any]] = []
    for name, dataset in datasets.items():
        if not dataset.get("public_robotics_suite", False):
            continue
        input_path = _resolve(dataset["local_input"])
        profile_path = _resolve(dataset["pipeline_config"])
        integrity_status, integrity_detail = _verify_local_artifact(dataset)
        result: dict[str, Any] = {
            "dataset": name,
            "workflow": dataset["workflow"],
            "input_path": str(input_path),
            "profile": str(profile_path),
            "integrity_status": integrity_status,
            "integrity_detail": integrity_detail,
        }
        if integrity_status == "invalid":
            result["status"] = "invalid"
        elif not input_path.exists():
            result["status"] = "not_installed"
        else:
            config = load_pipeline_config(profile_path)
            pipeline_result = run_pipeline(config, force=force)
            result["pipeline"] = pipeline_result
            result["status"] = (
                "passed"
                if pipeline_result["discovered_count"] > 0 and pipeline_result["failed_count"] == 0
                else "failed"
            )
        results.append(result)

    summary = {
        "schema_version": 1,
        "generated_at": datetime.now(UTC).isoformat(),
        "manifest_path": str(manifest_path),
        "dataset_count": len(results),
        "passed_count": sum(row["status"] == "passed" for row in results),
        "not_installed_count": sum(row["status"] == "not_installed" for row in results),
        "failed_count": sum(row["status"] in {"failed", "invalid"} for row in results),
        "results": results,
    }
    output_path = output_path or (
        REPOSITORY_ROOT / "data" / "bronze" / "public_robotics_suite.json"
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return summary
