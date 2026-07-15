from __future__ import annotations

from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from ros_telemetry_analytics.config import DomainAnalyticsConfig
from ros_telemetry_analytics.domain import DOMAIN_RECORD_DIRECTORY, DOMAIN_SCHEMAS
from ros_telemetry_analytics.domain_analysis import render_bag_report, run_domain_analysis


def _write_records(output_dir: Path, records: dict[str, list[dict]]) -> None:
    record_dir = output_dir / DOMAIN_RECORD_DIRECTORY
    record_dir.mkdir(parents=True)
    for name, schema in DOMAIN_SCHEMAS.items():
        pq.write_table(
            pa.Table.from_pylist(records.get(name, []), schema=schema),
            record_dir / f"{name}.parquet",
        )


def test_domain_analyzers_emit_metrics_events_and_report(tmp_path: Path) -> None:
    bag_id = "bag"
    records = {
        "odometry": [
            {
                "bag_id": bag_id,
                "sequence": index,
                "topic": "/odom",
                "timestamp_ns": index * 1_000_000_000,
                "position_x": position,
                "position_y": 0.0,
                "position_z": 0.0,
                "linear_x": 0.0,
                "linear_y": 0.0,
                "linear_z": 0.0,
            }
            for index, position in enumerate((0.0, 0.2, 2.0))
        ],
        "imu": [
            {
                "bag_id": bag_id,
                "sequence": 10 + index,
                "topic": "/imu",
                "timestamp_ns": index * 100_000_000,
                "angular_velocity_x": angular,
                "angular_velocity_y": 0.0,
                "angular_velocity_z": 0.0,
                "linear_acceleration_x": acceleration,
                "linear_acceleration_y": 0.0,
                "linear_acceleration_z": 0.0,
            }
            for index, (acceleration, angular) in enumerate(((9.8, 0.1), (35.0, 11.0)))
        ],
        "commands": [
            {
                "bag_id": bag_id,
                "sequence": 20,
                "topic": "/cmd_vel",
                "timestamp_ns": 0,
                "linear_x": 1.0,
                "linear_y": 0.0,
                "linear_z": 0.0,
                "angular_x": 0.0,
                "angular_y": 0.0,
                "angular_z": 0.0,
            }
        ],
        "transforms": [
            {
                "bag_id": bag_id,
                "sequence": 30,
                "topic": "/tf",
                "timestamp_ns": 0,
                "frame_id": "map",
                "child_frame_id": "base",
                "translation_x": 0.0,
                "translation_y": 0.0,
                "translation_z": 0.0,
            },
            {
                "bag_id": bag_id,
                "sequence": 31,
                "topic": "/tf",
                "timestamp_ns": 1_000_000_000,
                "frame_id": "map",
                "child_frame_id": "base",
                "translation_x": 2.0,
                "translation_y": 0.0,
                "translation_z": 0.0,
            },
            {
                "bag_id": bag_id,
                "sequence": 32,
                "topic": "/tf",
                "timestamp_ns": 1_000_000_000,
                "frame_id": "base",
                "child_frame_id": "map",
                "translation_x": 0.0,
                "translation_y": 0.0,
                "translation_z": 0.0,
            },
        ],
        "diagnostics": [
            {
                "bag_id": bag_id,
                "sequence": 40,
                "topic": "/diagnostics",
                "timestamp_ns": 0,
                "level": 1,
                "name": "motor",
                "message": "warm",
                "hardware_id": "motor-1",
                "values_json": "{}",
            }
        ],
        "images": [
            {
                "bag_id": bag_id,
                "sequence": 50 + index,
                "topic": "/camera/image_raw",
                "timestamp_ns": index * 100_000_000,
                "height": 2,
                "width": 2,
                "encoding": "mono8",
                "step": 2,
                "data_bytes": 4,
                "mean_intensity": 10.0,
                "sharpness_score": 1.0,
                "content_hash": "same-hash",
            }
            for index in range(2)
        ],
        "extraction_errors": [
            {
                "bag_id": bag_id,
                "sequence": 60,
                "topic": "/broken",
                "message_type": "sensor_msgs/msg/Imu",
                "timestamp_ns": 0,
                "error_type": "ValueError",
                "error_message": "bad payload",
            }
        ],
    }
    _write_records(tmp_path, records)

    metrics, events, domain_summary = run_domain_analysis(tmp_path, DomainAnalyticsConfig())

    assert set(domain_summary["domains_present"]) == {
        "command",
        "diagnostics",
        "extraction",
        "image",
        "imu",
        "odometry",
        "tf",
    }
    assert domain_summary["status"] == "error"
    assert domain_summary["record_counts"] == {
        "odometry": 3,
        "imu": 2,
        "commands": 1,
        "transforms": 3,
        "diagnostics": 1,
        "images": 2,
    }
    assert domain_summary["payload_extraction_error_count"] == 1
    assert domain_summary["metric_error_count"] == 1
    assert {
        "command_without_motion",
        "dark_frames",
        "diagnostic_status",
        "duplicate_frames",
        "frame_cycle",
        "high_acceleration",
        "high_angular_velocity",
        "low_sharpness",
        "payload_deserialization_failed",
        "pose_jump",
        "translation_jump",
    }.issubset(set(events.get_column("event_type")))
    distance = metrics.filter(
        (metrics["domain"] == "odometry") & (metrics["metric"] == "distance_traveled")
    ).item(0, "value")
    assert distance == 2.0

    bag_summary = {
        "bag_id": bag_id,
        "analyzed_at": "2026-07-15T00:00:00+00:00",
        "message_count": 12,
        "topic_count": 7,
        "health_status": "warn",
        "health_findings": [
            {
                "source": "vslam_quality",
                "check": "timestamp_continuity",
                "topic": "/tf",
                "status": "warn",
                "detail": "max gap exceeded the continuity threshold",
            }
        ],
        "domain_analysis": domain_summary,
    }
    report = render_bag_report(bag_summary, metrics, events)
    assert "# Robot Bag Analysis" in report
    assert "## Analysis Coverage" in report
    assert "max gap exceeded the continuity threshold" in report
    assert "distance_traveled" in report
    assert "command_without_motion" in report


def test_disabled_domain_analysis_publishes_empty_contract(tmp_path: Path) -> None:
    _write_records(tmp_path, {})

    metrics, events, summary = run_domain_analysis(
        tmp_path,
        DomainAnalyticsConfig(enabled=False),
    )

    assert metrics.is_empty()
    assert events.is_empty()
    assert summary["status"] == "disabled"
    assert summary["record_counts"] == {
        "odometry": 0,
        "imu": 0,
        "commands": 0,
        "transforms": 0,
        "diagnostics": 0,
        "images": 0,
    }
    assert (tmp_path / "domain_metrics.parquet").exists()
    assert (tmp_path / "anomaly_events.parquet").exists()
    assert (tmp_path / "domain_summary.json").exists()
