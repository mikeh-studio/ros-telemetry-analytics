from __future__ import annotations

import hashlib
import json
from pathlib import Path

from demo.api.store import ProjectionStore


def _metric(
    metric_id: str, revision: int, timestamp: int, metric_type: str = "topic_window"
) -> dict:
    return {
        "schema_version": 1,
        "metric_id": hashlib.sha256(metric_id.encode()).hexdigest(),
        "metric_type": metric_type,
        "run_id": "run-1",
        "robot_id": "robot-17",
        "topic": "/odom" if metric_type != "run_status" else None,
        "window_start_ms": timestamp - 10_000,
        "window_end_ms": timestamp,
        "revision": revision,
        "stream_timestamp_ms": timestamp,
        "payload": {"status": "ok", "message_count": 200},
    }


def test_projection_is_idempotent_and_keeps_highest_revision(tmp_path: Path) -> None:
    store = ProjectionStore(tmp_path / "projection.db", tmp_path / "output")
    original = _metric("metric-1", 0, 10_000)
    corrected = _metric("metric-1-revision-1", 1, 10_000)
    corrected["payload"]["message_count"] = 201

    assert store.project(
        stream_kind="metric",
        payload=original,
        kafka_topic="telemetry.metrics.v1",
        kafka_partition=0,
        kafka_offset=5,
    )
    assert not store.project(
        stream_kind="metric",
        payload=original,
        kafka_topic="telemetry.metrics.v1",
        kafka_partition=0,
        kafka_offset=5,
    )
    assert store.project(
        stream_kind="metric",
        payload=corrected,
        kafka_topic="telemetry.metrics.v1",
        kafka_partition=0,
        kafka_offset=6,
    )

    snapshot = store.snapshot("run-1")
    assert snapshot["topics"][0]["revision"] == 1
    assert snapshot["topics"][0]["payload"]["message_count"] == 201
    assert snapshot["consumer_offsets"][0]["next_offset"] == 7


def test_completion_requires_all_four_independent_file_summaries(tmp_path: Path) -> None:
    output_root = tmp_path / "output"
    store = ProjectionStore(tmp_path / "projection.db", output_root)
    directory = output_root / "run-1" / "topic_health"
    directory.mkdir(parents=True)
    topics = ["/camera/image_raw", "/imu/data", "/odom", "/diagnostics"]
    lines = [
        json.dumps(
            {
                **_metric(f"summary-{index}", 0, 90_000, "mission_summary"),
                "topic": topic,
            }
        )
        for index, topic in enumerate(topics)
    ]
    (directory / "part-0").write_text("\n".join(lines), encoding="utf-8")

    assert store.verify_completion("run-1")["verified"] is True


def test_completion_rejects_duplicate_and_in_progress_summaries(tmp_path: Path) -> None:
    output_root = tmp_path / "output"
    store = ProjectionStore(tmp_path / "projection.db", output_root)
    directory = output_root / "run-1" / "topic_health"
    directory.mkdir(parents=True)
    topics = ["/camera/image_raw", "/imu/data", "/odom", "/diagnostics"]
    rows = [
        json.dumps(
            {
                **_metric(f"summary-{index}", 0, 90_000, "mission_summary"),
                "topic": topic,
            }
        )
        for index, topic in enumerate(topics)
    ]
    rows.append(rows[0])
    (directory / "part-0").write_text("\n".join(rows), encoding="utf-8")
    (directory / ".part-1.inprogress").write_text("", encoding="utf-8")

    completion = store.verify_completion("run-1")
    assert completion["verified"] is False
    assert "duplicate topic summaries" in completion["errors"]
    assert "temporary summary files remain" in completion["errors"]


def test_snapshot_never_verifies_files_before_summary_ready_is_projected(tmp_path: Path) -> None:
    output_root = tmp_path / "output"
    store = ProjectionStore(tmp_path / "projection.db", output_root)
    directory = output_root / "run-1" / "topic_health"
    directory.mkdir(parents=True)
    topics = ["/camera/image_raw", "/imu/data", "/odom", "/diagnostics"]
    rows = [
        json.dumps(
            {
                **_metric(f"summary-{index}", 0, 90_000, "mission_summary"),
                "topic": topic,
            }
        )
        for index, topic in enumerate(topics)
    ]
    (directory / "part-0").write_text("\n".join(rows), encoding="utf-8")

    starting = _metric("run-starting", 0, 0, "run_status")
    starting["window_start_ms"] = None
    starting["window_end_ms"] = None
    starting["payload"] = {"status": "starting"}
    store.project(
        stream_kind="metric",
        payload=starting,
        kafka_topic="telemetry.metrics.v1",
        kafka_partition=0,
        kafka_offset=0,
    )

    before_marker = store.snapshot("run-1")
    assert before_marker["completion"]["verified"] is False
    assert before_marker["completion"]["errors"] == ["waiting for committed summary_ready"]

    finalizing = _metric("run-finalizing", 0, 97_000, "run_status")
    finalizing["window_start_ms"] = None
    finalizing["window_end_ms"] = None
    finalizing["payload"] = {"status": "finalizing"}
    store.project(
        stream_kind="metric",
        payload=finalizing,
        kafka_topic="telemetry.metrics.v1",
        kafka_partition=0,
        kafka_offset=1,
    )

    ready = _metric("run-summary-ready", 0, 97_000, "run_status")
    ready["window_start_ms"] = None
    ready["window_end_ms"] = None
    ready["payload"] = {"status": "summary_ready"}
    store.project(
        stream_kind="metric",
        payload=ready,
        kafka_topic="telemetry.metrics.v1",
        kafka_partition=0,
        kafka_offset=2,
    )

    snapshot = store.snapshot("run-1")
    assert snapshot["completion"]["verified"] is True
    assert snapshot["run"]["payload"]["status"] == "summary_ready"
    assert snapshot["run_start_stream_ms"] == 0
    assert snapshot["latest_stream_ms"] == 97_000
    assert snapshot["mission_progress_ms"] == 90_000


def test_latest_topic_prefers_the_latest_partial_window_when_stream_times_tie() -> None:
    earlier = {
        "metric_type": "topic_window",
        "topic": "/camera/image_raw",
        "stream_timestamp_ms": 90_000,
        "window_end_ms": 91_000,
        "revision": 0,
    }
    later = {**earlier, "window_end_ms": 99_000}

    assert ProjectionStore._latest_topics([later, earlier]) == [later]
