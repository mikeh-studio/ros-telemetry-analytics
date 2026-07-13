from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import polars as pl
import pytest
from rosbags.rosbag2 import StoragePlugin

from isaac_telemetry.config import PipelineConfig
from isaac_telemetry.pipeline import run_pipeline

MESSAGES = [
    ("/stereo/left/image_raw", "sensor_msgs/msg/Image", 0),
    ("/stereo/right/image_raw", "sensor_msgs/msg/Image", 1_000_000),
    ("/stereo/left/image_raw", "sensor_msgs/msg/Image", 33_000_000),
    ("/stereo/right/image_raw", "sensor_msgs/msg/Image", 34_000_000),
]


def _config(tmp_path: Path, analytics_config) -> PipelineConfig:
    return PipelineConfig(
        input_roots=(tmp_path / "input",),
        output_root=tmp_path / "output",
        excluded_directory_names=frozenset({"downloads"}),
        parquet_batch_size=2,
        analytics=analytics_config,
    )


def test_pipeline_is_idempotent_and_publishes_complete_outputs(
    tmp_path: Path,
    write_bag,
    analytics_config,
) -> None:
    write_bag(tmp_path / "input" / "good", MESSAGES)
    config = _config(tmp_path, analytics_config)

    first = run_pipeline(config)
    second = run_pipeline(config)
    changed_config = replace(
        config,
        analytics=replace(config.analytics, stereo_skew_warn_ns=2_000_000),
    )
    after_config_change = run_pipeline(changed_config)

    assert first["processed_count"] == 1
    assert first["failed_count"] == 0
    assert second["skipped_count"] == 1
    assert after_config_change["processed_count"] == 1
    bag_id = first["results"][0]["bag_id"]
    bag_output = config.output_root / "bags" / bag_id
    assert {
        "message_index.parquet",
        "topic_manifest.parquet",
        "topic_health.parquet",
        "vslam_quality.parquet",
        "summary.json",
    }.issubset(path.name for path in bag_output.iterdir())
    assert json.loads((bag_output / "summary.json").read_text())["pipeline_status"] == "success"
    assert json.loads((bag_output / "summary.json").read_text())["analytics_fingerprint"]
    assert (config.output_root / "latest_report.md").exists()


def test_pipeline_isolates_bad_inputs(
    tmp_path: Path,
    write_bag,
    analytics_config,
) -> None:
    input_root = tmp_path / "input"
    write_bag(input_root / "good", MESSAGES)
    (input_root / "bad.mcap").write_bytes(b"not-an-mcap")

    manifest = run_pipeline(_config(tmp_path, analytics_config))

    assert manifest["discovered_count"] == 2
    assert manifest["processed_count"] == 1
    assert manifest["failed_count"] == 1
    failure = next(result for result in manifest["results"] if result["status"] == "failed")
    assert failure["error_type"]
    assert failure["error_message"]


@pytest.mark.parametrize("storage_plugin", [StoragePlugin.SQLITE3, StoragePlugin.MCAP])
def test_ros2_stereo_pipeline_end_to_end(
    tmp_path: Path,
    write_bag,
    analytics_config,
    storage_plugin: StoragePlugin,
) -> None:
    write_bag(tmp_path / "input" / "stereo", MESSAGES, storage_plugin)

    manifest = run_pipeline(_config(tmp_path, analytics_config))

    assert manifest["processed_count"] == 1
    bag_id = manifest["results"][0]["bag_id"]
    quality = pl.read_parquet(tmp_path / "output" / "bags" / bag_id / "vslam_quality.parquet")
    stereo = quality.filter(pl.col("check_type") == "stereo_sync")
    assert stereo.height == 1
    assert stereo.row(0, named=True)["paired_message_count"] == 2
