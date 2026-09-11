"""Evaluate captured Nav2 telemetry and relative-motion detection against reset actions."""

import argparse
import json
from pathlib import Path

from demo.common.localization_consistency import evaluate_consistency


def evaluate(directory):
    fixture = json.loads((directory / "evaluation.json").read_text())
    snapshot = json.loads((directory / "snapshot.json").read_text())
    capture = json.loads((directory / "kafka.json").read_text())
    telemetry = [
        row["value"]
        for row in capture["records"]["telemetry.events.v1"]
        if row["value"]["envelope_type"] == "telemetry"
    ]
    signals = snapshot.get("observed_signals", [])
    sources = {row["body"]["event_id"]: row for row in telemetry}
    signal_integrity = bool(signals)
    for signal in signals:
        source = sources.get(signal["payload"]["event_id"])
        signal_integrity &= (
            bool(source)
            and all(
                signal[key] == source[key]
                for key in ("run_id", "robot_id", "topic", "stream_timestamp_ms")
            )
            and signal["payload"]["attributes"] == source["body"]["attributes"]
        )
    result = evaluate_consistency(signals)
    start, end = (
        fixture["actions"]["disturbance"]["wall_ms"],
        fixture["actions"]["repair"]["wall_ms"],
    )
    opens = [row for row in result["transitions"] if row["status"] == "active"]
    recoveries = [row for row in result["transitions"] if row["status"] == "recovered"]
    baseline_ms = fixture["actions"]["baseline"]["wall_ms"]
    expected = {
        row["ros_timestamp_ns"]
        for row in fixture["samples"]
        if row["topic"] == "/amcl_pose" and row["wall_ms"] >= baseline_ms
    }
    received = {
        row["body"]["attributes"].get("ros_timestamp_ns")
        for row in telemetry
        if row["topic"] == "/amcl_pose"
    }
    checks = {
        "fixture_passed": fixture["passed"],
        "same_run": snapshot["run_id"] == capture["run_id"],
        "projected_signals_preserve_source": signal_integrity,
        "all_labeled_pose_samples_received": bool(expected) and expected <= received,
        "summaries_verified": snapshot["completion"]["verified"],
        "summary_count_reconciled": sum(
            row["payload"]["message_count"] for row in snapshot["mission_summaries"].values()
        )
        == len(telemetry),
        "no_duplicates": len({row["envelope_id"] for row in telemetry}) == len(telemetry),
        "no_rejected_records": not capture["records"]["telemetry.dead-letter.v1"]
        and not capture["records"]["telemetry.late.v1"],
        "no_transport_incidents": not capture["records"]["telemetry.anomalies.v1"],
        "one_inconsistency_detected_during_fault": len(opens) == 1
        and start <= opens[0]["stream_timestamp_ms"] < end,
        "one_recovery_after_repair": len(recoveries) == 1
        and recoveries[0]["stream_timestamp_ms"] >= end
        and not result["active"],
    }
    return {
        "passed": all(checks.values()),
        "checks": checks,
        "run_id": snapshot["run_id"],
        "detector": result,
        "summary_messages": len(telemetry),
        "detection_delay_ms": opens[0]["stream_timestamp_ms"] - start if len(opens) == 1 else None,
        "recovery_delay_ms": recoveries[0]["stream_timestamp_ms"] - end
        if len(recoveries) == 1
        else None,
        "detector_parameters": {"threshold_m": 0.5, "max_pair_age_ms": 1500},
        "scope": (
            "Post-run diagnostic on API signals from live Nav2; "
            "injection actions used only for scoring, not detector inputs"
        ),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, required=True)
    args = parser.parse_args()
    report = evaluate(args.directory)
    (args.directory / "telemetry-evaluation.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report))
    raise SystemExit(0 if report["passed"] else 1)
