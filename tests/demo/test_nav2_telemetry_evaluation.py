import json

from scripts.evaluate_nav2_telemetry import evaluate


def test_labels_only_score_detector_output_and_source_mutation_fails(tmp_path):
    signals, events = [], []
    for index, (time, position) in enumerate(((1000, 10), (2000, 12), (3000, 10))):
        for topic, x, timestamp in (("/odom", 0, time), ("/amcl_pose", position, time + 1)):
            event_id = f"{index}-{topic}"
            attrs = {
                "position_x": x,
                "position_y": 0,
                "yaw": 0,
                "frame_id": "map" if topic == "/amcl_pose" else "odom",
                "ros_timestamp_ns": timestamp * 1_000_000,
            }
            identity = {
                "run_id": "r",
                "robot_id": "bot",
                "topic": topic,
                "stream_timestamp_ms": timestamp,
            }
            signals.append({**identity, "payload": {"attributes": attrs, "event_id": event_id}})
            events.append(
                {
                    "value": {
                        **identity,
                        "envelope_type": "telemetry",
                        "envelope_id": event_id,
                        "body": {"event_id": event_id, "attributes": attrs},
                    }
                }
            )
    fixture = {
        "passed": True,
        "actions": {
            name: {"wall_ms": value}
            for name, value in (("baseline", 1000), ("disturbance", 2000), ("repair", 3000))
        },
        "samples": [
            {
                "topic": row["topic"],
                "wall_ms": row["stream_timestamp_ms"],
                "ros_timestamp_ns": row["payload"]["attributes"]["ros_timestamp_ns"],
            }
            for row in signals
        ],
    }
    snapshot = {
        "run_id": "r",
        "observed_signals": signals,
        "completion": {"verified": True},
        "mission_summaries": {"summary": {"payload": {"message_count": 6}}},
    }
    capture = {
        "run_id": "r",
        "records": {
            "telemetry.events.v1": events,
            "telemetry.late.v1": [],
            "telemetry.dead-letter.v1": [],
            "telemetry.anomalies.v1": [],
        },
    }
    for name, value in (
        ("evaluation.json", fixture),
        ("snapshot.json", snapshot),
        ("kafka.json", capture),
    ):
        (tmp_path / name).write_text(json.dumps(value))
    original = evaluate(tmp_path)
    assert original["passed"]
    fixture["actions"]["disturbance"]["wall_ms"] = 2500
    (tmp_path / "evaluation.json").write_text(json.dumps(fixture))
    changed = evaluate(tmp_path)
    assert changed["detector"] == original["detector"]
    assert not changed["checks"]["one_inconsistency_detected_during_fault"]
    snapshot["observed_signals"][1]["payload"]["attributes"]["position_x"] = 99
    (tmp_path / "snapshot.json").write_text(json.dumps(snapshot))
    assert not evaluate(tmp_path)["checks"]["projected_signals_preserve_source"]
