"""Review/apply the exact redundant NVIDIA extraction cleanup; never touches other data."""

from __future__ import annotations

import argparse
import uuid
from pathlib import Path

from ros_telemetry_analytics.investigations import sha256, write_json

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / "data/raw/downloads/visual_slam/isaac_ros_visual_slam/quickstart_bag"
CANONICAL = ROOT / "data/raw/isaac_ros_assets/visual_slam/isaac_ros_visual_slam/quickstart_bag"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    names = ["quickstart_bag_0.db3", "metadata.yaml"]
    records = []
    for name in names:
        original, retained = CACHE / name, CANONICAL / name
        if not original.exists():
            continue
        if not retained.is_file() or original.is_symlink() or retained.is_symlink():
            raise ValueError("Canonical surviving file is missing or a path is a symlink")
        digest = sha256(original)
        if digest != sha256(retained):
            raise ValueError(f"Files differ: {name}")
        records.append(
            {
                "remove": str(original.relative_to(ROOT)),
                "retain": str(retained.relative_to(ROOT)),
                "bytes": original.stat().st_size,
                "sha256": digest,
            }
        )
    receipt = ROOT / "data/evaluations/dataset-audit" / f"cleanup-{uuid.uuid4().hex}.json"
    payload = {
        "status": "proposed",
        "files": records,
        "archive_retained": "data/raw/downloads/visual_slam/quickstart.tar.gz",
        "dependency_check": "assets.py EXTRACT_DIR uses canonical isaac_ros_assets tree; "
        "no code/config references the cache extraction",
    }
    write_json(receipt, payload)
    if args.apply:
        for row in records:
            (ROOT / row["remove"]).unlink()
            if sha256(ROOT / row["retain"]) != row["sha256"]:
                raise ValueError("Surviving copy failed verification")
        if CACHE.exists() and not any(CACHE.iterdir()):
            CACHE.rmdir()
        payload["status"] = "removed_verified_duplicates"
        write_json(receipt, payload)
    print(receipt)


if __name__ == "__main__":
    main()
