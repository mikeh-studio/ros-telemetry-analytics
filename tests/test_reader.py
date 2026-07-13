from __future__ import annotations

from pathlib import Path

import polars as pl
import pytest
from rosbags.rosbag1 import Writer as Rosbag1Writer
from rosbags.rosbag2 import StoragePlugin
from rosbags.typesys import Stores, get_typestore

from isaac_telemetry.discovery import discover_bags
from isaac_telemetry.reader import scan_bag

MESSAGES = [
    ("/camera/left/image_raw", "sensor_msgs/msg/Image", 1_000_000),
    ("/camera/right/image_raw", "sensor_msgs/msg/Image", 2_000_000),
    ("/tf", "tf2_msgs/msg/TFMessage", 3_000_000),
]


@pytest.mark.parametrize(
    ("storage_plugin", "suffix"),
    [(StoragePlugin.SQLITE3, ".db3"), (StoragePlugin.MCAP, ".mcap")],
)
def test_scan_supports_ros2_directory_and_standalone_file(
    tmp_path: Path,
    write_bag,
    storage_plugin: StoragePlugin,
    suffix: str,
) -> None:
    bag_dir = write_bag(tmp_path / "bag", MESSAGES, storage_plugin)
    directory_source = discover_bags([bag_dir])[0]
    directory_output = tmp_path / "directory-output"

    result = scan_bag(directory_source, directory_output, batch_size=2)

    assert result == {"message_count": 3, "topic_count": 3}
    assert pl.read_parquet(directory_output / "message_index.parquet").height == 3

    bag_file = next(bag_dir.glob(f"*{suffix}"))
    standalone_source = discover_bags([bag_file])[0]
    standalone_output = tmp_path / "standalone-output"
    standalone_result = scan_bag(standalone_source, standalone_output, batch_size=2)

    assert standalone_result == result
    assert pl.read_parquet(standalone_output / "topic_manifest.parquet")["message_count"].sum() == 3


def test_scan_supports_ros1_bag(tmp_path: Path) -> None:
    bag_path = tmp_path / "legacy.bag"
    typestore = get_typestore(Stores.ROS1_NOETIC)
    with Rosbag1Writer(bag_path) as writer:
        connection = writer.add_connection(
            "/camera/image_raw",
            "sensor_msgs/msg/Image",
            typestore=typestore,
        )
        writer.write(connection, 1_000_000, b"raw-message")

    source = discover_bags([bag_path])[0]
    result = scan_bag(source, tmp_path / "ros1-output", batch_size=10)

    assert source.format == "rosbag1"
    assert result == {"message_count": 1, "topic_count": 1}


def test_scan_preserves_zero_message_connections(tmp_path: Path, write_bag) -> None:
    bag_dir = write_bag(
        tmp_path / "bag",
        MESSAGES[:1],
        empty_topics=[("/camera/right/image_raw", "sensor_msgs/msg/Image")],
    )

    source = discover_bags([bag_dir])[0]
    output = tmp_path / "output"
    result = scan_bag(source, output, batch_size=10)
    manifest = pl.read_parquet(output / "topic_manifest.parquet")

    assert result == {"message_count": 1, "topic_count": 2}
    right = manifest.filter(pl.col("topic") == "/camera/right/image_raw").row(0, named=True)
    assert right["message_count"] == 0
    assert right["first_timestamp_ns"] is None
