from __future__ import annotations

import json
import math
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl
import pyarrow as pa
import pyarrow.parquet as pq


@dataclass(frozen=True)
class LocalizationEvalConfig:
    """Thresholds for the observable-only localization baseline."""

    particle_spread_warn_m: float = 0.4
    pose_jump_warn_m: float = 0.5
    event_merge_gap_ms: float = 500.0
    event_tolerance_ms: float = 100.0

    def __post_init__(self) -> None:
        for name, value in asdict(self).items():
            if not math.isfinite(value) or value <= 0:
                raise ValueError(f"{name} must be finite and greater than zero")


SAMPLE_SCHEMA = {
    "run_id": pl.Utf8,
    "source_file": pl.Utf8,
    "segment_id": pl.Int64,
    "sample_index": pl.Int64,
    "timestamp_ns": pl.Int64,
    "ground_truth_x": pl.Float64,
    "ground_truth_y": pl.Float64,
    "ground_truth_yaw": pl.Float64,
    "estimated_x": pl.Float64,
    "estimated_y": pl.Float64,
    "estimated_yaw": pl.Float64,
    "position_error_m": pl.Float64,
    "heading_error_rad": pl.Float64,
    "label_failure": pl.Boolean,
    "particle_position_spread_m": pl.Float64,
    "estimated_pose_jump_m": pl.Float64,
    "detector_score": pl.Float64,
    "detector_failure": pl.Boolean,
}

EVENT_SCHEMA = {
    "event_id": pl.Utf8,
    "run_id": pl.Utf8,
    "source_file": pl.Utf8,
    "segment_id": pl.Int64,
    "event_kind": pl.Utf8,
    "start_timestamp_ns": pl.Int64,
    "end_timestamp_ns": pl.Int64,
    "sample_count": pl.Int64,
    "max_position_error_m": pl.Float64,
    "max_heading_error_rad": pl.Float64,
    "max_detector_score": pl.Float64,
}

MATCH_SCHEMA = {
    "expected_event_id": pl.Utf8,
    "observed_event_id": pl.Utf8,
    "run_id": pl.Utf8,
    "source_file": pl.Utf8,
    "segment_id": pl.Int64,
    "expected_start_timestamp_ns": pl.Int64,
    "expected_end_timestamp_ns": pl.Int64,
    "observed_start_timestamp_ns": pl.Int64,
    "observed_end_timestamp_ns": pl.Int64,
    "detected": pl.Boolean,
    "onset_lag_ms": pl.Float64,
    "recovery_lag_ms": pl.Float64,
}

_RUN_ID_PATTERN = re.compile(r"(rec_\d{8}_\d{6})")


def _empty_frame(schema: dict[str, pl.DataType]) -> pl.DataFrame:
    return pl.DataFrame(schema=schema)


def _required_field(array: pa.StructArray, name: str) -> pa.Array:
    try:
        return array.field(name)
    except (KeyError, ValueError) as exc:
        raise ValueError(f"TUHH localization data is missing required field {name!r}") from exc


def _float_values(array: pa.Array) -> np.ndarray:
    return np.asarray(array.to_numpy(zero_copy_only=False), dtype=np.float64)


def _yaw_from_quaternion(
    x: np.ndarray,
    y: np.ndarray,
    z: np.ndarray,
    w: np.ndarray,
) -> np.ndarray:
    return np.arctan2(2.0 * (w * z + x * y), 1.0 - 2.0 * (y * y + z * z))


