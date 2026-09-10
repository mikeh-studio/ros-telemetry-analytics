"""Check exact injected event IDs, dispositions, and final analytical counts."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path


def evaluate(capture, fixture, snapshot, injections):
    mode = fixture["fault"]
    expected_ids = {row["event_id"] for row in injections}
    telemetry = [
        row["value"]
        for row in capture["records"]["telemetry.events.v1"]
        if row["value"]["envelope_type"] == "telemetry"
    ]
    counts = Counter(row["body"]["event_id"] for row in telemetry)
    side = [row["value"] for row in capture["records"]["telemetry.late.v1"]]
    reason = "duplicate" if mode == "duplicate" else "beyond_allowed_lateness"
    disposition_ids = [row["event_id"] for row in side if row["reason"] == reason]
    allowed = {reason} if mode == "duplicate" else {reason, "sequence_gap", "sequence_regression"}
    accepted = len(counts) - (len(disposition_ids) if mode == "delay" else 0)
    scan_summary = snapshot["mission_summaries"]["/scan"]["payload"]
    total = sum(row["payload"]["message_count"] for row in snapshot["mission_summaries"].values())
    envelopes = [row["value"] for row in capture["records"]["telemetry.events.v1"]]
    start = min(
        row["stream_timestamp_ms"] for row in envelopes if row["envelope_type"] == "run_started"
    )
    end = min(
        row["stream_timestamp_ms"] for row in envelopes if row["envelope_type"] == "run_ended"
    )
    eligible = {
        (row["topic"], row["source_timestamp_ns"])
        for row in fixture["records"]
        if row["subscription_count"] > 0
        and start * 1_000_000 <= row["published_wall_ns"] < (end - 100) * 1_000_000
    }
    observed = {
        (row["topic"], row["body"]["attributes"].get("ros_timestamp_ns")) for row in telemetry
    }
    checks = {
        "matching_run": capture["run_id"] == snapshot["run_id"],
        "ten_distinct_injections": len(injections) == len(expected_ids) == 10,
        "injections_completed": all(row.get("completed_wall_ns") for row in injections),
        "source_ledger_reconciled": bool(eligible) and not (eligible - observed),
        "exact_broker_multiplicity": all(
            count == (2 if mode == "duplicate" and event_id in expected_ids else 1)
            for event_id, count in counts.items()
        )
        and expected_ids <= counts.keys(),
        "exact_disposition_ids": Counter(disposition_ids) == Counter(expected_ids),
        "only_expected_dispositions": all(row["reason"] in allowed for row in side),
        "no_schema_rejections": not capture["records"]["telemetry.dead-letter.v1"],
        "summaries_verified": snapshot["completion"]["verified"],
        "accepted_counts_reconcile": total == accepted,
        "no_unexpected_incidents": not capture["records"]["telemetry.anomalies.v1"],
        "no_projected_active_incidents": not any(
            row["status"] == "active" for row in snapshot["anomalies"]
        ),
    }
    if mode == "delay":
        checks["exact_disposition_ids"] = (
            set(disposition_ids) <= expected_ids
            and len(disposition_ids) == len(set(disposition_ids))
            and Counter(row["event_id"] for row in side if row["reason"] == "sequence_regression")
            == Counter(expected_ids)
        )
        checks["late_counters_reconcile"] = scan_summary.get("too_late_count") == len(
            disposition_ids
        ) and scan_summary.get("accepted_late_count") == len(expected_ids) - len(disposition_ids)
        checks["rejections_follow_watermark"] = all(
            row["watermark_ms"] > row["envelope"]["stream_timestamp_ms"] + 5000
            for row in side
            if row["reason"] == reason
        )
        checks["ten_second_delay_observed"] = all(
            row.get("completed_wall_ns", 0) - row["handoff_wall_ns"] >= 10_000_000_000
            for row in injections
        )
    else:
        checks["duplicate_counter_reconciles"] = scan_summary.get("duplicate_count") == len(
            expected_ids
        )
    return {
        "run_id": capture["run_id"],
        "fault": mode,
        "passed": all(checks.values()),
        "checks": checks,
        "broker_telemetry_count": len(telemetry),
        "unique_observations": len(counts),
        "accepted_observations": accepted,
        "summary_message_count": total,
        "accepted_late_count": scan_summary.get("accepted_late_count", 0),
        "side_dispositions": dict(Counter(row["reason"] for row in side)),
        "injected_event_ids": sorted(expected_ids),
        "eligible_publications": len(eligible),
        "excluded_publications": len(fixture["records"]) - len(eligible),
        "scope": (
            "Real DDS fixture with a test-only pre-Kafka transport shim; "
            "not a durable gateway guarantee"
        ),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("capture", "fixture", "snapshot", "injections", "output"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    args = parser.parse_args()
    report = evaluate(
        *(
            json.loads(path.read_text())
            for path in (args.capture, args.fixture, args.snapshot, args.injections)
        )
    )
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps(report))
    raise SystemExit(0 if report["passed"] else 1)
