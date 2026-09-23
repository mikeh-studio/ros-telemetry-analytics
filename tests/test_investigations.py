from __future__ import annotations

import base64
import json
import os
import struct
import subprocess
import sys
import zlib
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
import yaml
from rosbags.rosbag2 import StoragePlugin
from rosbags.typesys import Stores, get_typestore

from ros_telemetry_analytics import investigations as evidence


def image(stamp: int, frame: str = "camera"):
    types = get_typestore(Stores.ROS2_HUMBLE).types
    return types["sensor_msgs/msg/Image"](
        types["std_msgs/msg/Header"](types["builtin_interfaces/msg/Time"](stamp, 0), frame),
        2,
        2,
        "mono8",
        0,
        2,
        np.array([10, 30, 50, 90], dtype=np.uint8),
    )


@pytest.fixture
def prepared(tmp_path, write_serialized_bag):
    bag = write_serialized_bag(
        tmp_path / "recording",
        [("/camera", image(i, str(1000 + i)), i * 1_000_000_000) for i in range(5)],
        storage_plugin=StoragePlugin.MCAP,
    )
    source = next(bag.glob("*.mcap"))
    configs = tmp_path / "configs"
    configs.mkdir()
    (configs / "profile.yaml").write_text(
        "pipeline:\n  project_root: ..\nanalytics:\n  domain_analyzers:\n    enabled: true\n"
    )
    spec = {
        "name": "Test recording",
        "input": str(source.relative_to(tmp_path)),
        "profile": "configs/profile.yaml",
        "role": "real_recording",
        "purpose": "test",
        "source": "https://example.test/data",
        "license": "test",
        "image_frame_semantics": "exposure_ns",
    }
    (configs / "investigations.yaml").write_text(yaml.safe_dump({"datasets": {"test": spec}}))
    output = tmp_path / "evidence"
    metadata = evidence.build_bundle(tmp_path, "test", output)
    return tmp_path, output, metadata, source


def test_source_to_preview_and_interval_reconcile(prepared):
    root, output, metadata, _ = prepared
    directory, loaded = evidence.load_bundle(root, output, "test")
    assert loaded["message_count"] == 5
    assert loaded["verified_previews"] == loaded["preview_count"] > 0
    assert len(loaded["header_profile"]) == 1  # Exposure values must not fragment the clock check.
    public = evidence.public_metadata(directory, loaded)
    assert public["cases"] == []
    assert "source_input" not in public
    interval = evidence.interval(directory, metadata, 0, 4)
    series = next(s for s in interval["series"] if s["field"] == "mean_intensity")
    assert sum(p["count"] for p in series["points"]) == 5
    assert max(p["max"] for p in series["points"] if p["count"]) == 45
    assert series["frame"] == "header.frame_id is exposure (ns)"
    assert all(isinstance(p["timestamp_ns"], str) for p in interval["previews"])
    assert evidence.collection(root, output)["datasets"][0]["status"] == "ready"


