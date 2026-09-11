from copy import deepcopy

from scripts.nav2_localization_fault import evaluate


def evidence():
    actions = {
        name: {"wall_ms": timestamp}
        for name, timestamp in (("baseline", 0), ("disturbance", 10000), ("repair", 20000))
    }
    samples = [
        {"topic": "/amcl_pose", "wall_ms": timestamp, "x": x, "y": -0.5, "frame_id": "map"}
        for timestamp, x in ((1000, -2.0), (11000, -0.5), (21000, -2.0))
    ] + [
        {"topic": "/odom", "wall_ms": timestamp, "x": 0, "y": 0, "frame_id": "odom"}
        for timestamp in (1000, 11000, 21000)
    ]
    return samples, actions


def test_disturbance_requires_recovery_and_stationary_odometry():
    samples, actions = evidence()
    assert evaluate(samples, actions, 1.5)["passed"]
    moved = deepcopy(samples)
    moved[-1]["x"] = 0.5
    assert not evaluate(moved, actions, 1.5)["checks"]["odometry_remained_stationary"]
    unrecovered = deepcopy(samples)
    unrecovered[2]["x"] = -0.5
    assert not evaluate(unrecovered, actions, 1.5)["checks"]["estimate_restored_after_reset"]
    assert not evaluate(samples, {}, 1.5)["passed"]


def test_fault_detection_must_fall_in_the_independently_recorded_fault_interval():
    samples, actions = evidence()
    samples[1]["wall_ms"] = 9000
    assert not evaluate(samples, actions, 1.5)["checks"]["injected_estimate_displacement_observed"]
