"""Real ROS messages for transport tests; this is not a navigating robot simulation."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path


def main():
    import rclpy
    from diagnostic_msgs.msg import DiagnosticArray, DiagnosticStatus
    from geometry_msgs.msg import PoseWithCovarianceStamped
    from nav_msgs.msg import Odometry
    from rclpy.qos import QoSProfile, ReliabilityPolicy, qos_profile_sensor_data
    from sensor_msgs.msg import LaserScan

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--duration-s", type=float, default=25)
    parser.add_argument("--dropout-start-s", type=float, default=8)
    parser.add_argument("--dropout-end-s", type=float, default=13)
    parser.add_argument("--output", type=Path, default=Path("/state/fixture.json"))
    parser.add_argument(
        "--fault", choices=["clean", "silence", "qos", "duplicate", "delay"], default="silence"
    )
    args = parser.parse_args()
    rclpy.init()
    node = rclpy.create_node("gateway_transport_fixture")
    publishers = {
        "/scan": node.create_publisher(LaserScan, "/scan", qos_profile_sensor_data),
        "/odom": node.create_publisher(Odometry, "/odom", qos_profile_sensor_data),
        "/amcl_pose": node.create_publisher(
            PoseWithCovarianceStamped, "/amcl_pose", qos_profile_sensor_data
        ),
        "/diagnostics": node.create_publisher(
            DiagnosticArray, "/diagnostics", qos_profile_sensor_data
        ),
    }
    counts = dict.fromkeys(publishers, 0)
    records = []
    started = time.monotonic()
    wall_start_ns = time.time_ns()
    next_due = dict.fromkeys(publishers, 0.0)
    qos_transition_ns = None
    periods = {"/scan": 0.1, "/odom": 0.05, "/amcl_pose": 1.0, "/diagnostics": 1.0}
    try:
        while (elapsed := time.monotonic() - started) < args.duration_s:
            rclpy.spin_once(node, timeout_sec=0)
            if args.fault == "qos" and qos_transition_ns is None and elapsed >= args.dropout_end_s:
                node.destroy_publisher(publishers["/scan"])
                publishers["/scan"] = node.create_publisher(
                    LaserScan, "/scan", QoSProfile(depth=10, reliability=ReliabilityPolicy.RELIABLE)
                )
                qos_transition_ns = time.time_ns()
            for topic in publishers:
                if elapsed < next_due[topic]:
                    continue
                next_due[topic] += periods[topic]
                if (
                    args.fault == "silence"
                    and topic == "/scan"
                    and args.dropout_start_s <= elapsed < args.dropout_end_s
                ):
                    continue
                if topic == "/scan":
                    message = LaserScan()
                    message.range_min = 0.1
                    message.range_max = 10.0
                    message.ranges = [2.0] * 36
                elif topic == "/odom":
                    message = Odometry()
                    message.pose.pose.position.x = elapsed * 0.1
                    message.pose.pose.orientation.w = 1.0
                elif topic == "/amcl_pose":
                    message = PoseWithCovarianceStamped()
                    message.pose.pose.position.x = elapsed * 0.1
                    message.pose.pose.orientation.w = 1.0
                else:
                    message = DiagnosticArray()
                    status = DiagnosticStatus()
                    status.name = "transport_fixture"
                    status.message = "synthetic ROS publisher"
                    message.status = [status]
                message.header.stamp = node.get_clock().now().to_msg()
                message.header.frame_id = {"/odom": "odom", "/amcl_pose": "map"}.get(
                    topic, "base_link"
                )
                publishers[topic].publish(message)
                counts[topic] += 1
                records.append(
                    {
                        "topic": topic,
                        "source_timestamp_ns": message.header.stamp.sec * 1_000_000_000
                        + message.header.stamp.nanosec,
                        "published_wall_ns": time.time_ns(),
                        "subscription_count": publishers[topic].get_subscription_count(),
                    }
                )
            time.sleep(0.001)
    finally:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(
                {
                    "source": "ROS message fixture, not Nav2",
                    "fault": args.fault,
                    "qos_transition_ns": qos_transition_ns,
                    "wall_start_ns": wall_start_ns,
                    "published": counts,
                    "records": records,
                    "scan_dropout_start_ns": wall_start_ns + int(args.dropout_start_s * 1e9),
                    "scan_dropout_end_ns": wall_start_ns + int(args.dropout_end_s * 1e9),
                },
                indent=2,
            )
            + "\n"
        )
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
