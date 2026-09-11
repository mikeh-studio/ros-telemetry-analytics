from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

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


def test_observed_signal_retention_is_bounded_per_robot_and_topic(tmp_path: Path) -> None:
    store = ProjectionStore(tmp_path / "projection.db", tmp_path / "output")
    records = []
    for index in range(190):
        metric = _metric(f"signal-{index}", 0, index * 1000, "observed_signal")
        records.append(
            dict(
                stream_kind="metric",
                payload=metric,
                kafka_topic="telemetry.metrics.v1",
                kafka_partition=0,
                kafka_offset=index,
            )
        )
    other = _metric("other-robot", 0, 0, "observed_signal")
    other["robot_id"] = "robot-other"
    records.append(
        dict(
            stream_kind="metric",
            payload=other,
            kafka_topic="telemetry.metrics.v1",
            kafka_partition=0,
            kafka_offset=190,
        )
    )
    store.project_batch(records)
    signals = store.snapshot("run-1")["observed_signals"]
    assert len(signals) == 181
    assert (
        min(row["stream_timestamp_ms"] for row in signals if row["robot_id"] == "robot-17") == 10000
    )
    assert any(row["robot_id"] == "robot-other" for row in signals)
    assert store.snapshot("different-run")["observed_signals"] == []


def test_live_run_preserves_source_and_robot_identity(tmp_path: Path) -> None:
    store = ProjectionStore(tmp_path / "projection.db", tmp_path / "output")
    metric = _metric("live-status", 0, 10_000, "run_status")
    metric["robot_id"] = "robot-live-1"
    metric["payload"] = {
        "status": "running",
        "source_format": "live_ros2",
        "dataset_id": "live-ros2",
        "expected_topic_count": 6,
    }
    store.project(
        stream_kind="metric",
        payload=metric,
        kafka_topic="telemetry.metrics.v1",
        kafka_partition=0,
        kafka_offset=0,
    )
    snapshot = store.snapshot()
    assert snapshot["source"] == "live_ros2"
    assert snapshot["robot_id"] == "robot-live-1"
    assert snapshot["topic_count"] == 6


def test_interleaved_runs_retain_separate_projection_with_bounded_history(tmp_path: Path) -> None:
    store = ProjectionStore(tmp_path / "projection.db", tmp_path / "output")
    for index in range(9):
        metric = _metric(f"status-{index}", 0, (index + 1) * 10_000, "run_status")
        metric["run_id"] = f"run-{index}"
        metric["payload"]["status"] = "running"
        store.project(
            stream_kind="metric",
            payload=metric,
            kafka_topic="telemetry.metrics.v1",
            kafka_partition=0,
            kafka_offset=index,
        )
    assert store.snapshot("run-0")["run"] is None
    assert store.snapshot("run-1")["run"]["run_id"] == "run-1"
    assert store.snapshot("run-8")["run"]["run_id"] == "run-8"

    older_summary = _metric("older-summary", 0, 95_000, "mission_summary")
    older_summary["run_id"] = "run-1"
    store.project(
        stream_kind="metric",
        payload=older_summary,
        kafka_topic="telemetry.metrics.v1",
        kafka_partition=0,
        kafka_offset=9,
    )
    assert store.snapshot("run-1")["mission_summaries"]["/odom"]["payload"]["message_count"] == 200
    assert store.snapshot("run-8")["run"]["run_id"] == "run-8"


def test_anomaly_revision_wins_over_timestamp_and_stale_redelivery(tmp_path: Path) -> None:
    store = ProjectionStore(tmp_path / "projection.db", tmp_path / "output")
    original = {
        "anomaly_id": "incident",
        "run_id": "run-1",
        "robot_id": "robot-1",
        "topic": None,
        "condition_type": "ROBOT_OFFLINE",
        "status": "active",
        "revision": 0,
        "detected_stream_ms": 20000,
    }
    recovered = {**original, "status": "recovered", "revision": 1, "detected_stream_ms": 15000}
    for offset, payload in enumerate((original, recovered, original)):
        store.project(
            stream_kind="anomaly",
            payload=payload,
            kafka_topic="telemetry.anomalies.v1",
            kafka_partition=0,
            kafka_offset=offset,
        )
    assert store.snapshot("run-1")["anomalies"][0]["status"] == "recovered"
    assert store.offsets()[("telemetry.anomalies.v1", 0)] == 3


def test_projection_batch_rolls_back_messages_and_offsets_together(tmp_path: Path) -> None:
    store = ProjectionStore(tmp_path / "projection.db", tmp_path / "output")
    record = {
        "stream_kind": "metric",
        "payload": _metric("one", 0, 1000),
        "kafka_topic": "telemetry.metrics.v1",
        "kafka_partition": 0,
        "kafka_offset": 0,
    }
    with pytest.raises(KeyError):
        store.project_batch([record, {**record, "payload": {}}])
    assert store.offsets() == {}
    assert store.snapshot()["run_id"] is None
    assert store.project_batch([record, {**record, "kafka_offset": 1}]) == [True, False]
    assert store.offsets()[("telemetry.metrics.v1", 0)] == 2


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


