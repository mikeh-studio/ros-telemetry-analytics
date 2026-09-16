"""Bounded mission for the bundled Gazebo sandbox; never use against a physical robot."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path


def main():
    import rclpy
    from geometry_msgs.msg import PoseWithCovarianceStamped
    from lifecycle_msgs.srv import GetState
    from nav2_msgs.action import NavigateToPose
    from nav_msgs.msg import Odometry
    from rclpy.action import ActionClient
    from rclpy.parameter import Parameter
    from rclpy.qos import qos_profile_sensor_data

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--timeout-s", type=float, default=90)
    args = parser.parse_args()
    rclpy.init()
    node = rclpy.create_node(
        "telemetry_simulation_mission",
        parameter_overrides=[
            Parameter("use_sim_time", value=True),
        ],
    )
    initial = node.create_publisher(PoseWithCovarianceStamped, "/initialpose", 10)
    poses = []
    localized = []
    node.create_subscription(
        Odometry,
        "/odom",
        lambda msg: poses.append(
            {
                "wall_ms": time.time_ns() // 1_000_000,
                "x": msg.pose.pose.position.x,
                "y": msg.pose.pose.position.y,
            }
        ),
        qos_profile_sensor_data,
    )
    node.create_subscription(
        PoseWithCovarianceStamped,
        "/amcl_pose",
        lambda msg: localized.append(msg),
        qos_profile_sensor_data,
    )
    client = ActionClient(node, NavigateToPose, "/navigate_to_pose")
    started = time.monotonic()
    report = {"source": "Gazebo sandbox with Nav2 and AMCL", "status": "failed"}

    def spin_until(predicate):
        while not predicate():
            if time.monotonic() - started > args.timeout_s:
                raise TimeoutError("Simulation mission exceeded its wall-clock deadline")
            rclpy.spin_once(node, timeout_sec=0.1)

    try:
        spin_until(
            lambda: node.get_clock().now().nanoseconds > 0 and initial.get_subscription_count() > 0
        )
        last_sent = 0.0
        while not localized:
            if time.monotonic() - started > args.timeout_s:
                raise TimeoutError("AMCL did not initialize")
            if time.monotonic() - last_sent > 1:
                pose = PoseWithCovarianceStamped()
                pose.header.frame_id = "map"
                pose.header.stamp = node.get_clock().now().to_msg()
                pose.pose.pose.position.x = -2.0
                pose.pose.pose.position.y = -0.5
                pose.pose.pose.orientation.w = 1.0
                pose.pose.covariance[0] = pose.pose.covariance[7] = 0.01
                pose.pose.covariance[35] = 0.01
                initial.publish(pose)
                last_sent = time.monotonic()
            rclpy.spin_once(node, timeout_sec=0.1)
        spin_until(client.server_is_ready)
        lifecycle = node.create_client(GetState, "/bt_navigator/get_state")
        spin_until(lifecycle.service_is_ready)
        while True:
            if time.monotonic() - started > args.timeout_s:
                raise TimeoutError("Nav2 did not become active before the mission deadline")
            state = lifecycle.call_async(GetState.Request())
            spin_until(state.done)
            if state.result().current_state.id == 3:
                break
            rclpy.spin_once(node, timeout_sec=0.1)
        goal = NavigateToPose.Goal()
        goal.pose.header.frame_id = "map"
        goal.pose.header.stamp = node.get_clock().now().to_msg()
        goal.pose.pose.position.x = -2.0
        goal.pose.pose.position.y = 0.5
        goal.pose.pose.orientation.w = 1.0
        pending = client.send_goal_async(goal)
        spin_until(pending.done)
        handle = pending.result()
        if not handle.accepted:
            raise RuntimeError("Nav2 rejected the simulation goal")
        result = handle.get_result_async()
        try:
            spin_until(result.done)
        except TimeoutError:
            handle.cancel_goal_async()
            raise
        report.update(
            action_status=result.result().status,
            status="succeeded" if result.result().status == 4 else "failed",
        )
    except Exception as error:
        report["error"] = str(error)
    finally:
        report.update(
            wall_duration_s=time.monotonic() - started, amcl_messages=len(localized), odometry=poses
        )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2) + "\n")
        node.destroy_node()
        rclpy.shutdown()
    print(json.dumps({k: v for k, v in report.items() if k != "odometry"}))
    raise SystemExit(0 if report["status"] == "succeeded" else 1)


if __name__ == "__main__":
    main()
