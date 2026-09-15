"""Read-only investigation of saved localization evaluations; never reruns a detector."""

from __future__ import annotations

import hashlib
import json
import math
from functools import lru_cache
from pathlib import Path

import polars as pl

FILES = (
    "localization_eval.json",
    "localization_samples.parquet",
    "localization_event_matches.parquet",
    "localization_events.parquet",
)
FIELDS = (
    "timestamp_ns",
    "sample_index",
    "segment_id",
    "run_id",
    "source_file",
    "ground_truth_x",
    "ground_truth_y",
    "estimated_x",
    "estimated_y",
    "position_error_m",
    "heading_error_rad",
    "particle_position_spread_m",
    "particle_heading_spread_rad",
    "estimated_pose_jump_m",
    "detector_score",
    "label_failure",
    "detector_failure",
)


def signature(directory: Path) -> tuple:
    return tuple(
        (name, (directory / name).stat().st_mtime_ns, (directory / name).stat().st_size)
        for name in FILES
    )


def clean(value):
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, dict):
        return {key: clean(item) for key, item in value.items()}
    if isinstance(value, list):
        return [clean(item) for item in value]
    return value


@lru_cache(maxsize=2)
def _load(directory: str, version: tuple):
    root = Path(directory)
    summary = json.loads((root / FILES[0]).read_text())
    samples = pl.read_parquet(root / FILES[1])
    required = {
        "timestamp_ns",
        "run_id",
        "source_file",
        "segment_id",
        "label_failure",
        "detector_failure",
    }
    if not required.issubset(samples.columns) or samples.is_empty():
        raise ValueError("Recording identity or samples are missing from this evaluation")
    matches = pl.read_parquet(root / FILES[2]).to_dicts()
    events = pl.read_parquet(root / FILES[3]).to_dicts()
    # Separate experiment runs have independent clocks; files within a run share one.
    clocks = {
        row["run_id"]: {
            "run_id": row["run_id"],
            "origin_timestamp_ns": row["origin"],
            "duration_ms": (row["end"] - row["origin"]) / 1e6,
        }
        for row in samples.group_by("run_id")
        .agg(
            pl.col("timestamp_ns").min().alias("origin"),
            pl.col("timestamp_ns").max().alias("end"),
        )
        .to_dicts()
    }
    event_by_id = {
        (item["run_id"], item["source_file"], item["segment_id"], item["event_id"]): item
        for item in events
    }
    matched = {
        (item["run_id"], item["source_file"], item["segment_id"], item["observed_event_id"])
        for item in matches
        if item["detected"]
    }
    cases = []
    for match in matches:
        identity = (match["run_id"], match["source_file"], match["segment_id"])
        event = event_by_id.get((*identity, match["expected_event_id"]), {})
        cases.append(
            {
                **match,
                **{key: event.get(key) for key in ("max_position_error_m", "max_detector_score")},
                "event_id": match["expected_event_id"],
                "outcome": "detected" if match["detected"] else "missed",
                "start_timestamp_ns": match["expected_start_timestamp_ns"],
                "end_timestamp_ns": match["expected_end_timestamp_ns"],
            }
        )
    for event in events:
        key = (event["run_id"], event["source_file"], event["segment_id"], event["event_id"])
        if event["event_kind"] == "observed" and key not in matched:
            cases.append(
                {
                    **event,
                    "outcome": "false_alarm",
                    "observed_start_timestamp_ns": event["start_timestamp_ns"],
                    "observed_end_timestamp_ns": event["end_timestamp_ns"],
                    "onset_lag_ms": None,
                    "recovery_lag_ms": None,
                }
            )
    cases.sort(key=lambda item: (item["run_id"], item["start_timestamp_ns"], item["event_id"]))
    for index, case in enumerate(cases):
        case["case_id"] = str(index)
        clock = clocks[case["run_id"]]
        origin = clock["origin_timestamp_ns"]
        case["run_duration_ms"] = clock["duration_ms"]
        case["start_ms"] = (case["start_timestamp_ns"] - origin) / 1e6
        case["end_ms"] = (case["end_timestamp_ns"] - origin) / 1e6
        case["duration_ms"] = case["end_ms"] - case["start_ms"]
    config = {
        "inputs": summary.get("detector_inputs", []),
        "thresholds": summary.get("thresholds", {}),
    }
    metadata = {
        "status": "available",
        "evaluation_id": hashlib.sha256(repr(version).encode()).hexdigest()[:16],
        "configuration_id": hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest()[
            :12
        ],
        "detector_version": summary.get("detector_version"),
        "dataset": summary.get("dataset_adapter", "Saved localization evaluation"),
        "recordings": sorted(
            {Path(name).name for name in samples["source_file"].unique().to_list()}
        ),
        "duration_ms": sum(clock["duration_ms"] for clock in clocks.values()),
        "clock_basis": "run",
        "runs": [clocks[key] for key in sorted(clocks)],
        "sample_count": samples.height,
        "cases": clean([{**case, "source_file": Path(case["source_file"]).name} for case in cases]),
    }
    return metadata, samples, cases, clocks


