"""Bind reviewed annotations to an exact source digest and completed analysis identity."""

from pathlib import Path

import yaml

from ros_telemetry_analytics.investigations import load_bundle, specs, write_json

ROOT = Path(__file__).resolve().parents[1]


def publish(root: Path, output: Path, dataset_id: str, metadata: dict) -> None:
    config = yaml.safe_load((root / "configs/recording_cases.yaml").read_text())
    entry = config["datasets"].get(dataset_id)
    if not entry:
        return
    if entry["source_sha256"] != metadata["source_sha256"]:
        raise ValueError("Reviewed cases do not match this source copy")
    for case in entry["cases"]:
        if not 0 <= case["start_s"] <= case["focus_s"] <= case["end_s"] <= metadata["duration_s"]:
            raise ValueError("Reviewed case is outside the recording")
    write_json(
        output / dataset_id / metadata["analysis_id"] / "annotations.json",
        {
            "analysis_id": metadata["analysis_id"],
            "source_sha256": metadata["source_sha256"],
            "kind": "reviewed interpretation, separate from generated alerts",
            "cases": entry["cases"],
        },
    )


if __name__ == "__main__":
    for name in specs(ROOT):
        _, metadata = load_bundle(ROOT, ROOT / "data/investigations", name)
        publish(ROOT, ROOT / "data/investigations", name, metadata)
