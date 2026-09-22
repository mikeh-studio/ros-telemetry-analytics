"""Inventory local assets without changing them; record bounded reader checks and limitations."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import uuid
import zipfile
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pyarrow.parquet as pq

from ros_telemetry_analytics.discovery import discover_bags
from ros_telemetry_analytics.investigations import rows, sha256, specs, write_json
from ros_telemetry_analytics.reader import open_bag

ROOT = Path(__file__).resolve().parents[1]


def inspect_bag(path: Path) -> dict:
    (source,) = discover_bags([path], excluded_directory_names=frozenset())
    with open_bag(source) as reader:
        connections = [
            {"topic": c.topic, "type": c.msgtype, "count": c.msgcount} for c in reader.connections
        ]
        return {
            "status": "reader_metadata_ok",
            "message_count": reader.message_count,
            "topics": connections,
            "duration_s": reader.duration / 1e9,
            "scope": "Reader index/metadata only; payload not certified",
        }


def main() -> None:
    if len(sys.argv) == 3 and sys.argv[1] == "--inspect":
        try:
            print(json.dumps(inspect_bag(Path(sys.argv[2]))))
        except Exception as exc:
            print(
                json.dumps({"status": "reader_rejected", "error": f"{type(exc).__name__}: {exc}"})
            )
        return
    audit_id = uuid.uuid4().hex
    destination = ROOT / "data/evaluations/dataset-audit" / audit_id
    manifest = specs(ROOT)
    registered = {str((ROOT / value["input"]).resolve()): key for key, value in manifest.items()}
    roots = [ROOT / "data/raw", ROOT / "data/demo", ROOT / "data/uploads"]
    custom = os.environ.get("DATASET_UPLOAD_DIR")
    if custom and Path(custom).resolve() not in roots:
        roots.append(Path(custom).resolve())
    physical = []
    for root in roots:
        if not root.exists():
            continue
        for path in sorted(root.rglob("*")):
            if not path.is_file() or path.name in {".gitkeep", ".DS_Store"}:
                continue
            relative = str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path)
            item = {"path": relative, "bytes": path.stat().st_size, "sha256": sha256(path)}
            if path.suffix == ".parquet":
                metadata = pq.read_metadata(path)
                item.update(
                    {
                        "rows": metadata.num_rows,
                        "row_groups": metadata.num_row_groups,
                        "columns": metadata.schema.names,
                    }
                )
            physical.append(item)
    errors = []
    sources = discover_bags(
        [p for p in roots if p.exists()],
        excluded_directory_names=frozenset(),
        on_error=lambda p, e: errors.append({"path": str(p), "error": str(e)}),
    )
    logical = []
    for source in sources:
        path = source.path
        name = str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path)
        dataset_id = registered.get(str(path))
        role = (
            "real_recording"
            if dataset_id
            else "parser_regression"
            if "ros_fixtures" in name
            else "compatibility_sample"
            if "quickstart" in name
            else "controlled_demo"
            if "data/demo" in name
            else "unclassified_preserve"
        )
        files = [
            f["path"] for f in physical if (f["path"] == name or f["path"].startswith(name + "/"))
        ]
        row = {
            "path": name,
            "dataset_id": dataset_id,
            "role": role,
            "bytes": source.size_bytes,
            "fingerprint": source.fingerprint,
            "physical_files": files,
            "format": source.format,
        }
        if dataset_id:
            pointer = ROOT / "data/investigations" / dataset_id / "latest.json"
            if pointer.exists():
                version = json.loads(pointer.read_text())["analysis_id"]
                metadata = json.loads((pointer.parent / version / "metadata.json").read_text())
                row["analysis"] = {
                    k: metadata[k]
                    for k in (
                        "analysis_id",
                        "status",
                        "message_count",
                        "duration_s",
                        "coverage",
                        "preview_count",
                        "verified_previews",
                        "extraction_errors",
                        "source_sha256",
                        "elapsed_s",
                        "header_profile",
                    )
                }
                row["analysis"]["continuity_checks"] = rows(
                    pointer.parent / version / metadata["analysis_path"] / "vslam_quality.parquet"
                )
                row["source"] = manifest[dataset_id]["source"]
                row["purpose"] = manifest[dataset_id]["purpose"]
        else:
            try:
                check = subprocess.run(
                    [sys.executable, __file__, "--inspect", str(path)],
                    capture_output=True,
                    text=True,
                    timeout=20,
                    check=True,
                )
                row["reader_check"] = json.loads(check.stdout)
            except (subprocess.SubprocessError, ValueError) as exc:
                row["reader_check"] = {"status": "check_incomplete", "error": str(exc)}
        logical.append(row)
    archive = ROOT / "data/raw/tuhh/preprocessed_data.zip"
    tuhh = {
        "role": "localization_evaluation",
        "origin": "simulation",
        "purpose": "Existing held-out localization study; labels/reference remain evaluation-only",
        "validation_scope": "Physical inventory, archive membership, readable Parquet metadata; "
        "existing study retained without retuning or re-scoring",
    }
    if archive.exists():
        with zipfile.ZipFile(archive) as source:
            tuhh["archive_members"] = [i.filename for i in source.infolist() if not i.is_dir()]
    segments = []
    for path in sorted((ROOT / "data/raw/tuhh").glob("*.processed.parquet")):
        table = pq.ParquetFile(path).read(
            columns=[
                "measurements.list.element.time",
                "measurements.list.element.value.is_delocalized",
            ]
        )
        for segment_id, scalar in enumerate(table["measurements"]):
            values = scalar.values
            times = values.field("time").to_numpy()
            labels = values.field("value").field("is_delocalized").to_pylist()
            groups = {}
            for stamp, label in zip(times, labels, strict=True):
                groups.setdefault(int(stamp), set()).add(label)
            segments.append(
                {
                    "file": path.name,
                    "segment": segment_id,
                    "samples": len(times),
                    "failure_labels": sum(v is True for v in labels),
                    "missing_labels": sum(v is None for v in labels),
                    "duplicate_timestamp_rows": len(times) - len(groups),
                    "conflicting_label_timestamps": sum(len(v) > 1 for v in groups.values()),
                    "backward_timestamps": int((np.diff(times) < 0).sum()),
                }
            )
    tuhh["segment_checks"] = segments
    tuhh["validation_scope"] = (
        "Archive membership, Parquet metadata, nested timestamp/label "
        "profiling within original segments; no detector tuning or rescoring"
    )
    by_hash = {}
    for file in physical:
        if file["bytes"]:
            by_hash.setdefault(file["sha256"], []).append(file)
    duplicates = [items for items in by_hash.values() if len(items) > 1]
    try:
        docker = subprocess.run(
            ["docker", "compose", "ps", "--format", "json"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        volume_scope = {
            "status": "requires_volume_inventory" if docker.returncode == 0 else "unavailable",
            "detail": docker.stdout or docker.stderr,
        }
    except (OSError, subprocess.TimeoutExpired) as exc:
        volume_scope = {"status": "unavailable", "detail": str(exc)}
    result = {
        "audit_id": audit_id,
        "created_at": datetime.now(UTC).isoformat(),
        "scope": "Host raw sources, host demo/uploads and explicit DATASET_UPLOAD_DIR",
        "physical_files": physical,
        "logical_bags": logical,
        "discovery_errors": errors,
        "tuhh": tuhh,
        "exact_duplicate_groups": duplicates,
        "docker_volumes": volume_scope,
        "preserved_outputs": "data/evaluations and data/bronze retained as derived lineage",
        "deferred": ["OpenLORIS", "ARCO", "nvblox"],
        "checksum_note": "Digests identify local copies; not upstream authenticity certification",
    }
    write_json(destination / "inventory.json", result)
    write_json(ROOT / "data/evaluations/dataset-audit/latest.json", {"audit_id": audit_id})
    print(destination / "inventory.json")


if __name__ == "__main__":
    main()