def test_stale_and_cross_dataset_identity_rejected(prepared):
    root, output, metadata, source = prepared
    with pytest.raises(KeyError):
        evidence.load_bundle(root, output, "../test")
    with pytest.raises(ValueError, match="Analysis changed"):
        evidence.load_bundle(root, output, "test", "f" * 32)
    directory, _ = evidence.load_bundle(root, output, "test")
    changed = {**metadata, "analysis_path": "../../outside"}
    evidence.write_json(directory / "metadata.json", changed)
    with pytest.raises(ValueError, match="location"):
        evidence.load_bundle(root, output, "test")
    evidence.write_json(directory / "metadata.json", {**metadata, "dataset_id": "other"})
    with pytest.raises(ValueError, match="identity mismatch"):
        evidence.load_bundle(root, output, "test")
    evidence.write_json(directory / "metadata.json", metadata)
    stat = source.stat()
    with source.open("r+b") as stream:
        stream.seek(-1, 2)
        original = stream.read(1)
        stream.seek(-1, 2)
        stream.write(bytes([original[0] ^ 1]))
    os.utime(source, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    with pytest.raises(ValueError, match="Source bytes changed"):
        evidence.load_bundle(root, output, "test")
    assert evidence.collection(root, output)["datasets"][0]["status"] == "stale"


def test_annotations_bound_to_analysis_and_intervals_validated(prepared):
    root, output, metadata, _ = prepared
    directory, _ = evidence.load_bundle(root, output, "test")
    evidence.write_json(
        directory / "annotations.json", {"analysis_id": "old", "cases": [{"id": "old"}]}
    )
    assert evidence.public_metadata(directory, metadata)["cases"] == []
    evidence.write_json(
        directory / "annotations.json",
        {"analysis_id": metadata["analysis_id"], "cases": [{"id": "new"}]},
    )
    assert evidence.public_metadata(directory, metadata)["cases"] == [{"id": "new"}]
    for lo, hi in [(-1, 1), (1, 1), (0, 5), (0, float("nan"))]:
        with pytest.raises(ValueError, match="Interval"):
            evidence.interval(directory, metadata, lo, hi)
    with pytest.raises(ValueError, match="topic"):
        evidence.interval(directory, metadata, 0, 4, "/missing")


def test_buckets_preserve_short_spikes_and_empty_time():
    points = evidence.bounded_points([0, 1, 2, 9_000_000_000], [1, 99, 1, 3], 0, 0, 10, 10)
    assert points[0] == {"t": 0, "end_s": 1, "min": 1, "max": 99, "value": 101 / 3, "count": 3}
    assert points[1]["count"] == 0 and points[1]["value"] is None
    assert points[9]["max"] == 3
    assert evidence.bounded_points([], [], 0, 0, 1) == []


def decode_png(uri):
    raw = base64.b64decode(uri.split(",")[1])
    assert raw[:8] == b"\x89PNG\r\n\x1a\n"
    offset = 8
    chunks = {}
    while offset < len(raw):
        size = struct.unpack(">I", raw[offset : offset + 4])[0]
        chunks[raw[offset + 4 : offset + 8]] = raw[offset + 8 : offset + 8 + size]
        offset += size + 12
    return chunks[b"IHDR"], zlib.decompress(chunks[b"IDAT"])


def test_png_stride_channel_order_depth_and_bounds():
    message = SimpleNamespace(
        encoding="bgr8",
        height=1,
        width=2,
        step=8,
        data=np.array([1, 2, 3, 4, 5, 6, 88, 99], dtype=np.uint8),
    )
    _, pixels = decode_png(evidence.png_preview(message))
    assert pixels == bytes([0, 3, 2, 1, 6, 5, 4])
    message.encoding = "mono16"
    message.width = 2
    message.step = 4
    message.is_bigendian = 1
    message.data = np.array([0, 65535], dtype=">u2").view(np.uint8)
    _, pixels = decode_png(evidence.png_preview(message))
    assert pixels == bytes([0, 0, 255])
    message.encoding = "32FC1"
    message.is_bigendian = 0
    message.step = 8
    message.data = np.array([float("nan"), 5], dtype="<f4").view(np.uint8)
    assert decode_png(evidence.png_preview(message))[1] == bytes([0, 0, 255])
    message.encoding = "unsupported"
    assert evidence.png_preview(message) is None
    message.encoding = "mono8"
    message.width = 513
    message.height = 257
    message.step = 513
    message.data = np.zeros(513 * 257, dtype=np.uint8)
    header, _ = decode_png(evidence.png_preview(message))
    assert max(struct.unpack(">II", header[:8])) <= 256


def test_missing_source_and_recipe_changes(prepared):
    root, output, _, source = prepared
    profile = root / "configs/profile.yaml"
    profile.write_text(profile.read_text() + "\n# changed\n")
    with pytest.raises(ValueError, match="stale"):
        evidence.load_bundle(root, output, "test")
    source.unlink()
    assert evidence.build_bundle(root, "test", output)["status"] == "not_installed"


def test_isolated_worker_publishes_loadable_recording(prepared):
    root, output, old, _ = prepared
    process = subprocess.run(
        [
            sys.executable,
            "-m",
            "demo.api.evidence_worker",
            "--root",
            str(root),
            "--output",
            str(output),
            "--dataset",
            "test",
        ],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        check=False,
    )
    assert process.returncode == 0, process.stderr
    result = json.loads(process.stdout.splitlines()[-1])
    assert result["status"] == "completed"
    directory, metadata = evidence.load_bundle(root, output, "test")
    assert metadata["analysis_id"] != old["analysis_id"]
    assert metadata["message_count"] == 5
    assert evidence.interval(directory, metadata, 0, 4)["previews"]
    assert (output / "test" / old["analysis_id"]).exists()
    assert not list((output / "test").glob(".rebuild-*"))