def _particle_position_spread(value: pa.StructArray) -> np.ndarray:
    particle_lists = _required_field(value, "/particle_cloud/particles")
    if not pa.types.is_large_list(particle_lists.type) and not pa.types.is_list(
        particle_lists.type
    ):
        raise ValueError("/particle_cloud/particles must be a list")

    offsets = np.asarray(particle_lists.offsets.to_numpy(zero_copy_only=False), dtype=np.int64)
    counts = np.diff(offsets)
    sample_count = len(counts)
    spread = np.full(sample_count, np.nan, dtype=np.float64)
    if not counts.sum():
        return spread

    particles = particle_lists.values
    pose = _required_field(particles, "pose")
    position = _required_field(pose, "position")
    x = _float_values(_required_field(position, "x"))
    y = _float_values(_required_field(position, "y"))
    weights = _float_values(_required_field(particles, "weight"))

    sample_indices = np.repeat(np.arange(sample_count, dtype=np.int64), counts)
    weight_sum = np.bincount(sample_indices, weights=weights, minlength=sample_count)
    weighted_x = np.bincount(sample_indices, weights=weights * x, minlength=sample_count)
    weighted_y = np.bincount(sample_indices, weights=weights * y, minlength=sample_count)
    weighted_x2 = np.bincount(sample_indices, weights=weights * x * x, minlength=sample_count)
    weighted_y2 = np.bincount(sample_indices, weights=weights * y * y, minlength=sample_count)
    valid = (counts > 0) & (weight_sum > 0)
    mean_x = np.divide(weighted_x, weight_sum, out=np.zeros_like(weighted_x), where=valid)
    mean_y = np.divide(weighted_y, weight_sum, out=np.zeros_like(weighted_y), where=valid)
    variance = (
        np.divide(
            weighted_x2 + weighted_y2,
            weight_sum,
            out=np.zeros_like(weighted_x2),
            where=valid,
        )
        - mean_x * mean_x
        - mean_y * mean_y
    )
    spread[valid] = np.sqrt(np.maximum(variance[valid], 0.0))
    return spread


def _pose_jumps(x: np.ndarray, y: np.ndarray, segment_ids: np.ndarray) -> np.ndarray:
    jumps = np.zeros(len(x), dtype=np.float64)
    if len(x) < 2:
        return jumps
    same_segment = segment_ids[1:] == segment_ids[:-1]
    jumps[1:] = np.where(same_segment, np.hypot(np.diff(x), np.diff(y)), 0.0)
    return jumps


