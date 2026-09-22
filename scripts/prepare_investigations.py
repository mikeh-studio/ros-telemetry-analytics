"""Prepare immutable offline evidence. Does not download, delete, or change originals."""

from __future__ import annotations

import argparse
import json
import resource
import sys
import time
from pathlib import Path

from curate_investigations import publish

from ros_telemetry_analytics.investigations import build_bundle, specs, write_json

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("datasets", nargs="*", help="Registered IDs; defaults to all installed")
    parser.add_argument("--output", type=Path, default=ROOT / "data/investigations")
    args = parser.parse_args()
    selected = args.datasets or list(specs(ROOT))
    results = []
    for dataset_id in selected:
        started = time.monotonic()
        print(f"Preparing {dataset_id}", flush=True)
        try:
            metadata = build_bundle(ROOT, dataset_id, args.output)
            if metadata["status"] in {"ready", "limited"}:
                publish(ROOT, args.output, dataset_id, metadata)
            result = {
                k: v
                for k, v in metadata.items()
                if k
                not in {
                    "coverage",
                    "header_profile",
                    "temporal_profile",
                    "topic_health",
                    "relationships",
                }
            }
        except (OSError, ValueError, KeyError) as exc:
            result = {"dataset_id": dataset_id, "status": "failed", "error": str(exc)}
        result["wall_s"] = time.monotonic() - started
        result["process_peak_rss_bytes"] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * (
            1 if sys.platform == "darwin" else 1024
        )
        results.append(result)
        print(json.dumps(result), flush=True)
    write_json(
        args.output / "preparation.json",
        {
            "results": results,
            "memory_note": "Process high-water mark; cumulative across this invocation",
        },
    )
    if any(r["status"] == "failed" for r in results):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
