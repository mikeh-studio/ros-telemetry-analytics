import asyncio
import json

import polars as pl
import pytest
from fastapi import HTTPException

from demo.api import app as api
from demo.api import localization_investigation as investigation


@pytest.fixture
def recording(tmp_path):
    identity = {"run_id": "run-a", "source_file": "recording.parquet", "segment_id": 0}
    samples = [
        {
            **identity,
            "timestamp_ns": int(t * 1e9),
            "sample_index": index,
            "ground_truth_x": float(index),
            "ground_truth_y": 0.0,
            "estimated_x": float(index),
            "estimated_y": 0.0,
            "label_failure": index in (1, 2),
            "detector_failure": index == 2,
            "particle_position_spread_m": float("nan") if index == 1 else 0.2,
            "estimated_pose_jump_m": 0.1,
        }
        for index, t in enumerate([0, 0.01, 0.01, 0.02, 2, 2.01, 2.02, 8])
    ]
    # Same timestamps and segment id in another source and run must never leak in.
    samples += [
        {**samples[0], "run_id": "other-run", "estimated_x": 999.0},
        {**samples[0], "source_file": "other.parquet", "estimated_x": 888.0},
    ]
    pl.DataFrame(samples).write_parquet(tmp_path / "localization_samples.parquet")
    matches = [
        {
            **identity,
            "expected_event_id": "expected",
            "observed_event_id": "matched",
            "expected_start_timestamp_ns": 10_000_000,
            "expected_end_timestamp_ns": 20_000_000,
            "observed_start_timestamp_ns": 10_000_000,
            "observed_end_timestamp_ns": 20_000_000,
            "detected": True,
            "onset_lag_ms": 0.0,
            "recovery_lag_ms": 0.0,
        }
    ]
    pl.DataFrame(matches).write_parquet(tmp_path / "localization_event_matches.parquet")
    events = [
        {
            **identity,
            "event_id": name,
            "event_kind": kind,
            "start_timestamp_ns": 10_000_000,
            "end_timestamp_ns": 20_000_000,
        }
        for name, kind in [
            ("expected", "expected"),
            ("matched", "observed"),
            ("unmatched", "observed"),
        ]
    ]
    pl.DataFrame(events).write_parquet(tmp_path / "localization_events.parquet")
    (tmp_path / "localization_eval.json").write_text(
        json.dumps({"thresholds": {"pose_jump_warn_m": 0.5}})
    )
    return tmp_path


def test_unmatched_alerts_and_full_resolution_source_isolation(recording):
    meta = investigation.metadata(recording)
    assert [case["outcome"] for case in meta["cases"]] == ["detected", "false_alarm"]
    result = investigation.interval(recording, "0", meta["evaluation_id"])
    assert len(result["samples"]) == 7  # full resolution, including both duplicate timestamps
    assert {row["run_id"] for row in result["samples"]} == {"run-a"}
    assert {row["source_file"] for row in result["samples"]} == {"recording.parquet"}
    assert result["samples"][1]["particle_position_spread_m"] is None
    assert result["samples"][4]["break_before"]
    assert not result["samples"][2]["break_before"]
    assert result["route"][-1]["elapsed_ms"] == 8000
    assert result["route"][4]["continuity"] != result["route"][3]["continuity"]
    json.dumps(result, allow_nan=False)


def test_evaluation_change_and_missing_event_have_explicit_http_errors(recording, monkeypatch):
    monkeypatch.setattr(api, "LOCALIZATION_EVAL_DIR", recording)
    meta = investigation.metadata(recording)
    with pytest.raises(HTTPException) as missing:
        asyncio.run(api.localization_interval("missing", meta["evaluation_id"]))
    assert missing.value.status_code == 404
    (recording / "localization_eval.json").write_text('{"thresholds": {"pose_jump_warn_m": 0.75}}')
    with pytest.raises(HTTPException) as changed:
        asyncio.run(api.localization_interval("0", meta["evaluation_id"]))
    assert changed.value.status_code == 409
    assert investigation.metadata(recording)["configuration_id"] != meta["configuration_id"]


def test_all_events_are_listed_not_only_first_hundred(recording):
    matches = pl.read_parquet(recording / "localization_event_matches.parquet").to_dicts()[0]
    pl.DataFrame(
        [
            {
                **matches,
                "expected_event_id": f"missed-{i}",
                "detected": False,
                "observed_event_id": None,
            }
            for i in range(125)
        ]
    ).write_parquet(recording / "localization_event_matches.parquet")
    meta = investigation.metadata(recording)
    assert sum(case["outcome"] == "missed" for case in meta["cases"]) == 125
    assert sum(case["outcome"] == "false_alarm" for case in meta["cases"]) == 2


def test_missing_evidence_does_not_invent_a_detector_version(tmp_path):
    assert investigation.metadata(tmp_path)["status"] == "unavailable"


def test_malformed_evidence_is_not_reported_as_a_missing_event(recording, monkeypatch):
    monkeypatch.setattr(api, "LOCALIZATION_EVAL_DIR", recording)
    meta = investigation.metadata(recording)
    path = recording / "localization_event_matches.parquet"
    pl.read_parquet(path).drop("detected").write_parquet(path)
    with pytest.raises(HTTPException) as invalid:
        asyncio.run(api.localization_interval("0", meta["evaluation_id"]))
    assert invalid.value.status_code == 422


def test_independent_runs_use_their_own_clocks(recording):
    offset = 1_000_000_000_000
    for name in (
        "localization_samples.parquet",
        "localization_event_matches.parquet",
        "localization_events.parquet",
    ):
        path = recording / name
        frame = pl.read_parquet(path)
        second = frame.filter(pl.col("run_id") == "run-a").with_columns(
            pl.lit("run-b").alias("run_id"),
            *[
                (pl.col(column) + offset).alias(column)
                for column in frame.columns
                if column == "timestamp_ns" or column.endswith("_timestamp_ns")
            ],
        )
        pl.concat([frame, second]).write_parquet(path)
    meta = investigation.metadata(recording)
    # Two eight-second runs, not the unrelated 1000-second gap between clocks.
    assert meta["duration_ms"] == 16_000
    first = next(case for case in meta["cases"] if case["run_id"] == "run-a")
    second = next(case for case in meta["cases"] if case["run_id"] == "run-b")
    assert first["start_ms"] == second["start_ms"] == 10
    result = investigation.interval(recording, second["case_id"], meta["evaluation_id"])
    assert result["start_ms"] == 0
    assert result["route"][-1]["elapsed_ms"] == 8000
    assert {row["run_id"] for row in result["samples"]} == {"run-b"}
