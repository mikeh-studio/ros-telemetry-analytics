"""Fetch the selected bag pack atomically; never replace an existing recording."""

from __future__ import annotations

import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path

import requests
import yaml

ROOT = Path(__file__).resolve().parents[1]


def fetch(url: str, destination: Path, expected_bytes: int | None = None) -> dict:
    if destination.exists():
        return {"path": str(destination.relative_to(ROOT)), "status": "already_present"}
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".partial")
    digest = hashlib.sha256()
    count = 0
    owned = False
    try:
        with requests.get(url, stream=True, timeout=(20, 120)) as response:
            response.raise_for_status()
            if "text/html" in response.headers.get("Content-Type", ""):
                raise ValueError("Download returned an HTML page")
            with temporary.open("xb") as output:
                owned = True
                for chunk in response.iter_content(1024 * 1024):
                    output.write(chunk)
                    digest.update(chunk)
                    count += len(chunk)
                output.flush()
                os.fsync(output.fileno())
        if not count or (expected_bytes is not None and count != expected_bytes):
            raise ValueError(f"Unexpected download size: {count}, expected {expected_bytes}")
        if destination.suffix == ".bag":
            with temporary.open("rb") as source:
                if source.read(13) != b"#ROSBAG V2.0\n":
                    raise ValueError("Download is not a ROS 1 v2 bag")
        # Atomic create: another acquisition cannot be silently overwritten.
        os.link(temporary, destination)
        result = {
            "path": str(destination.relative_to(ROOT)),
            "url": url,
            "bytes": count,
            "sha256": digest.hexdigest(),
            "acquired_at": datetime.now(UTC).isoformat(),
            "integrity": "local digest; no independently published checksum",
        }
        destination.with_suffix(destination.suffix + ".receipt.json").write_text(
            json.dumps(result, indent=2) + "\n"
        )
        return result
    finally:
        # Do not remove a partial owned by an earlier interrupted invocation.
        if owned and temporary.exists():
            temporary.unlink()


def main() -> None:
    datasets = yaml.safe_load((ROOT / "configs/investigations.yaml").read_text())["datasets"]
    failures = []
    for dataset_id, spec in datasets.items():
        downloads = []
        if spec.get("download_url"):
            downloads.append((spec["download_url"], ROOT / spec["input"], spec.get("bytes")))
        if spec.get("reference_url"):
            downloads.append(
                (spec["reference_url"], ROOT / spec["input"].replace(".bag", ".gt.txt"), None)
            )
        for url, path, size in downloads:
            print(f"Fetching {dataset_id}: {path.name}", flush=True)
            try:
                print(json.dumps(fetch(url, path, size)), flush=True)
            except (OSError, ValueError, requests.RequestException) as exc:
                failures.append({"dataset": dataset_id, "url": url, "error": str(exc)})
                print(json.dumps(failures[-1]), flush=True)
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