def load(directory: Path):
    version = signature(directory)
    result = _load(str(directory), version)
    if signature(directory) != version:
        raise ValueError("Evaluation changed while loading; refresh the evaluation")
    return result


def metadata(directory: Path) -> dict:
    try:
        return load(directory)[0]
    except (OSError, ValueError, KeyError, pl.exceptions.PolarsError) as exc:
        return {"status": "unavailable", "detail": f"Investigation evidence unavailable: {exc}"}


def interval(directory: Path, case_id: str, evaluation_id: str) -> dict:
    meta, samples, cases, clocks = load(directory)
    if evaluation_id != meta["evaluation_id"]:
        raise RuntimeError("Evaluation changed. Refresh and select the event again.")
    case = next((item for item in cases if item["case_id"] == case_id), None)
    if case is None:
        raise LookupError("Event not found in this evaluation")
    clock = clocks[case["run_id"]]
    origin = clock["origin_timestamp_ns"]
    # Include detection and recovery plus context, but never another source/segment.
    start = (
        min(
            case["start_timestamp_ns"],
            case.get("observed_start_timestamp_ns") or case["start_timestamp_ns"],
        )
        - 5_000_000_000
    )
    end = (
        max(
            case["end_timestamp_ns"],
            case.get("observed_end_timestamp_ns") or case["end_timestamp_ns"],
        )
        + 5_000_000_000
    )
    part = samples.filter(
        (pl.col("run_id") == case["run_id"])
        & (pl.col("source_file") == case["source_file"])
        & (pl.col("segment_id") == case["segment_id"])
    )
    gaps = (
        part.sort(
            ["timestamp_ns", "sample_index"] if "sample_index" in part.columns else ["timestamp_ns"]
        )["timestamp_ns"]
        .diff()
        .drop_nulls()
    )
    positive = gaps.filter(gaps > 0)
    gap_ms = max(100.0, float(positive.median() or 0) / 1e6 * 5)
    route_frame = part.sort("timestamp_ns")
    route_fields = [
        field
        for field in (
            "timestamp_ns",
            "ground_truth_x",
            "ground_truth_y",
            "estimated_x",
            "estimated_y",
        )
        if field in part.columns
    ]
    route_rows = clean(route_frame.select(route_fields).to_dicts())
    continuity = 0
    for index, row in enumerate(route_rows):
        row["elapsed_ms"] = (row["timestamp_ns"] - origin) / 1e6
        invalid = any(row.get(field) is None for field in route_fields if field != "timestamp_ns")
        if index and (
            invalid
            or route_rows[index - 1].get("invalid")
            or row["elapsed_ms"] - route_rows[index - 1]["elapsed_ms"] > gap_ms
        ):
            continuity += 1
        row["continuity"] = continuity
        row["invalid"] = invalid
    indices = sorted(
        {
            round(index * (len(route_rows) - 1) / max(1, min(600, len(route_rows)) - 1))
            for index in range(min(600, len(route_rows)))
        }
    )
    route = [route_rows[index] for index in indices]
    part = part.filter(pl.col("timestamp_ns").is_between(start, end)).sort(
        ["timestamp_ns", "sample_index"] if "sample_index" in part.columns else ["timestamp_ns"]
    )
    if part.height > 25000:
        raise ValueError("This event interval exceeds the 25,000-sample inspection limit")
    rows = part.select([field for field in FIELDS if field in part.columns]).to_dicts()
    for index, row in enumerate(rows):
        row["elapsed_ms"] = (row["timestamp_ns"] - origin) / 1e6
        row["source_file"] = Path(row["source_file"]).name
        row["break_before"] = (
            index == 0 or row["elapsed_ms"] - rows[index - 1]["elapsed_ms"] > gap_ms
        )
    if not rows:
        raise ValueError("No samples are available for this event interval")
    return {
        "evaluation_id": evaluation_id,
        "case_id": case_id,
        "run_id": case["run_id"],
        "clock_origin_timestamp_ns": origin,
        "run_duration_ms": clock["duration_ms"],
        "samples": clean(rows),
        "route": route,
        "sample_count": len(rows),
        "start_ms": rows[0]["elapsed_ms"],
        "end_ms": rows[-1]["elapsed_ms"],
        "gap_threshold_ms": gap_ms,
        "resolution": "full",
        "context_seconds": 5,
    }
