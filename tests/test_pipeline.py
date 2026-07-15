from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import polars as pl
import pytest
from rosbags.rosbag2 import StoragePlugin

from ros_telemetry_analytics import pipeline
from ros_telemetry_analytics.config import PipelineConfig
from ros_telemetry_analytics.pipeline import run_pipeline

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
        "anomaly_events.parquet",
        "bag_report.md",
        "domain_metrics.parquet",
        "domain_summary.json",
        "message_index.parquet",
        "relationship_health.parquet",
        "topic_manifest.parquet",
        "topic_health.parquet",
        "vslam_quality.parquet",
        "summary.json",
    }.issubset(path.name for path in bag_output.iterdir())
    summary = json.loads((bag_output / "summary.json").read_text())
    assert summary["pipeline_status"] == "success"
    assert summary["analytics_fingerprint"]
    assert summary["domain_analysis"]["status"] == "warn"
    assert pl.read_parquet(
        bag_output / "domain_records" / "extraction_errors.parquet"
    ).height == len(MESSAGES)
    assert (bag_output / "bag_report.md").exists()
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
    relationships = pl.read_parquet(
        tmp_path / "output" / "bags" / bag_id / "relationship_health.parquet"
    )
    stereo = quality.filter(pl.col("check_type") == "stereo_sync")
    assert stereo.height == 1
    assert stereo.row(0, named=True)["paired_message_count"] == 2
    assert relationships.row(0, named=True)["source"] == "automatic"


def test_zero_message_connection_is_reported_as_error(
    tmp_path: Path,
    write_bag,
    analytics_config,
) -> None:
    write_bag(
        tmp_path / "input" / "dead-camera",
        MESSAGES[::2],
        empty_topics=[("/stereo/right/image_raw", "sensor_msgs/msg/Image")],
    )

    manifest = run_pipeline(_config(tmp_path, analytics_config))
    bag_id = manifest["results"][0]["bag_id"]
    bag_output = tmp_path / "output" / "bags" / bag_id
    health = pl.read_parquet(bag_output / "topic_health.parquet")
    summary = json.loads((bag_output / "summary.json").read_text())

    right = health.filter(pl.col("topic") == "/stereo/right/image_raw").row(0, named=True)
    assert right["message_count"] == 0
    assert right["status"] == "error"
    assert summary["health_status"] == "error"


def test_missing_cached_artifact_forces_reprocessing(
    tmp_path: Path,
    write_bag,
    analytics_config,
) -> None:
    write_bag(tmp_path / "input" / "good", MESSAGES)
    config = _config(tmp_path, analytics_config)
    first = run_pipeline(config)
    bag_id = first["results"][0]["bag_id"]
    (config.output_root / "bags" / bag_id / "relationship_health.parquet").unlink()

    second = run_pipeline(config)

    assert second["processed_count"] == 1
    assert second["skipped_count"] == 0


def test_fail_fast_marks_remaining_sources_not_attempted(
    tmp_path: Path,
    write_bag,
    analytics_config,
) -> None:
    input_root = tmp_path / "input"
    (input_root / "a-bad.mcap").parent.mkdir(parents=True)
    (input_root / "a-bad.mcap").write_bytes(b"not-an-mcap")
    write_bag(input_root / "z-good", MESSAGES)

    manifest = run_pipeline(_config(tmp_path, analytics_config), fail_fast=True)

    assert manifest["failed_count"] == 1
    assert manifest["not_attempted_count"] == 1
    assert len(manifest["results"]) == manifest["discovered_count"]


def test_pipeline_recovers_backups_and_removes_stale_outputs(
    tmp_path: Path,
    write_bag,
    analytics_config,
) -> None:
    config = _config(tmp_path, analytics_config)
    backup = config.output_root / "bags" / ".recovered-backup-deadbeef"
    backup.mkdir(parents=True)
    (backup / "marker").write_text("backup", encoding="utf-8")
    stale = config.output_root / "bags" / "stale"
    stale.mkdir()
    (config.output_root / ".staging" / "abandoned").mkdir(parents=True)
    write_bag(tmp_path / "input" / "good", MESSAGES)

    run_pipeline(config)

    assert not (config.output_root / ".staging" / "abandoned").exists()
    assert not (config.output_root / "bags" / "recovered").exists()
    assert not stale.exists()


def test_publish_stage_restores_backup_when_replace_fails(tmp_path: Path, monkeypatch) -> None:
    target = tmp_path / "target"
    target.mkdir()
    (target / "old").write_text("old", encoding="utf-8")
    stage = tmp_path / "stage"
    stage.mkdir()
    (stage / "new").write_text("new", encoding="utf-8")
    real_replace = pipeline.os.replace

    def fail_stage_replace(source, destination):
        if source == stage:
            raise OSError("publish failed")
        return real_replace(source, destination)

    monkeypatch.setattr(pipeline.os, "replace", fail_stage_replace)
    with pytest.raises(OSError, match="publish failed"):
        pipeline._publish_stage(stage, target)

    assert (target / "old").read_text() == "old"


def test_empty_bag_has_error_health(tmp_path: Path, write_bag, analytics_config) -> None:
    write_bag(tmp_path / "input" / "empty", [])

    manifest = run_pipeline(_config(tmp_path, analytics_config))

    assert manifest["processed_count"] == 1
    assert manifest["results"][0]["health_status"] == "error"


def test_lock_contention_preserves_holder_diagnostics(tmp_path: Path) -> None:
    output_root = tmp_path / "output"
    with pipeline._pipeline_lock(output_root):
        diagnostics = (output_root / ".pipeline.lock").read_text()
        with pytest.raises(RuntimeError, match="Another pipeline process"):
            with pipeline._pipeline_lock(output_root):
                raise AssertionError("second lock unexpectedly acquired")
        assert (output_root / ".pipeline.lock").read_text() == diagnostics


def test_atomic_json_removes_temp_file_when_serialization_fails(
    tmp_path: Path,
    monkeypatch,
) -> None:
    def fail_dump(*_args, **_kwargs):
        raise TypeError("not serializable")

    monkeypatch.setattr(pipeline.json, "dump", fail_dump)
    with pytest.raises(TypeError, match="not serializable"):
        pipeline._write_json(tmp_path / "output.json", {"bad": object()})

    assert list(tmp_path.iterdir()) == []
