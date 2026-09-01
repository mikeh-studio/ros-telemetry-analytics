from __future__ import annotations

import json
from pathlib import Path

import polars as pl
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from ros_telemetry_analytics.localization_eval import (
    EVENT_SCHEMA,
    SAMPLE_SCHEMA,
    LocalizationEvalConfig,
    evaluate_localization_files,
    load_tuhh_processed_parquet,
    score_localization,
)


def _measurement(timestamp_ns: int, failure: bool, particle_offset: float) -> dict:
    identity = {"x": 0.0, "y": 0.0, "z": 0.0, "w": 1.0}
    position_error = 0.5 if failure else 0.1
    return {
        "time": timestamp_ns,
        "value": {
            "/particle_cloud/particles": [
                {
                    "pose": {
                        "position": {"x": -particle_offset, "y": 0.0, "z": 0.0},
                        "orientation": identity,
                    },
                    "weight": 0.5,
                },
                {
                    "pose": {
                        "position": {"x": particle_offset, "y": 0.0, "z": 0.0},
                        "orientation": identity,
                    },
                    "weight": 0.5,
                },
            ],
            "/momo/pose/pose.position.x": timestamp_ns / 1_000_000_000 * 0.1,
            "/momo/pose/pose.position.y": 0.0,
            "/momo/pose/pose.orientation.x": 0.0,
            "/momo/pose/pose.orientation.y": 0.0,
            "/momo/pose/pose.orientation.z": 0.0,
            "/momo/pose/pose.orientation.w": 1.0,
            "/amcl_pose/pose.pose.position.x": timestamp_ns / 1_000_000_000 * 0.1,
            "/amcl_pose/pose.pose.position.y": 0.0,
            "/amcl_pose/pose.pose.orientation.x": 0.0,
            "/amcl_pose/pose.pose.orientation.y": 0.0,
            "/amcl_pose/pose.pose.orientation.z": 0.0,
            "/amcl_pose/pose.pose.orientation.w": 1.0,
            "position_error": position_error,
            "heading_error": 0.0,
            "is_delocalized": failure,
        },
    }


def _write_tuhh_fixture(path: Path) -> None:
    rows = [
        {
            "measurements": [
                _measurement(0, False, 0.1),
                _measurement(1_000_000_000, True, 0.5),
                _measurement(2_000_000_000, True, 0.5),
                _measurement(3_000_000_000, False, 0.1),
            ]
        },
        {
            "measurements": [
                _measurement(4_000_000_000, False, 0.1),
                _measurement(5_000_000_000, True, 0.1),
                _measurement(6_000_000_000, False, 0.1),
            ]
        },
    ]
    pq.write_table(pa.Table.from_pylist(rows), path)


def test_tuhh_adapter_keeps_labels_out_of_detector_inputs(tmp_path: Path) -> None:
    source = tmp_path / "rec_20250821_104113_id_01.processed.parquet"
    _write_tuhh_fixture(source)

    samples = load_tuhh_processed_parquet(source, LocalizationEvalConfig())

    assert samples.height == 7
    assert samples.get_column("segment_id").to_list() == [0, 0, 0, 0, 1, 1, 1]
    assert samples.get_column("particle_position_spread_m").to_list() == pytest.approx(
        [0.1, 0.5, 0.5, 0.1, 0.1, 0.1, 0.1]
    )
    assert samples.get_column("detector_failure").to_list() == [
        False,
        True,
        True,
        False,
        False,
        False,
        False,
    ]
    assert (
        samples.get_column("label_failure").to_list()
        != samples.get_column("detector_failure").to_list()
    )


def test_localization_eval_writes_scorecard_and_expected_observed_timeline(
    tmp_path: Path,
) -> None:
    source = tmp_path / "rec_20250821_104113_id_01.processed.parquet"
    output = tmp_path / "evaluation"
    _write_tuhh_fixture(source)

    summary = evaluate_localization_files([source], output)

    assert summary["sample_count"] == 7
    assert summary["sample_metrics"] == {
        "true_positive": 2,
        "false_positive": 0,
        "false_negative": 1,
        "true_negative": 4,
        "precision": 1.0,
        "recall": pytest.approx(2 / 3),
        "f1": pytest.approx(0.8),
    }
    assert summary["event_metrics"]["expected_event_count"] == 2
    assert summary["event_metrics"]["matched_event_count"] == 1
    assert summary["event_metrics"]["recall"] == 0.5
    assert summary["evaluation_only_fields"] == [
        "ground_truth_pose",
        "position_error_m",
        "heading_error_rad",
        "label_failure",
    ]
    for name in (
        "localization_samples.parquet",
        "localization_events.parquet",
        "localization_event_matches.parquet",
        "localization_eval.json",
        "localization_eval.md",
    ):
        assert (output / name).is_file()
    persisted = json.loads((output / "localization_eval.json").read_text())
    assert persisted["dataset_adapter"] == "tuhh_robot_localization_failure_prediction_v1"
    report = (output / "localization_eval.md").read_text()
    assert "# Localization Integrity Evaluation" in report
    assert "Expected versus observed" in report
    assert "Sample F1: **0.800**" in report


