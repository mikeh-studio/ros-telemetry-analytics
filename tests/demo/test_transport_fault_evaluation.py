from copy import deepcopy

import pytest

from scripts.evaluate_transport_fault import evaluate


def evidence(mode):
    telemetry = [
        {
            "envelope_type": "telemetry",
            "topic": "/scan",
            "body": {"event_id": str(index), "attributes": {"ros_timestamp_ns": index * 1_000_000}},
        }
        for index in range(20)
    ]
    fixture = {
        "fault": mode,
        "records": [
            {
                "topic": "/scan",
                "source_timestamp_ns": index * 1_000_000,
                "published_wall_ns": index * 1_000_000,
                "subscription_count": 1,
            }
            for index in range(20)
        ],
    }
    injections = [
        {"event_id": str(index), "handoff_wall_ns": 1, "completed_wall_ns": 10_000_000_001}
        for index in range(10)
    ]
    records = {
        "telemetry.events.v1": [
            {"value": row}
            for row in [
                {"envelope_type": "run_started", "stream_timestamp_ms": 0},
                *telemetry,
                *(telemetry[:10] if mode == "duplicate" else []),
                {"envelope_type": "run_ended", "stream_timestamp_ms": 1000},
            ]
        ],
        "telemetry.late.v1": [
            {
                "value": {
                    "event_id": str(index),
                    "reason": "duplicate" if mode == "duplicate" else "beyond_allowed_lateness",
                    "watermark_ms": 6000,
                    "envelope": {"stream_timestamp_ms": 0},
                }
            }
            for index in range(10)
        ],
        "telemetry.dead-letter.v1": [],
        "telemetry.anomalies.v1": [],
    }
    snapshot = {
        "run_id": "run",
        "completion": {"verified": True},
        "anomalies": [],
        "mission_summaries": {
            "/scan": {
                "payload": {
                    "message_count": 20 if mode == "duplicate" else 10,
                    "duplicate_count": 10 if mode == "duplicate" else 0,
                    "accepted_late_count": 0,
                    "too_late_count": 10 if mode == "delay" else 0,
                }
            }
        },
    }
    if mode == "delay":
        records["telemetry.late.v1"] += [
            {"value": {"event_id": str(index), "reason": "sequence_regression"}}
            for index in range(10)
        ]
    return {"run_id": "run", "records": records}, fixture, snapshot, injections


@pytest.mark.parametrize("mode", ["duplicate", "delay"])
def test_fault_accounting_requires_exact_ids_and_source_reconciliation(mode):
    capture, fixture, snapshot, injections = evidence(mode)
    assert evaluate(capture, fixture, snapshot, injections)["passed"]
    bad = deepcopy(capture)
    bad["records"]["telemetry.late.v1"][0]["value"]["event_id"] = "unexpected"
    assert not evaluate(bad, fixture, snapshot, injections)["checks"]["exact_disposition_ids"]
    missing = deepcopy(fixture)
    missing["records"][0]["source_timestamp_ns"] = 999
    assert not evaluate(capture, missing, snapshot, injections)["checks"][
        "source_ledger_reconciled"
    ]
    bad_snapshot = deepcopy(snapshot)
    bad_snapshot["mission_summaries"]["/scan"]["payload"]["message_count"] += 1
    assert not evaluate(capture, fixture, bad_snapshot, injections)["checks"][
        "accepted_counts_reconcile"
    ]


def test_delay_checks_mixed_acceptance_against_counters_and_rejection_watermarks():
    capture, fixture, snapshot, injections = evidence("delay")
    capture["records"]["telemetry.late.v1"] = capture["records"]["telemetry.late.v1"][4:]
    payload = snapshot["mission_summaries"]["/scan"]["payload"]
    payload.update(message_count=14, accepted_late_count=4, too_late_count=6)
    assert evaluate(capture, fixture, snapshot, injections)["passed"]
    capture["records"]["telemetry.late.v1"][0]["value"]["watermark_ms"] = 5000
    assert not evaluate(capture, fixture, snapshot, injections)["checks"][
        "rejections_follow_watermark"
    ]
    payload["accepted_late_count"] = 5
    assert not evaluate(capture, fixture, snapshot, injections)["checks"]["late_counters_reconcile"]
