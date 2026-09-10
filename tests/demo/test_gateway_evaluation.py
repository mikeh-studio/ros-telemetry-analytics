from copy import deepcopy

from scripts.evaluate_gateway_run import evaluate


def test_clean_control_rejects_any_incident():
    capture, fixture, snapshot = evidence()
    fixture["fault"] = "clean"
    snapshot["anomalies"] = []
    assert not evaluate(capture, fixture, snapshot)["checks"]["no_unexpected_alerts"]
    capture["records"]["telemetry.anomalies.v1"] = []
    assert evaluate(capture, fixture, snapshot)["passed"]


def evidence():
    capture = {
        "run_id": "live-test",
        "records": {
            "telemetry.events.v1": [
                {"value": item}
                for item in [
                    {"envelope_type": "run_started", "stream_timestamp_ms": 1000},
                    {"envelope_type": "run_ended", "stream_timestamp_ms": 30000},
                    {
                        "envelope_type": "telemetry",
                        "envelope_id": "one",
                        "topic": "/scan",
                        "body": {"attributes": {"ros_timestamp_ns": 50}},
                    },
                ]
            ],
            "telemetry.anomalies.v1": [
                {
                    "broker_timestamp_ms": 13000,
                    "value": {
                        "anomaly_id": "gap",
                        "status": "active",
                        "condition_type": "GAP",
                        "topic": "/scan",
                        "detected_stream_ms": 11000,
                    },
                },
                {
                    "broker_timestamp_ms": 18000,
                    "value": {
                        "anomaly_id": "gap",
                        "status": "recovered",
                        "condition_type": "GAP",
                        "topic": "/scan",
                        "detected_stream_ms": 16000,
                    },
                },
            ],
            "telemetry.dead-letter.v1": [],
            "telemetry.late.v1": [],
        },
    }
    fixture = {
        "records": [
            {
                "topic": "/scan",
                "source_timestamp_ns": 50,
                "subscription_count": 1,
                "published_wall_ns": 2_000_000_000,
            }
        ],
        "scan_dropout_start_ns": 10_000_000_000,
        "scan_dropout_end_ns": 15_000_000_000,
    }
    snapshot = {
        "run_id": "live-test",
        "completion": {"verified": True},
        "mission_summaries": {"/scan": {"payload": {"message_count": 1}}},
    }
    return capture, fixture, snapshot


def test_eval_separates_event_detection_from_broker_visibility():
    report = evaluate(*evidence())
    assert report["passed"]
    assert report["gap_detection_stream_delay_ms"] == [1000]
    assert report["gap_detection_broker_delay_ms"] == [3000]
    assert report["gap_recovery_broker_delay_ms"] == [3000]


def test_eval_fails_on_missing_source_false_alarm_and_unverified_summary():
    capture, fixture, snapshot = deepcopy(evidence())
    fixture["records"][0]["source_timestamp_ns"] = 51
    snapshot["completion"]["verified"] = False
    capture["records"]["telemetry.anomalies.v1"].append(
        {
            "value": {
                "status": "active",
                "topic": "/odom",
                "condition_type": "RATE",
                "detected_stream_ms": 9000,
            }
        }
    )
    report = evaluate(capture, fixture, snapshot)
    assert not report["passed"]
    assert not report["checks"]["source_ledger_reconciled"]
    assert not report["checks"]["no_unexpected_alerts"]
    assert not report["checks"]["summaries_verified"]


def test_qos_case_requires_direct_incompatibility_evidence_and_a_repaired_stream():
    capture, fixture, snapshot = evidence()
    fixture.update(fault="qos", qos_transition_ns=15_000_000_000)
    fixture["records"][0].update(
        source_timestamp_ns=16_000_000_000, published_wall_ns=16_000_000_000
    )
    fixture["records"].append(
        {
            "topic": "/scan",
            "source_timestamp_ns": 5_000_000_000,
            "published_wall_ns": 5_000_000_000,
            "subscription_count": 0,
        }
    )
    capture["records"]["telemetry.events.v1"][-1]["value"]["body"]["attributes"][
        "ros_timestamp_ns"
    ] = 16_000_000_000
    for row in capture["records"]["telemetry.anomalies.v1"]:
        row["value"]["condition_type"] = "NEVER_SEEN"
    capture["records"]["telemetry.events.v1"].append(
        {
            "value": {
                "envelope_type": "telemetry",
                "envelope_id": "qos-evidence",
                "topic": "/_telemetry/gateway_events",
                "body": {
                    "attributes": {
                        "event_kind": "qos_incompatible",
                        "affected_topic": "/scan",
                        "count": 1,
                    }
                },
            }
        }
    )
    snapshot["mission_summaries"]["/scan"]["payload"]["message_count"] = 2
    snapshot["anomalies"] = []
    assert evaluate(capture, fixture, snapshot)["passed"]
    capture["records"]["telemetry.events.v1"].pop()
    assert not evaluate(capture, fixture, snapshot)["checks"]["qos_incompatibility_observed"]
