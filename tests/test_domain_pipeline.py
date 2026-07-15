from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import polars as pl
import pytest
from rosbags.typesys import Stores, get_typestore

from ros_telemetry_analytics.config import AnalyticsConfig, PipelineConfig
from ros_telemetry_analytics.pipeline import run_pipeline


def _messages() -> list[tuple[str, object, int]]:
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
    Transform = types["geometry_msgs/msg/Transform"]
    TransformStamped = types["geometry_msgs/msg/TransformStamped"]
    TFMessage = types["tf2_msgs/msg/TFMessage"]
    KeyValue = types["diagnostic_msgs/msg/KeyValue"]
    DiagnosticStatus = types["diagnostic_msgs/msg/DiagnosticStatus"]
    DiagnosticArray = types["diagnostic_msgs/msg/DiagnosticArray"]
    Image = types["sensor_msgs/msg/Image"]

    def header(timestamp_ns: int, frame_id: str):
        return Header(Time(timestamp_ns // 1_000_000_000, timestamp_ns % 1_000_000_000), frame_id)

    zero_vector = Vector3(0.0, 0.0, 0.0)
    identity = Quaternion(0.0, 0.0, 0.0, 1.0)
    covariance_36 = np.zeros(36, dtype=np.float64)
    covariance_9 = np.zeros(9, dtype=np.float64)

    odometry = []
    for index, position_x in enumerate((0.0, 2.0)):
        timestamp = index * 1_000_000_000
        odometry.append(
            (
                "/odom",
                Odometry(
                    header(timestamp, "map"),
                    "base_link",
                    PoseWithCovariance(
                        Pose(Point(position_x, 0.0, 0.0), identity),
                        covariance_36,
                    ),
                    TwistWithCovariance(Twist(zero_vector, zero_vector), covariance_36),
                ),
                timestamp,
            )
        )

    imu = Imu(
        header(0, "imu_link"),
        identity,
        covariance_9,
        Vector3(11.0, 0.0, 0.0),
        covariance_9,
        Vector3(35.0, 0.0, 0.0),
        covariance_9,
    )
    command = Twist(Vector3(1.0, 0.0, 0.0), zero_vector)
    transform = TransformStamped(
        header(0, "map"),
        "base_link",
        Transform(Vector3(0.0, 0.0, 0.0), identity),
    )
    diagnostics = DiagnosticArray(
        header(0, "base_link"),
        [
            DiagnosticStatus(
                1,
                "motor",
                "warm",
                "motor-1",
                [KeyValue("temperature_c", "80")],
            )
        ],
    )
    pixels = np.array([10, 10, 10, 10], dtype=np.uint8)
    image = Image(header(0, "camera"), 2, 2, "mono8", 0, 2, pixels)
    mono16_pixels = np.array([0, 65_535, 32_768, 16_384], dtype="<u2").view(np.uint8)
    mono16_image = Image(header(0, "camera"), 2, 2, "mono16", 0, 4, mono16_pixels)
    depth_pixels = np.array([1.0, 2.0, np.nan, 0.0], dtype="<f4").view(np.uint8)
    depth_image = Image(header(0, "camera"), 2, 2, "32FC1", 0, 8, depth_pixels)
    return [
        *odometry,
        ("/imu", imu, 0),
        ("/cmd_vel", command, 0),
        ("/tf", TFMessage([transform]), 0),
        ("/diagnostics", diagnostics, 0),
        ("/camera/image_raw", image, 0),
        ("/camera/image_raw", image, 100_000_000),
        ("/camera/mono16", mono16_image, 0),
        ("/camera/depth", depth_image, 0),
    ]


def test_pipeline_deserializes_payloads_and_publishes_domain_summary(
    tmp_path: Path,
    write_serialized_bag,
) -> None:
    write_serialized_bag(tmp_path / "input" / "navigation", _messages())
    config = PipelineConfig(
        input_roots=(tmp_path / "input",),
        output_root=tmp_path / "output",
        excluded_directory_names=frozenset(),
        parquet_batch_size=2,
        analytics=AnalyticsConfig(rate_rules=()),
    )

    manifest = run_pipeline(config)

    assert manifest["processed_count"] == 1
    bag_id = manifest["results"][0]["bag_id"]
    bag_output = config.output_root / "bags" / bag_id
    for dataset in ("odometry", "imu", "commands", "transforms", "diagnostics", "images"):
        assert pl.read_parquet(bag_output / "domain_records" / f"{dataset}.parquet").height
    assert pl.read_parquet(bag_output / "domain_records" / "extraction_errors.parquet").is_empty()

    images = pl.read_parquet(bag_output / "domain_records" / "images.parquet")
    mono16 = images.filter(pl.col("topic") == "/camera/mono16").row(0, named=True)
    assert mono16["mean_intensity"] == pytest.approx(111.5625, abs=0.01)
    assert mono16["sharpness_score"] is not None
    depth = images.filter(pl.col("topic") == "/camera/depth").row(0, named=True)
    assert depth["mean_depth_m"] == pytest.approx(1.5)
    assert depth["valid_pixel_fraction"] == pytest.approx(0.5)

    summary = json.loads((bag_output / "summary.json").read_text())
    events = pl.read_parquet(bag_output / "anomaly_events.parquet")
    assert summary["domain_analysis"]["status"] == "warn"
    assert {
        "command_without_motion",
        "diagnostic_status",
        "duplicate_frames",
        "high_acceleration",
        "high_angular_velocity",
        "pose_jump",
    }.issubset(set(events.get_column("event_type")))
    report = (bag_output / "bag_report.md").read_text()
    assert "# Robot Bag Analysis" in report
    assert "distance_traveled" in report
