"""Reconcile retained live signal metrics with source envelopes and API projection."""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path


def evaluate(capture: dict, snapshot: dict) -> dict:
    sources = {
        row["value"]["body"]["event_id"]: row["value"]
        for row in capture["records"]["telemetry.events.v1"]
        if row["value"]["envelope_type"] == "telemetry"
    }
    signals = {
        row["value"]["metric_id"]: row["value"]
        for row in capture["records"]["telemetry.metrics.v1"]
        if row["value"]["metric_type"] == "observed_signal"
    }
    by_topic = defaultdict(list)
    mismatches = []
    for metric in signals.values():
        source = sources.get(metric["payload"]["event_id"])
        if (
            source is None
            or any(
                metric[key] != source[key]
                for key in ("run_id", "robot_id", "topic", "stream_timestamp_ms")
            )
            or metric["payload"]["attributes"] != source["body"]["attributes"]
        ):
            mismatches.append(metric["metric_id"])
        by_topic[(metric["robot_id"], metric["topic"])].append(metric)
    expected = {
        row["metric_id"]: row
        for values in by_topic.values()
        for row in sorted(values, key=lambda row: row["stream_timestamp_ms"])[-180:]
    }
    projected = {row["metric_id"]: row for row in snapshot.get("observed_signals", [])}
    topics = {row["topic"] for row in signals.values()}
    checks = {
        "same_run": capture["run_id"] == snapshot["run_id"],
        "signals_present": bool(signals),
        "pose_and_odometry_present": {"/amcl_pose", "/odom"} <= topics,
        "coordinate_frames_present": all(
            row["payload"]["attributes"].get("frame_id")
            for row in signals.values()
            if row["topic"] in {"/amcl_pose", "/odom"}
        ),
        "source_fields_preserved": not mismatches,
        "retained_projection_exact": projected == expected,
        "one_sample_per_topic_bucket": all(
            len(rows) == len({row["window_start_ms"] for row in rows}) for rows in by_topic.values()
        ),
        "qos_callback_projected": any(
            row["payload"]["attributes"].get("event_kind") == "qos_incompatible"
            and row["payload"]["attributes"].get("affected_topic") == "/scan"
            for row in projected.values()
        ),
    }
    return {
        "run_id": capture["run_id"],
        "passed": all(checks.values()),
        "checks": checks,
        "signal_count": len(signals),
        "retained_count": len(projected),
        "topics": sorted(topics),
        "source_mismatches": mismatches,
        "scope": "Synthetic DDS QoS fixture; source and API reconciliation, not rendered UI",
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for field in ("capture", "snapshot", "output"):
        parser.add_argument(f"--{field}", type=Path, required=True)
    args = parser.parse_args()
    report = evaluate(json.loads(args.capture.read_text()), json.loads(args.snapshot.read_text()))
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps(report))
    raise SystemExit(0 if report["passed"] else 1)
