"""Controlled AMCL estimate reset in the bundled stationary Gazebo sandbox."""

from __future__ import annotations

import argparse
import json
import math
import time
from pathlib import Path


def evaluate(samples, actions, offset_m):
    initial, disturbance, repair = (
        actions.get(name) for name in ("baseline", "disturbance", "repair")
    )
    if not all((initial, disturbance, repair)):
        return {"passed": False, "checks": {"all_phases_completed": False}}
    poses = [row for row in samples if row["topic"] == "/amcl_pose"]
    baseline = [
        row for row in poses if initial["wall_ms"] <= row["wall_ms"] < disturbance["wall_ms"]
    ]
    fault = [row for row in poses if disturbance["wall_ms"] <= row["wall_ms"] < repair["wall_ms"]]
    recovery = [row for row in poses if row["wall_ms"] >= repair["wall_ms"]]

    def distance(row):
        return math.hypot(row["x"] + 2.0, row["y"] + 0.5)

    odom = [row for row in samples if row["topic"] == "/odom"]
    displacement = max(
        (math.hypot(row["x"] - odom[0]["x"], row["y"] - odom[0]["y"]) for row in odom), default=None
    )
    detected = next((row for row in fault if distance(row) >= offset_m * 0.6), None)
    recovered = next((row for row in recovery if distance(row) <= 0.25), None)
    checks = {
        "baseline_near_spawn": bool(baseline) and distance(baseline[-1]) <= 0.25,
        "injected_estimate_displacement_observed": detected is not None,
        "estimate_restored_after_reset": recovered is not None,
        "odometry_remained_stationary": displacement is not None and displacement <= 0.1,
        "both_pose_frames_present": {row["frame_id"] for row in poses} == {"map"}
        and bool(odom)
        and all(row["frame_id"] for row in odom),
    }
    return {
        "passed": all(checks.values()),
        "checks": checks,
        "fault_observation_delay_ms": detected["wall_ms"] - disturbance["wall_ms"]
        if detected
        else None,
        "repair_observation_delay_ms": recovered["wall_ms"] - repair["wall_ms"]
        if recovered
        else None,
        "max_odometry_displacement_m": displacement,
        "max_fault_estimate_distance_m": max(map(distance, fault), default=None),
        "pose_samples": len(poses),
        "scope": (
            "Controlled AMCL estimate reset and manual restoration in Gazebo; "
            "not autonomous relocalization or production detection"
        ),
    }


def main():
    import rclpy
    from geometry_msgs.msg import PoseWithCovarianceStamped
    from nav_msgs.msg import Odometry
    from rclpy.parameter import Parameter
    from rclpy.qos import qos_profile_sensor_data

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--offset-m", type=float, default=1.5)
    parser.add_argument("--timeout-s", type=float, default=100)
    parser.add_argument("--ready-file", type=Path)
    parser.add_argument("--go-file", type=Path)
    args = parser.parse_args()
    if not 1 <= args.offset_m <= 3:
        parser.error("Use a 1–3 m disturbance in the bundled sandbox")
    rclpy.init()
    node = rclpy.create_node(
        "telemetry_localization_fault", parameter_overrides=[Parameter("use_sim_time", value=True)]
    )
    publisher = node.create_publisher(PoseWithCovarianceStamped, "/initialpose", 10)
    samples, actions = [], {}
    started = time.monotonic()

    def receive(topic, message):
        samples.append(
            {
                "topic": topic,
                "wall_ms": time.time_ns() // 1_000_000,
                "ros_timestamp_ns": message.header.stamp.sec * 1_000_000_000
                + message.header.stamp.nanosec,
                "frame_id": message.header.frame_id,
                "x": message.pose.pose.position.x,
                "y": message.pose.pose.position.y,
            }
        )

    for topic, message_type in (("/amcl_pose", PoseWithCovarianceStamped), ("/odom", Odometry)):
        node.create_subscription(
            message_type,
            topic,
            lambda msg, topic=topic: receive(topic, msg),
            qos_profile_sensor_data,
        )

    def spin_until(predicate):
        while not predicate():
            if time.monotonic() - started > args.timeout_s:
                raise TimeoutError("Localization disturbance exceeded its deadline")
            rclpy.spin_once(node, timeout_sec=0.1)

    def reset(name, offset):
        pose = PoseWithCovarianceStamped()
        pose.header.frame_id = "map"
        pose.header.stamp = node.get_clock().now().to_msg()
        pose.pose.pose.position.x, pose.pose.pose.position.y = -2.0 + offset, -0.5
        pose.pose.pose.orientation.w = 1.0
        pose.pose.covariance[0] = pose.pose.covariance[7] = pose.pose.covariance[35] = 0.01
        actions[name] = {"wall_ms": time.time_ns() // 1_000_000, "x": -2.0 + offset, "y": -0.5}
        publisher.publish(pose)
        until = time.monotonic() + 6
        spin_until(lambda: time.monotonic() >= until)

    error = None
    try:
        spin_until(
            lambda: (
                publisher.get_subscription_count() > 0 and node.get_clock().now().nanoseconds > 0
            )
        )
        if args.ready_file:
            if args.go_file is None:
                raise ValueError("A go-file is required with ready-file")
            reset("initialization", 0)
            spin_until(lambda: any(row["topic"] == "/amcl_pose" for row in samples))
            args.ready_file.touch()
            spin_until(args.go_file.exists)
        reset("baseline", 0)
        spin_until(lambda: any(row["topic"] == "/amcl_pose" for row in samples))
        reset("disturbance", args.offset_m)
        reset("repair", 0)
    except Exception as exc:
        error = str(exc)
    finally:
        report = evaluate(samples, actions, args.offset_m)
        if error:
            report.update(passed=False, error=error)
        report.update(samples=samples, actions=actions, offset_m=args.offset_m)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2) + "\n")
        node.destroy_node()
        rclpy.shutdown()
    print(json.dumps({key: value for key, value in report.items() if key != "samples"}))
    raise SystemExit(0 if report["passed"] else 1)


if __name__ == "__main__":
    main()
