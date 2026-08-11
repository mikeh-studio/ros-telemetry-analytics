from __future__ import annotations

import argparse
import shutil
import tempfile
from pathlib import Path

import numpy as np
from rosbags.rosbag2 import StoragePlugin, Writer
from rosbags.typesys import Stores, get_typestore

from demo.common.config import StreamingConfig, load_streaming_config

SOURCE_START_NS = 1_700_000_000_000_000_000


def _serialized_messages() -> dict[str, tuple[str, bytes]]:
    typestore = get_typestore(Stores.ROS2_HUMBLE)
    types = typestore.types
    Time = types["builtin_interfaces/msg/Time"]
    Header = types["std_msgs/msg/Header"]
    Vector3 = types["geometry_msgs/msg/Vector3"]
    Point = types["geometry_msgs/msg/Point"]
    Quaternion = types["geometry_msgs/msg/Quaternion"]
    Pose = types["geometry_msgs/msg/Pose"]
    PoseWithCovariance = types["geometry_msgs/msg/PoseWithCovariance"]
    Twist = types["geometry_msgs/msg/Twist"]
    TwistWithCovariance = types["geometry_msgs/msg/TwistWithCovariance"]
    Odometry = types["nav_msgs/msg/Odometry"]
    Imu = types["sensor_msgs/msg/Imu"]
    Image = types["sensor_msgs/msg/Image"]
    DiagnosticArray = types["diagnostic_msgs/msg/DiagnosticArray"]
    DiagnosticStatus = types["diagnostic_msgs/msg/DiagnosticStatus"]

    header = Header(Time(0, 0), "base_link")
    zero_vector = Vector3(0.0, 0.0, 0.0)
    identity = Quaternion(0.0, 0.0, 0.0, 1.0)
    covariance_36 = np.zeros(36, dtype=np.float64)
    covariance_9 = np.zeros(9, dtype=np.float64)
    payloads = {
        "/camera/image_raw": Image(
            Header(Time(0, 0), "camera"),
            1,
            1,
            "mono8",
            0,
            1,
            np.array([127], dtype=np.uint8),
        ),
        "/imu/data": Imu(
            Header(Time(0, 0), "imu_link"),
            identity,
            covariance_9,
            zero_vector,
            covariance_9,
            Vector3(0.0, 0.0, 9.81),
            covariance_9,
        ),
        "/odom": Odometry(
            header,
            "base_link",
            PoseWithCovariance(Pose(Point(0.0, 0.0, 0.0), identity), covariance_36),
            TwistWithCovariance(Twist(zero_vector, zero_vector), covariance_36),
        ),
        "/diagnostics": DiagnosticArray(
            header,
            [DiagnosticStatus(0, "robot", "healthy", "robot-17", [])],
        ),
    }
    return {
        topic: (
            message.__msgtype__,
            bytes(typestore.serialize_cdr(message, message.__msgtype__)),
        )
        for topic, message in payloads.items()
    }


def generate_fixture(output_path: Path, config: StreamingConfig, *, force: bool = False) -> Path:
    output_path = output_path.expanduser().resolve()
    if output_path.exists() and not force:
        return output_path
    output_path.parent.mkdir(parents=True, exist_ok=True)
    payloads = _serialized_messages()
    expected = config.analytics.expected_topics
    for topic_spec in expected:
        if topic_spec.topic not in payloads:
            raise ValueError(f"Fixture generator has no payload for {topic_spec.topic}")

    scheduled: list[tuple[int, str]] = []
    for topic_spec in expected:
        count = int(config.demo.duration_s * topic_spec.expected_rate_hz)
        scheduled.extend(
            (
                SOURCE_START_NS + round(index * 1_000_000_000 / topic_spec.expected_rate_hz),
                topic_spec.topic,
            )
            for index in range(count)
        )
    scheduled.sort(key=lambda item: (item[0], item[1]))

    with tempfile.TemporaryDirectory(prefix="flight-deck-fixture-") as temp_dir:
        bag_dir = Path(temp_dir) / "warehouse_run_17"
        typestore = get_typestore(Stores.ROS2_HUMBLE)
        with Writer(bag_dir, version=9, storage_plugin=StoragePlugin.MCAP) as writer:
            connections = {
                topic: writer.add_connection(topic, message_type, typestore=typestore)
                for topic, (message_type, _raw) in payloads.items()
            }
            for timestamp_ns, topic in scheduled:
                writer.write(connections[topic], timestamp_ns, payloads[topic][1])
        generated = next(bag_dir.glob("*.mcap"))
        temporary = output_path.with_suffix(f"{output_path.suffix}.tmp")
        shutil.copyfile(generated, temporary)
        temporary.replace(output_path)
    return output_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate the Flight Deck MCAP fixture")
    parser.add_argument("--config", type=Path, default=Path("configs/streaming_demo.yaml"))
    parser.add_argument("--output", type=Path)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    config = load_streaming_config(args.config)
    output = args.output or config.demo.fixture_path
    generated = generate_fixture(output, config, force=args.force)
    print(generated)


if __name__ == "__main__":
    main()
