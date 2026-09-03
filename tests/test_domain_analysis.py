from __future__ import annotations

from pathlib import Path

import polars as pl
import pyarrow as pa
import pyarrow.parquet as pq

from ros_telemetry_analytics.config import DomainAnalyticsConfig
from ros_telemetry_analytics.domain import DOMAIN_RECORD_DIRECTORY, DOMAIN_SCHEMAS
from ros_telemetry_analytics.domain_analysis import (
    EVENT_SCHEMA,
    METRIC_SCHEMA,
    build_domain_summary,
    render_bag_report,
    run_domain_analysis,
)


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
        "laser_scans": 0,
        "point_clouds": 0,
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
        "laser_scans": 0,
        "point_clouds": 0,
    }
    assert (tmp_path / "domain_metrics.parquet").exists()
    assert (tmp_path / "anomaly_events.parquet").exists()
    assert (tmp_path / "domain_summary.json").exists()


def test_summary_and_report_prioritize_severe_findings_before_caps() -> None:
    metrics = pl.DataFrame(
        [
            {
                "bag_id": "bag",
                "domain": "image",
                "topic": f"/camera/{index:02d}",
                "metric": "mean_intensity",
                "value": float(index),
                "unit": "level",
                "status": "ok",
                "detail": "",
            }
            for index in range(45)
        ]
        + [
            {
                "bag_id": "bag",
                "domain": "tf",
                "topic": "zz-warning",
                "metric": "empty_frame_count",
                "value": 1.0,
                "unit": "transforms",
                "status": "warn",
                "detail": "warning must survive truncation",
            },
            {
                "bag_id": "bag",
                "domain": "tf",
                "topic": "zz-error",
                "metric": "frame_cycle_count",
                "value": 1.0,
                "unit": "cycles",
                "status": "error",
                "detail": "error must survive truncation",
            },
        ],
        schema=METRIC_SCHEMA,
    )
    events = pl.DataFrame(
        [
            {
                "bag_id": "bag",
                "domain": "image",
                "topic": "/camera",
                "start_timestamp_ns": index,
                "end_timestamp_ns": index,
                "severity": "warn",
                "event_type": "early_warning",
                "observed_value": 1.0,
                "threshold": 0.0,
                "unit": "frames",
                "detail": f"early warning {index}",
            }
            for index in range(55)
        ]
        + [
            {
                "bag_id": "bag",
                "domain": "tf",
                "topic": "/tf",
                "start_timestamp_ns": 10_000,
                "end_timestamp_ns": 10_000,
                "severity": "error",
                "event_type": "late_error",
                "observed_value": 1.0,
                "threshold": 0.0,
                "unit": "cycles",
                "detail": "late error must survive truncation",
            }
        ],
        schema=EVENT_SCHEMA,
    )
    record_counts = {name: 0 for name in DOMAIN_SCHEMAS}

    domain_summary = build_domain_summary(True, metrics, events, record_counts)

    assert [row["status"] for row in domain_summary["key_metrics"][:2]] == [
        "error",
        "warn",
    ]
    bag_summary = {
        "bag_id": "bag",
        "analyzed_at": "2026-07-15T00:00:00+00:00",
        "message_count": 101,
        "topic_count": 47,
        "health_status": "ok",
        "health_findings": [],
        "domain_analysis": domain_summary,
    }
    report = render_bag_report(bag_summary, metrics, events)
    assert "zz-error" in report
    assert "zz-warning" in report
    assert "late_error" in report
    assert report.index("late_error") < report.index("early_warning")