def test_event_matching_does_not_reuse_one_alert_for_multiple_failures() -> None:
    samples = pl.DataFrame(
        {
            name: (
                [False]
                if dtype == pl.Boolean
                else [0.0]
                if dtype == pl.Float64
                else [0]
                if dtype == pl.Int64
                else ["run-1"]
            )
            for name, dtype in SAMPLE_SCHEMA.items()
        },
        schema=SAMPLE_SCHEMA,
    )
    event_defaults = {
        "run_id": "run-1",
        "source_file": "run.parquet",
        "segment_id": 0,
        "sample_count": 1,
        "max_position_error_m": 1.0,
        "max_heading_error_rad": 0.0,
        "max_detector_score": 2.0,
    }
    events = pl.DataFrame(
        [
            {
                **event_defaults,
                "event_id": "expected-1",
                "event_kind": "expected",
                "start_timestamp_ns": 100,
                "end_timestamp_ns": 200,
            },
            {
                **event_defaults,
                "event_id": "expected-2",
                "event_kind": "expected",
                "start_timestamp_ns": 300,
                "end_timestamp_ns": 400,
            },
            {
                **event_defaults,
                "event_id": "observed-1",
                "event_kind": "observed",
                "start_timestamp_ns": 150,
                "end_timestamp_ns": 350,
            },
        ],
        schema=EVENT_SCHEMA,
    )

    summary, matches = score_localization(
        samples,
        events,
        LocalizationEvalConfig(event_tolerance_ms=0.000001),
    )

    assert summary["event_metrics"]["matched_event_count"] == 1
    assert summary["event_metrics"]["precision"] == 1.0
    assert summary["event_metrics"]["recall"] == 0.5
    assert matches.get_column("detected").to_list() == [True, False]


def test_event_matching_maximizes_detected_events_before_onset_distance() -> None:
    samples = pl.DataFrame(
        {
            name: (
                [False]
                if dtype == pl.Boolean
                else [0.0]
                if dtype == pl.Float64
                else [0]
                if dtype == pl.Int64
                else ["run-1"]
            )
            for name, dtype in SAMPLE_SCHEMA.items()
        },
        schema=SAMPLE_SCHEMA,
    )
    event_defaults = {
        "run_id": "run-1",
        "source_file": "run.parquet",
        "segment_id": 0,
        "sample_count": 1,
        "max_position_error_m": 1.0,
        "max_heading_error_rad": 0.0,
        "max_detector_score": 2.0,
    }
    events = pl.DataFrame(
        [
            {
                **event_defaults,
                "event_id": "expected-1",
                "event_kind": "expected",
                "start_timestamp_ns": 100,
                "end_timestamp_ns": 200,
            },
            {
                **event_defaults,
                "event_id": "expected-2",
                "event_kind": "expected",
                "start_timestamp_ns": 250,
                "end_timestamp_ns": 350,
            },
            {
                **event_defaults,
                "event_id": "observed-shared",
                "event_kind": "observed",
                "start_timestamp_ns": 150,
                "end_timestamp_ns": 300,
            },
            {
                **event_defaults,
                "event_id": "observed-first-only",
                "event_kind": "observed",
                "start_timestamp_ns": 0,
                "end_timestamp_ns": 110,
            },
        ],
        schema=EVENT_SCHEMA,
    )

    summary, matches = score_localization(
        samples,
        events,
        LocalizationEvalConfig(event_tolerance_ms=0.000001),
    )

    assert summary["event_metrics"]["matched_event_count"] == 2
    assert summary["event_metrics"]["precision"] == 1.0
    assert summary["event_metrics"]["recall"] == 1.0
    assert matches.get_column("observed_event_id").to_list() == [
        "observed-first-only",
        "observed-shared",
    ]
