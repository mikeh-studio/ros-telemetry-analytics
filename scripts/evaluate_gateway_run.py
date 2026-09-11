"""Evaluate a captured transport fixture against its independent publisher ledger."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path


def evaluate(capture: dict, fixture: dict, snapshot: dict) -> dict:
    records = capture["records"]
    envelopes = [row["value"] for row in records["telemetry.events.v1"]]
    telemetry = [row for row in envelopes if row["envelope_type"] == "telemetry"]
    started = [
        row["stream_timestamp_ms"] for row in envelopes if row["envelope_type"] == "run_started"
    ]
    ended = [row["stream_timestamp_ms"] for row in envelopes if row["envelope_type"] == "run_ended"]
    if not started or not ended:
        raise ValueError("Captured run needs both startup and terminal lifecycle evidence")
    start, end = min(started), min(ended)
    observed = {
        (row["topic"], row["body"]["attributes"]["ros_timestamp_ns"])
        for row in telemetry
        if row["body"]["attributes"].get("ros_timestamp_ns") is not None
    }
    # Explicitly exclude discovery and the final 100 ms where publication can
    # race subscription teardown; report exclusions rather than calling them delivered.
    eligible = {
        (row["topic"], row["source_timestamp_ns"])
        for row in fixture["records"]
        if row["subscription_count"] > 0
        and start * 1_000_000 <= row["published_wall_ns"] < (end - 100) * 1_000_000
    }
    fault_start = fixture["scan_dropout_start_ns"] // 1_000_000
    fault_end = fixture["scan_dropout_end_ns"] // 1_000_000
    qos = fixture.get("fault") == "qos"
    if qos:
        if fixture.get("qos_transition_ns") is None:
            raise ValueError("QoS experiment has no independently recorded compatibility repair")
        fault_start, fault_end = start, fixture["qos_transition_ns"] // 1_000_000
    anomalies = records["telemetry.anomalies.v1"]
    opens = [row for row in anomalies if row["value"]["status"] == "active"]
    matched = [
        row
        for row in opens
        if row["value"]["topic"] == "/scan"
        and row["value"]["condition_type"] == ("NEVER_SEEN" if qos else "GAP")
        and fault_start <= row["value"]["detected_stream_ms"] <= fault_end
    ]
    recoveries = [
        row
        for row in anomalies
        if row["value"]["status"] == "recovered"
        and any(row["value"]["anomaly_id"] == item["value"]["anomaly_id"] for item in matched)
    ]
    unexpected = [
        row["value"]
        for row in opens
        if row not in matched
        and not (
            row["value"]["topic"] == "/scan"
            and row["value"]["condition_type"] == "RATE"
            and fault_start <= row["value"]["detected_stream_ms"] <= fault_end + 10000
        )
    ]
    ids = [row["envelope_id"] for row in telemetry]
    summary_counts = sum(
        row["payload"]["message_count"] for row in snapshot["mission_summaries"].values()
    )
    checks = {
        "matching_run": snapshot["run_id"] == capture["run_id"],
        "source_ledger_reconciled": bool(eligible) and not (eligible - observed),
        "no_duplicate_envelopes": len(ids) == len(set(ids)),
        "no_schema_rejections": not records["telemetry.dead-letter.v1"],
        "no_late_records": not records["telemetry.late.v1"],
        "one_scan_gap_detected": len(matched) == 1,
        "scan_gap_recovered": len(recoveries) == 1,
        "no_unexpected_alerts": not unexpected,
        "summaries_verified": snapshot["completion"]["verified"],
        "summary_counts_reconciled": summary_counts == len(set(ids)),
    }
    qos_events = []
    if fixture.get("fault") == "clean":
        checks.pop("one_scan_gap_detected")
        checks.pop("scan_gap_recovered")
        checks["no_unexpected_alerts"] = not opens
        checks["projection_recovered"] = not any(
            row["status"] == "active" for row in snapshot["anomalies"]
        )
    if qos:
        qos_events = [
            row["body"]["attributes"]
            for row in telemetry
            if row["topic"] == "/_telemetry/gateway_events"
            and row["body"]["attributes"].get("event_kind") == "qos_incompatible"
            and row["body"]["attributes"].get("affected_topic") == "/scan"
        ]
        checks["one_never_seen_detected"] = checks.pop("one_scan_gap_detected")
        checks["scan_recovers_after_qos_fix"] = checks.pop("scan_gap_recovered")
        checks["qos_incompatibility_observed"] = any(row.get("count", 0) > 0 for row in qos_events)
        checks["publisher_active_during_incompatibility"] = any(
            row["topic"] == "/scan" and row["published_wall_ns"] < fixture["qos_transition_ns"]
            for row in fixture["records"]
        )
        checks["no_incompatible_scan_delivered"] = all(
            row["body"]["attributes"]["ros_timestamp_ns"] >= fixture["qos_transition_ns"]
            for row in telemetry
            if row["topic"] == "/scan"
        )
        checks["projection_recovered"] = not any(
            row["status"] == "active" for row in snapshot["anomalies"]
        )
    return {
        "run_id": capture["run_id"],
        "passed": all(checks.values()),
        "checks": checks,
        "fault": fixture.get("fault", "silence"),
        "qos_events": qos_events,
        "scope": "Real DDS transport fixture; not Nav2 or physical robot evidence",
        "received_by_topic": dict(Counter(row["topic"] for row in telemetry)),
        "publisher_records": len(fixture["records"]),
        "eligible_publisher_records": len(eligible),
        "excluded_publisher_records": len(fixture["records"]) - len(eligible),
        "eligibility": (
            "Subscriber discovered and publication within session, excluding final 100 ms"
        ),
        "missing_eligible_records": len(eligible - observed),
        "summary_message_count": summary_counts,
        ("never_seen_detection_stream_delay_ms" if qos else "gap_detection_stream_delay_ms"): [
            row["value"]["detected_stream_ms"] - fault_start for row in matched
        ],
        ("never_seen_detection_broker_delay_ms" if qos else "gap_detection_broker_delay_ms"): [
            row["broker_timestamp_ms"] - fault_start for row in matched
        ],
        ("qos_recovery_broker_delay_ms" if qos else "gap_recovery_broker_delay_ms"): [
            row["broker_timestamp_ms"] - fault_end for row in recoveries
        ],
        "unexpected_alerts": unexpected,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("capture", "fixture", "snapshot", "output"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    args = parser.parse_args()
    report = evaluate(
        *(json.loads(path.read_text()) for path in (args.capture, args.fixture, args.snapshot))
    )
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps(report["checks"], sort_keys=True))
    raise SystemExit(0 if report["passed"] else 1)


if __name__ == "__main__":
    main()