def test_completion_honors_the_selected_dataset_topic_count(tmp_path: Path) -> None:
    output_root = tmp_path / "output"
    store = ProjectionStore(tmp_path / "projection.db", output_root)
    directory = output_root / "run-1" / "topic_health"
    directory.mkdir(parents=True)
    rows = []
    for index, topic in enumerate(["/scan", "/odom"]):
        metric = _metric(f"summary-{index}", 0, 30_000, "mission_summary")
        metric["topic"] = topic
        metric["payload"]["expected_topic_count"] = 2
        rows.append(json.dumps(metric))
    (directory / "part-0").write_text("\n".join(rows), encoding="utf-8")

    completion = store.verify_completion("run-1")

    assert completion["verified"] is True
    assert completion["expected_topic_count"] == 2


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


def test_pending_completion_reports_selected_dataset_topic_count(tmp_path: Path) -> None:
    store = ProjectionStore(tmp_path / "projection.db", tmp_path / "output")
    starting = _metric("run-starting", 0, 0, "run_status")
    starting["window_start_ms"] = None
    starting["window_end_ms"] = None
    starting["payload"] = {
        "status": "starting",
        "dataset_id": "lilocbench_dynamics_0",
        "expected_topic_count": 7,
    }
    store.project(
        stream_kind="metric",
        payload=starting,
        kafka_topic="telemetry.metrics.v1",
        kafka_partition=0,
        kafka_offset=0,
    )

    snapshot = store.snapshot("run-1")

    assert snapshot["topic_count"] == 7
    assert snapshot["completion"]["expected_topic_count"] == 7


def test_snapshot_prefers_resumed_status_at_the_same_frozen_stream_time(
    tmp_path: Path,
) -> None:
    store = ProjectionStore(tmp_path / "projection.db", tmp_path / "output")
    statuses = [
        ("initial-running", "running", 5_000, 1),
        ("paused", "paused", 5_000, 0),
        ("resumed", "running", 5_000, 0),
    ]
    for offset, (metric_id, status, timestamp, revision) in enumerate(statuses):
        metric = _metric(metric_id, revision, timestamp, "run_status")
        metric["window_start_ms"] = None
        metric["window_end_ms"] = None
        metric["payload"] = {"status": status}
        store.project(
            stream_kind="metric",
            payload=metric,
            kafka_topic="telemetry.metrics.v1",
            kafka_partition=0,
            kafka_offset=offset,
        )

    snapshot = store.snapshot("run-1")
    assert snapshot["run"]["payload"]["status"] == "running"
    assert snapshot["run"]["metric_id"] == _metric("resumed", 0, 5_000, "run_status")["metric_id"]


def test_snapshot_does_not_regress_finalizing_to_a_late_active_status(
    tmp_path: Path,
) -> None:
    store = ProjectionStore(tmp_path / "projection.db", tmp_path / "output")
    statuses = [
        ("finalizing", "finalizing", 90_000),
        ("late-running", "running", 91_000),
    ]
    for offset, (metric_id, status, timestamp) in enumerate(statuses):
        metric = _metric(metric_id, 0, timestamp, "run_status")
        metric["window_start_ms"] = None
        metric["window_end_ms"] = None
        metric["payload"] = {"status": status}
        store.project(
            stream_kind="metric",
            payload=metric,
            kafka_topic="telemetry.metrics.v1",
            kafka_partition=0,
            kafka_offset=offset,
        )

    assert store.snapshot("run-1")["run"]["payload"]["status"] == "finalizing"


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


def test_topic_history_survives_reopen_and_uses_corrected_windows(tmp_path: Path) -> None:
    db = tmp_path / "history.db"
    output = tmp_path / "output"
    store = ProjectionStore(db, output)
    first = _metric("first", 0, 10000)
    later = _metric("later", 0, 11000)
    correction = {**first, "revision": 1, "payload": {"mean_rate_hz": 19.5}}
    other = {**_metric("other", 0, 12000), "run_id": "another-run"}
    for offset, metric in enumerate([first, later, correction, other]):
        store.project(
            stream_kind="metric",
            payload=metric,
            kafka_topic="telemetry.metrics.v1",
            kafka_partition=0,
            kafka_offset=offset,
        )
    snapshot = ProjectionStore(db, output).snapshot("run-1")
    assert len(snapshot["topic_history"]) == 2
    assert {item["run_id"] for item in snapshot["topic_history"]} == {"run-1"}
    assert snapshot["topic_history"][0]["payload"]["mean_rate_hz"] == 19.5
    assert snapshot["topics"][0]["window_end_ms"] == 11000