def load_tuhh_processed_parquet(
    path: Path,
    config: LocalizationEvalConfig,
    *,
    segment_offset: int = 0,
) -> pl.DataFrame:
    """Normalize one published TUHH processed Parquet member into sample rows.

    Ground truth and labels are retained only for evaluation. The baseline decision uses
    particle-cloud spread and AMCL pose jumps, both available during robot operation.
    """

    path = path.expanduser().resolve()
    try:
        measurements = pq.read_table(path, columns=["measurements"])[
            "measurements"
        ].combine_chunks()
    except (OSError, pa.ArrowException) as exc:
        raise ValueError(f"Could not read TUHH processed Parquet {path}: {exc}") from exc
    if not pa.types.is_large_list(measurements.type) and not pa.types.is_list(measurements.type):
        raise ValueError("TUHH processed Parquet column 'measurements' must be a list")

    lengths = np.asarray(
        np.diff(measurements.offsets.to_numpy(zero_copy_only=False)), dtype=np.int64
    )
    segment_ids = np.repeat(
        np.arange(segment_offset, segment_offset + len(lengths), dtype=np.int64), lengths
    )
    rows = measurements.values
    value = _required_field(rows, "value")
    timestamp_ns = np.asarray(
        _required_field(rows, "time").to_numpy(zero_copy_only=False), dtype=np.int64
    )

    ground_truth_x = _float_values(_required_field(value, "/momo/pose/pose.position.x"))
    ground_truth_y = _float_values(_required_field(value, "/momo/pose/pose.position.y"))
    gt_qx = _float_values(_required_field(value, "/momo/pose/pose.orientation.x"))
    gt_qy = _float_values(_required_field(value, "/momo/pose/pose.orientation.y"))
    gt_qz = _float_values(_required_field(value, "/momo/pose/pose.orientation.z"))
    gt_qw = _float_values(_required_field(value, "/momo/pose/pose.orientation.w"))

    estimated_x = _float_values(_required_field(value, "/amcl_pose/pose.pose.position.x"))
    estimated_y = _float_values(_required_field(value, "/amcl_pose/pose.pose.position.y"))
    estimated_qx = _float_values(_required_field(value, "/amcl_pose/pose.pose.orientation.x"))
    estimated_qy = _float_values(_required_field(value, "/amcl_pose/pose.pose.orientation.y"))
    estimated_qz = _float_values(_required_field(value, "/amcl_pose/pose.pose.orientation.z"))
    estimated_qw = _float_values(_required_field(value, "/amcl_pose/pose.pose.orientation.w"))

    position_error = _float_values(_required_field(value, "position_error"))
    heading_error = np.abs(_float_values(_required_field(value, "heading_error")))
    label_failure = np.asarray(
        _required_field(value, "is_delocalized").to_numpy(zero_copy_only=False), dtype=bool
    )
    particle_spread = _particle_position_spread(value)
    pose_jump = _pose_jumps(estimated_x, estimated_y, segment_ids)
    detector_score = np.maximum(
        np.nan_to_num(particle_spread / config.particle_spread_warn_m, nan=0.0),
        pose_jump / config.pose_jump_warn_m,
    )
    detector_failure = detector_score > 1.0
    match = _RUN_ID_PATTERN.search(path.name)
    run_id = match.group(1) if match else path.stem

    return pl.DataFrame(
        {
            "run_id": [run_id] * len(rows),
            "source_file": [path.name] * len(rows),
            "segment_id": segment_ids,
            "sample_index": np.arange(len(rows), dtype=np.int64),
            "timestamp_ns": timestamp_ns,
            "ground_truth_x": ground_truth_x,
            "ground_truth_y": ground_truth_y,
            "ground_truth_yaw": _yaw_from_quaternion(gt_qx, gt_qy, gt_qz, gt_qw),
            "estimated_x": estimated_x,
            "estimated_y": estimated_y,
            "estimated_yaw": _yaw_from_quaternion(
                estimated_qx, estimated_qy, estimated_qz, estimated_qw
            ),
            "position_error_m": position_error,
            "heading_error_rad": heading_error,
            "label_failure": label_failure,
            "particle_position_spread_m": particle_spread,
            "estimated_pose_jump_m": pose_jump,
            "detector_score": detector_score,
            "detector_failure": detector_failure,
        },
        schema=SAMPLE_SCHEMA,
    )


def _events_for_flag(
    samples: pl.DataFrame,
    flag: str,
    event_kind: str,
    merge_gap_ns: int,
) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    partitions = samples.partition_by(["run_id", "source_file", "segment_id"], maintain_order=True)
    for partition in partitions:
        rows = partition.iter_rows(named=True)
        active: list[dict[str, Any]] = []

        def append_active(active: list[dict[str, Any]] = active) -> None:
            if not active:
                return
            first = active[0]
            event_number = sum(
                event["run_id"] == first["run_id"] and event["event_kind"] == event_kind
                for event in events
            )
            events.append(
                {
                    "event_id": f"{first['run_id']}:{event_kind}:{event_number + 1}",
                    "run_id": first["run_id"],
                    "source_file": first["source_file"],
                    "segment_id": first["segment_id"],
                    "event_kind": event_kind,
                    "start_timestamp_ns": first["timestamp_ns"],
                    "end_timestamp_ns": active[-1]["timestamp_ns"],
                    "sample_count": len(active),
                    "max_position_error_m": max(row["position_error_m"] for row in active),
                    "max_heading_error_rad": max(row["heading_error_rad"] for row in active),
                    "max_detector_score": max(row["detector_score"] for row in active),
                }
            )
            active.clear()

        inactive_since_ns: int | None = None
        for row in rows:
            if row[flag]:
                if (
                    active
                    and inactive_since_ns is not None
                    and row["timestamp_ns"] - active[-1]["timestamp_ns"] > merge_gap_ns
                ):
                    append_active()
                active.append(row)
                inactive_since_ns = None
            else:
                inactive_since_ns = row["timestamp_ns"]
        append_active()
    return events


