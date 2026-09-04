from __future__ import annotations

from pathlib import Path

import pytest

from ros_telemetry_analytics import discovery
from ros_telemetry_analytics.discovery import discover_bags, inventory_frame

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


def test_bag_id_is_stable_when_a_slug_collision_is_added(tmp_path: Path) -> None:
    first = tmp_path / "camera one.bag"
    first.write_bytes(b"one")
    original_id = discover_bags([tmp_path])[0].bag_id

    (tmp_path / "camera_one.bag").write_bytes(b"two")
    sources = discover_bags([tmp_path])

    assert next(source.bag_id for source in sources if source.path == first) == original_id
    assert len({source.bag_id for source in sources}) == 2


def test_discovery_isolates_a_source_that_vanishes(tmp_path: Path, monkeypatch) -> None:
    good = tmp_path / "good.bag"
    vanished = tmp_path / "vanished.bag"
    good.write_bytes(b"good")
    vanished.write_bytes(b"gone")
    original_fingerprint = discovery._fingerprint

    def flaky_fingerprint(path: Path):
        if path == vanished:
            raise FileNotFoundError(path)
        return original_fingerprint(path)

    errors = []
    monkeypatch.setattr(discovery, "_fingerprint", flaky_fingerprint)
    sources = discover_bags([tmp_path], on_error=lambda path, exc: errors.append((path, exc)))

    assert [source.path for source in sources] == [good]
    assert errors[0][0] == vanished


@pytest.mark.parametrize("ros2_directory", [False, True])
def test_discovery_surfaces_directory_traversal_errors(
    tmp_path: Path, monkeypatch, ros2_directory: bool
) -> None:
    blocked = tmp_path / "blocked"
    blocked.mkdir()
    if ros2_directory:
        (blocked / "metadata.yaml").write_text("{}", encoding="utf-8")
    (blocked / "recording.db3").write_bytes(b"unreadable recording")
    good = tmp_path / "good.bag"
    good.write_bytes(b"healthy recording")
    real_scandir = discovery.os.scandir

    def flaky_scandir(path):
        if not isinstance(path, int) and Path(path) == blocked:
            raise PermissionError(13, "temporarily inaccessible", str(path))
        return real_scandir(path)

    monkeypatch.setattr(discovery.os, "scandir", flaky_scandir)
    with pytest.raises(PermissionError, match="temporarily inaccessible"):
        discover_bags([tmp_path])

    errors = []
    sources = discover_bags([tmp_path], on_error=lambda path, exc: errors.append((path, exc)))
    assert [source.path for source in sources] == [good]
    assert len(errors) == 1
    assert errors[0][0] == blocked
    assert isinstance(errors[0][1], PermissionError)


def test_discovery_isolates_missing_root_when_error_handler_is_supplied(tmp_path: Path) -> None:
    missing = tmp_path / "missing"
    good = tmp_path / "good.bag"
    good.write_bytes(b"healthy recording")
    errors = []

    sources = discover_bags([missing, good], on_error=lambda path, exc: errors.append((path, exc)))

    assert [source.path for source in sources] == [good]
    assert len(errors) == 1
    assert errors[0][0] == missing
    assert isinstance(errors[0][1], FileNotFoundError)
