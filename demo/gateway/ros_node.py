"""Run inside a sourced ROS 2 environment; the core remains ROS-independent."""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import signal
import time
from functools import partial
from pathlib import Path

from demo.gateway.core import LiveGateway, deliver_forever, load_gateway_config
from demo.gateway.outbox import DurableOutbox
from demo.replayer.kafka import KafkaEnvelopePublisher


def finite(value):
    value = float(value)
    return value if math.isfinite(value) else None


def observations(message) -> tuple[int | None, dict]:
    """Extract bounded observable fields, never raw images/scans or ground truth."""
    header = getattr(message, "header", None)
    timestamp = (
        int(header.stamp.sec) * 1_000_000_000 + int(header.stamp.nanosec) if header else None
    )
    result = {}
    if header is not None:
        frame_id = str(getattr(header, "frame_id", ""))
        result["frame_id"] = frame_id if len(frame_id) <= 512 else ""
    pose = getattr(message, "pose", None)
    if pose is not None and hasattr(pose, "pose"):
        p = pose.pose
        q = p.orientation
        result.update(
            position_x=finite(p.position.x),
            position_y=finite(p.position.y),
            yaw=finite(math.atan2(2 * (q.w * q.z + q.x * q.y), 1 - 2 * (q.y * q.y + q.z * q.z))),
            position_covariance_x=finite(pose.covariance[0]),
            position_covariance_y=finite(pose.covariance[7]),
            heading_covariance=finite(pose.covariance[35]),
        )
    twist = getattr(message, "twist", None)
    if twist is not None and hasattr(twist, "twist"):
        result.update(
            linear_velocity_x=finite(twist.twist.linear.x),
            angular_velocity_z=finite(twist.twist.angular.z),
        )
    ranges = getattr(message, "ranges", None)
    if ranges is not None:
        valid = [
            float(r)
            for r in ranges
            if math.isfinite(r) and message.range_min <= r <= message.range_max
        ]
        result.update(
            scan_count=len(ranges),
            scan_valid_count=len(valid),
            scan_min_range_m=min(valid) if valid else None,
        )
    statuses = getattr(message, "status", None)
    if statuses is not None:
        result.update(
            diagnostic_count=len(statuses),
            diagnostic_max_level=max(
                (s.level[0] if isinstance(s.level, bytes) else int(s.level) for s in statuses),
                default=0,
            ),
        )
    return timestamp, result


async def run(args) -> int:
    import rclpy
    from rclpy.event_handler import SubscriptionEventCallbacks
    from rclpy.executors import SingleThreadedExecutor
    from rclpy.qos import DurabilityPolicy, HistoryPolicy, QoSProfile, ReliabilityPolicy
    from rclpy.signals import SignalHandlerOptions
    from rosidl_runtime_py.utilities import get_message

    config = load_gateway_config(args.config)
    outbox = DurableOutbox(
        args.outbox,
        max_bytes=args.max_pending_bytes,
        max_records=args.max_pending_records,
        max_database_bytes=args.max_database_bytes,
    )
    if args.new_session:
        outbox.reset_completed_session()
    gateway = LiveGateway(config, outbox)
    stop = asyncio.Event()
    stopping = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stopping.set)
    rclpy.init(signal_handler_options=SignalHandlerOptions.NO)
    node = rclpy.create_node("telemetry_gateway")
    executor = SingleThreadedExecutor()
    executor.add_node(node)

    def callback(topic, message):
        timestamp, attrs = observations(message)
        if not gateway.ingest(topic, source_timestamp_ns=timestamp, attributes=attrs):
            node.get_logger().error("Gateway outbox full: observation rejected and counted")

    if not gateway.session["closed"]:
        for topic in config.topics:

            def event_handler(event, *, name=topic.topic, kind="qos_incompatible"):
                count = int(getattr(event, "total_count_change", 1))
                gateway.qos_event(kind, name, count)

            node.create_subscription(
                get_message(topic.message_type),
                topic.topic,
                partial(callback, topic.topic),
                QoSProfile(
                    history=HistoryPolicy.KEEP_LAST,
                    depth=10,
                    reliability=(
                        ReliabilityPolicy.RELIABLE
                        if topic.reliability == "reliable"
                        else ReliabilityPolicy.BEST_EFFORT
                    ),
                    durability=DurabilityPolicy.VOLATILE,
                ),
                event_callbacks=SubscriptionEventCallbacks(incompatible_qos=event_handler),
            )

    def publisher_factory():
        return KafkaEnvelopePublisher(
            bootstrap_servers=args.bootstrap_servers, topic="telemetry.events.v1"
        )

    delivery = asyncio.create_task(deliver_forever(gateway, publisher_factory, stop))
    last_heartbeat = 0.0
    try:
        while not gateway.session["closed"] and not gateway.expired() and not stopping.is_set():
            executor.spin_once(timeout_sec=0)
            if time.monotonic() - last_heartbeat >= 1:
                gateway.heartbeat()
                last_heartbeat = time.monotonic()
            if delivery.done():
                await delivery
                raise RuntimeError("Gateway delivery stopped unexpectedly")
            await asyncio.sleep(0.001)
        gateway.finish()
        deadline = time.monotonic() + args.drain_timeout_s
        while outbox.stats()["pending_records"] and time.monotonic() < deadline:
            await asyncio.sleep(0.05)
        print(
            json.dumps(
                {"run_id": gateway.run_id, "closed": gateway.session["closed"], **outbox.stats()},
                sort_keys=True,
            ),
            flush=True,
        )
        return 0 if outbox.stats()["pending_records"] == 0 else 2
    finally:
        stop.set()
        delivery.cancel()
        try:
            await delivery
        except asyncio.CancelledError:
            pass
        executor.shutdown()
        node.destroy_node()
        rclpy.shutdown()
        outbox.close()


def main():
    parser = argparse.ArgumentParser(description="Durable live ROS 2 telemetry gateway")
    parser.add_argument("--config", type=Path, default=Path("configs/gateway.yaml"))
    parser.add_argument("--outbox", type=Path, default=Path("/state/gateway.sqlite"))
    parser.add_argument(
        "--bootstrap-servers", default=os.getenv("KAFKA_BOOTSTRAP_SERVERS", "kafka:9092")
    )
    parser.add_argument("--max-pending-bytes", type=int, default=8_000_000)
    parser.add_argument("--max-pending-records", type=int, default=10000)
    parser.add_argument("--max-database-bytes", type=int, default=32_000_000)
    parser.add_argument("--drain-timeout-s", type=float, default=30)
    parser.add_argument(
        "--new-session",
        action="store_true",
        help="Start a new identity only after the previous session is fully drained",
    )
    args = parser.parse_args()
    if not math.isfinite(args.drain_timeout_s) or args.drain_timeout_s <= 0:
        parser.error("Drain timeout must be finite and positive")
    raise SystemExit(asyncio.run(run(args)))


if __name__ == "__main__":
    main()