def build_localization_events(
    samples: pl.DataFrame, config: LocalizationEvalConfig
) -> pl.DataFrame:
    merge_gap_ns = int(config.event_merge_gap_ms * 1_000_000)
    rows = [
        *_events_for_flag(samples, "label_failure", "expected", merge_gap_ns),
        *_events_for_flag(samples, "detector_failure", "observed", merge_gap_ns),
    ]
    return (
        pl.DataFrame(rows, schema=EVENT_SCHEMA).sort(["run_id", "start_timestamp_ns", "event_kind"])
        if rows
        else _empty_frame(EVENT_SCHEMA)
    )


def _safe_ratio(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def _match_event_partition(
    expected: list[dict[str, Any]],
    observed: list[dict[str, Any]],
    tolerance_ns: int,
) -> dict[str, dict[str, Any]]:
    """Return a maximum-cardinality, minimum-onset-distance event matching.

    Events of each kind are disjoint and time ordered, so an order-preserving dynamic
    program avoids the under-counting that a nearest-candidate greedy pass can cause.
    """

    expected = sorted(expected, key=lambda row: row["start_timestamp_ns"])
    observed = sorted(observed, key=lambda row: row["start_timestamp_ns"])
    expected_count = len(expected)
    observed_count = len(observed)
    scores = [[(0, 0) for _ in range(observed_count + 1)] for _ in range(expected_count + 1)]
    choices = [["done" for _ in range(observed_count + 1)] for _ in range(expected_count + 1)]

    for expected_index in range(expected_count - 1, -1, -1):
        for observed_index in range(observed_count - 1, -1, -1):
            wanted = expected[expected_index]
            seen = observed[observed_index]
            candidates = [
                (scores[expected_index + 1][observed_index], 0, "skip_expected"),
                (scores[expected_index][observed_index + 1], 1, "skip_observed"),
            ]
            overlaps = (
                seen["end_timestamp_ns"] + tolerance_ns >= wanted["start_timestamp_ns"]
                and seen["start_timestamp_ns"] - tolerance_ns <= wanted["end_timestamp_ns"]
            )
            if overlaps:
                remaining_matches, remaining_cost = scores[expected_index + 1][observed_index + 1]
                candidates.append(
                    (
                        (
                            remaining_matches + 1,
                            remaining_cost
                            + abs(seen["start_timestamp_ns"] - wanted["start_timestamp_ns"]),
                        ),
                        2,
                        "match",
                    )
                )
            score, _, choice = max(
                candidates,
                key=lambda candidate: (
                    candidate[0][0],
                    -candidate[0][1],
                    candidate[1],
                ),
            )
            scores[expected_index][observed_index] = score
            choices[expected_index][observed_index] = choice

    matched: dict[str, dict[str, Any]] = {}
    expected_index = 0
    observed_index = 0
    while expected_index < expected_count and observed_index < observed_count:
        choice = choices[expected_index][observed_index]
        if choice == "match":
            matched[expected[expected_index]["event_id"]] = observed[observed_index]
            expected_index += 1
            observed_index += 1
        elif choice == "skip_observed":
            observed_index += 1
        else:
            expected_index += 1
    return matched


def _match_localization_events(
    expected: list[dict[str, Any]],
    observed: list[dict[str, Any]],
    tolerance_ns: int,
) -> dict[str, dict[str, Any]]:
    partitions: dict[
        tuple[str, str, int],
        dict[str, list[dict[str, Any]]],
    ] = {}
    for event_kind, rows in (("expected", expected), ("observed", observed)):
        for row in rows:
            key = (row["run_id"], row["source_file"], row["segment_id"])
            partitions.setdefault(key, {"expected": [], "observed": []})[event_kind].append(row)

    matched: dict[str, dict[str, Any]] = {}
    for partition in partitions.values():
        matched.update(
            _match_event_partition(
                partition["expected"],
                partition["observed"],
                tolerance_ns,
            )
        )
    return matched


def score_localization(
    samples: pl.DataFrame,
    events: pl.DataFrame,
    config: LocalizationEvalConfig,
) -> tuple[dict[str, Any], pl.DataFrame]:
    labels = samples.get_column("label_failure").to_numpy()
    predictions = samples.get_column("detector_failure").to_numpy()
    true_positive = int(np.sum(labels & predictions))
    false_positive = int(np.sum(~labels & predictions))
    false_negative = int(np.sum(labels & ~predictions))
    true_negative = int(np.sum(~labels & ~predictions))
    precision = _safe_ratio(true_positive, true_positive + false_positive)
    recall = _safe_ratio(true_positive, true_positive + false_negative)
    f1 = (
        2 * precision * recall / (precision + recall)
        if precision is not None and recall is not None and precision + recall
        else None
    )

    event_rows = list(events.iter_rows(named=True))
    expected = [row for row in event_rows if row["event_kind"] == "expected"]
    observed = [row for row in event_rows if row["event_kind"] == "observed"]
    tolerance_ns = int(config.event_tolerance_ms * 1_000_000)
    matched_events = _match_localization_events(expected, observed, tolerance_ns)
    matched_observed_ids = {row["event_id"] for row in matched_events.values()}
    match_rows: list[dict[str, Any]] = []
    for wanted in expected:
        seen = matched_events.get(wanted["event_id"])
        match_rows.append(
            {
                "expected_event_id": wanted["event_id"],
                "observed_event_id": seen["event_id"] if seen else None,
                "run_id": wanted["run_id"],
                "source_file": wanted["source_file"],
                "segment_id": wanted["segment_id"],
                "expected_start_timestamp_ns": wanted["start_timestamp_ns"],
                "expected_end_timestamp_ns": wanted["end_timestamp_ns"],
                "observed_start_timestamp_ns": seen["start_timestamp_ns"] if seen else None,
                "observed_end_timestamp_ns": seen["end_timestamp_ns"] if seen else None,
                "detected": seen is not None,
                "onset_lag_ms": (
                    (seen["start_timestamp_ns"] - wanted["start_timestamp_ns"]) / 1_000_000
                    if seen
                    else None
                ),
                "recovery_lag_ms": (
                    (seen["end_timestamp_ns"] - wanted["end_timestamp_ns"]) / 1_000_000
                    if seen
                    else None
                ),
            }
        )
    matches = (
        pl.DataFrame(match_rows, schema=MATCH_SCHEMA) if match_rows else _empty_frame(MATCH_SCHEMA)
    )
    event_precision = _safe_ratio(len(matched_observed_ids), len(observed))
    matched_expected_count = len(matched_events)
    event_recall = _safe_ratio(matched_expected_count, len(expected))
    onset_lags = [row["onset_lag_ms"] for row in match_rows if row["onset_lag_ms"] is not None]
    recovery_lags = [
        row["recovery_lag_ms"] for row in match_rows if row["recovery_lag_ms"] is not None
    ]
    return (
        {
            "sample_count": samples.height,
            "failure_sample_count": int(labels.sum()),
            "failure_rate": float(labels.mean()) if len(labels) else None,
            "sample_metrics": {
                "true_positive": true_positive,
                "false_positive": false_positive,
                "false_negative": false_negative,
                "true_negative": true_negative,
                "precision": precision,
                "recall": recall,
                "f1": f1,
            },
            "event_metrics": {
                "expected_event_count": len(expected),
                "observed_event_count": len(observed),
                "matched_event_count": matched_expected_count,
                "matched_observed_event_count": len(matched_observed_ids),
                "false_alarm_event_count": len(observed) - len(matched_observed_ids),
                "precision": event_precision,
                "recall": event_recall,
                "mean_onset_lag_ms": float(np.mean(onset_lags)) if onset_lags else None,
                "mean_recovery_lag_ms": (float(np.mean(recovery_lags)) if recovery_lags else None),
            },
        },
        matches,
    )


def _format_metric(value: float | None) -> str:
    return "-" if value is None else f"{value:.3f}"


def render_localization_report(
    summary: dict[str, Any],
    matches: pl.DataFrame,
) -> str:
    sample = summary["sample_metrics"]
    event = summary["event_metrics"]
    lines = [
        "# Localization Integrity Evaluation",
        "",
        f"Samples: **{summary['sample_count']}**  ",
        f"Labeled failures: **{summary['failure_sample_count']}** "
        f"({_format_metric(summary['failure_rate'])})  ",
        f"Runs: **{summary['run_count']}**",
        "",
        "## Observable-only baseline",
        "",
        "The detector uses particle-cloud position spread and consecutive AMCL pose jumps. "
        "Ground-truth pose, position error, heading error, and published failure labels are "
        "used only for scoring.",
        "",
        f"- Sample precision: **{_format_metric(sample['precision'])}**",
        f"- Sample recall: **{_format_metric(sample['recall'])}**",
        f"- Sample F1: **{_format_metric(sample['f1'])}**",
        f"- Event precision: **{_format_metric(event['precision'])}**",
        f"- Event recall: **{_format_metric(event['recall'])}**",
        f"- False-alarm events: **{event['false_alarm_event_count']}**",
        "",
        "## Expected versus observed",
        "",
    ]
    if not matches.height:
        lines.append("No labeled failure events were present.")
    else:
        lines.extend(
            [
                "| Run | Expected start (ns) | Observed start (ns) | Detected | "
                "Onset lag (ms) | Recovery lag (ms) |",
                "| --- | ---: | ---: | --- | ---: | ---: |",
            ]
        )
        for row in matches.iter_rows(named=True):
            lines.append(
                f"| `{row['run_id']}` | {row['expected_start_timestamp_ns']} | "
                f"{row['observed_start_timestamp_ns'] or '-'} | "
                f"{'yes' if row['detected'] else 'no'} | "
                f"{_format_metric(row['onset_lag_ms'])} | "
                f"{_format_metric(row['recovery_lag_ms'])} |"
            )
    lines.extend(
        [
            "",
            "## Interpretation boundary",
            "",
            "This is an engineering baseline on published simulation data, not a safety "
            "certification. Thresholds must be validated on the target robot and environment.",
            "",
        ]
    )
    return "\n".join(lines)


def evaluate_localization_files(
    inputs: list[Path],
    output_dir: Path,
    config: LocalizationEvalConfig | None = None,
) -> dict[str, Any]:
    config = config or LocalizationEvalConfig()
    if not inputs:
        raise ValueError("At least one processed localization Parquet input is required")
    frames: list[pl.DataFrame] = []
    segment_offset = 0
    for input_path in inputs:
        frame = load_tuhh_processed_parquet(input_path, config, segment_offset=segment_offset)
        frames.append(frame)
        segment_offset = int(frame.get_column("segment_id").max()) + 1
    samples = pl.concat(frames, how="vertical")
    events = build_localization_events(samples, config)
    summary, matches = score_localization(samples, events, config)
    summary.update(
        {
            "schema_version": 1,
            "dataset_adapter": "tuhh_robot_localization_failure_prediction_v1",
            "input_files": [str(path.expanduser().resolve()) for path in inputs],
            "run_count": samples.get_column("run_id").n_unique(),
            "thresholds": asdict(config),
            "detector_inputs": [
                "particle_position_spread_m",
                "estimated_pose_jump_m",
            ],
            "evaluation_only_fields": [
                "ground_truth_pose",
                "position_error_m",
                "heading_error_rad",
                "label_failure",
            ],
        }
    )

    output_dir = output_dir.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    samples.write_parquet(output_dir / "localization_samples.parquet", compression="zstd")
    events.write_parquet(output_dir / "localization_events.parquet", compression="zstd")
    matches.write_parquet(output_dir / "localization_event_matches.parquet", compression="zstd")
    (output_dir / "localization_eval.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (output_dir / "localization_eval.md").write_text(
        render_localization_report(summary, matches), encoding="utf-8"
    )
    return summary
