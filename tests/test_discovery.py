from __future__ import annotations

from pathlib import Path

import pytest

from isaac_telemetry.discovery import discover_bags, inventory_frame

MESSAGES = [
    ("/camera/left/image_raw", "sensor_msgs/msg/Image", 1),
    ("/camera/right/image_raw", "sensor_msgs/msg/Image", 2),
]


def test_discovery_returns_one_source_per_ros2_directory_and_excludes_downloads(
    tmp_path: Path,
    write_bag,
) -> None:
    write_bag(tmp_path / "bags" / "primary", MESSAGES)
    write_bag(tmp_path / "downloads" / "duplicate", MESSAGES)
    standalone = tmp_path / "recording.mcap"
    standalone.write_bytes(b"placeholder")

    sources = discover_bags([tmp_path], frozenset({"downloads"}))

    assert [source.path.name for source in sources] == ["primary", "recording.mcap"]
    assert len({source.bag_id for source in sources}) == 2
    assert inventory_frame(sources).height == 2


def test_discovery_deduplicates_overlapping_roots(tmp_path: Path, write_bag) -> None:
    bag = write_bag(tmp_path / "bags" / "primary", MESSAGES)
    sources = discover_bags([tmp_path, bag])
    assert len(sources) == 1


def test_discovery_validates_inputs(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        discover_bags([tmp_path / "missing"])

    unsupported = tmp_path / "input.txt"
    unsupported.write_text("not a bag", encoding="utf-8")
    with pytest.raises(ValueError, match="Unsupported"):
        discover_bags([unsupported])
