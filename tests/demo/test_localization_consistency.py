import math

from demo.common.localization_consistency import evaluate_consistency


def sample(topic, time, x, y=0, yaw=0, frame=None):
    return {
        "run_id": "r",
        "robot_id": "robot",
        "topic": topic,
        "stream_timestamp_ms": time,
        "payload": {
            "attributes": {
                "ros_timestamp_ns": time * 1_000_000,
                "frame_id": frame or ("map" if topic == "/amcl_pose" else "odom"),
                "position_x": x,
                "position_y": y,
                "yaw": yaw,
            }
        },
    }


def test_motion_is_transformed_without_treating_different_frame_origins_as_failure():
    signals = [
        sample("/odom", 0, 0),
        sample("/amcl_pose", 1, 10, 20, math.pi / 2),
        sample("/odom", 1000, 1),
        sample("/amcl_pose", 1001, 10, 21, math.pi / 2),
    ]
    result = evaluate_consistency(signals)
    assert result["transitions"] == []
    assert result["states"][-1]["residual_m"] < 1e-9


def test_disagreement_opens_and_recovers_without_fault_labels():
    signals = [sample("/odom", time, 0) for time in (0, 1000, 2000)]
    signals += [
        sample("/amcl_pose", 1, 10),
        sample("/amcl_pose", 1001, 12),
        sample("/amcl_pose", 2001, 10),
    ]
    result = evaluate_consistency(signals)
    assert [row["status"] for row in result["transitions"]] == ["active", "recovered"]
    assert not result["active"]


def test_future_stale_or_changed_frame_data_cannot_establish_agreement():
    assert (
        evaluate_consistency([sample("/amcl_pose", 1, 0), sample("/odom", 2, 0)])["states"][0][
            "state"
        ]
        == "unknown"
    )
    assert (
        evaluate_consistency([sample("/odom", 0, 0), sample("/amcl_pose", 2000, 0)])["states"][0][
            "state"
        ]
        == "unknown"
    )
    signals = [
        sample("/odom", 0, 0),
        sample("/amcl_pose", 1, 0),
        sample("/odom", 1000, 0),
        sample("/amcl_pose", 1001, 0, frame="new_map"),
    ]
    assert evaluate_consistency(signals)["states"][-1]["state"] == "unknown"
