from __future__ import annotations

import math
import re
from collections import Counter
from pathlib import Path
from typing import Any

import polars as pl

from ros_telemetry_analytics.config import AnalyticsConfig

NS_PER_SECOND = 1_000_000_000
LEFT_TOPIC_PATTERN = re.compile(r"^(?P<prefix>.*)/left/(?P<suffix>.+)$")

TOPIC_HEALTH_SCHEMA = {
    "bag_id": pl.Utf8,
    "topic": pl.Utf8,
    "message_count": pl.Int64,
    "first_timestamp_ns": pl.Int64,
    "last_timestamp_ns": pl.Int64,
    "duration_s": pl.Float64,
    "mean_rate_hz": pl.Float64,
    "expected_rate_hz": pl.Float64,
    "rate_ratio": pl.Float64,
    "max_inter_message_gap_s": pl.Float64,
    "p95_inter_message_gap_s": pl.Float64,
    "gap_threshold_s": pl.Float64,
    "gap_event_count": pl.Int64,
    "estimated_dropped_messages": pl.Int64,
    "status": pl.Utf8,
}

VSLAM_QUALITY_SCHEMA = {
    "bag_id": pl.Utf8,
    "check_type": pl.Utf8,
    "topic": pl.Utf8,
    "topic_left": pl.Utf8,
    "topic_right": pl.Utf8,
    "message_count": pl.Int64,
    "mean_rate_hz": pl.Float64,
    "max_inter_message_gap_s": pl.Float64,
    "max_gap_to_mean_interval_ratio": pl.Float64,
    "left_message_count": pl.Int64,
    "right_message_count": pl.Int64,
    "paired_message_count": pl.Int64,
    "unmatched_left_count": pl.Int64,
    "unmatched_right_count": pl.Int64,
    "max_abs_sync_skew_ns": pl.Int64,
    "p95_abs_sync_skew_ns": pl.Float64,
    "mean_abs_sync_skew_ns": pl.Float64,
    "status": pl.Utf8,
    "detail": pl.Utf8,
}


def _empty_frame(schema: dict[str, pl.DataType]) -> pl.DataFrame:
    return pl.DataFrame(schema=schema)


def _validate_message_index(frame: pl.DataFrame) -> None:
    required = {"bag_id", "sequence", "topic", "timestamp_ns"}
    missing = required.difference(frame.columns)
    if missing:
        raise ValueError(f"Message index is missing required columns: {sorted(missing)}")


def _quantile(values: list[int], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, math.ceil(percentile * len(ordered)) - 1)
    return float(ordered[index])


def _status_rank(status: str) -> int:
    return {"ok": 0, "warn": 1, "error": 2}.get(status, 2)


def overall_status(statuses: list[str]) -> str:
    return max(statuses, key=_status_rank, default="error")


def _zero_message_rows(
    topic_manifest: pl.DataFrame | None,
    observed_topics: set[tuple[str, str]],
    config: AnalyticsConfig,
) -> list[dict[str, Any]]:
    if topic_manifest is None or topic_manifest.is_empty():
        return []

    rows: list[dict[str, Any]] = []
    totals = topic_manifest.group_by(["bag_id", "topic"]).agg(pl.col("message_count").sum())
    for item in totals.iter_rows(named=True):
        key = (item["bag_id"], item["topic"])
        if key in observed_topics or item["message_count"] != 0:
            continue
        expected_rate = config.expected_rate(item["topic"])
        rows.append(
            {
                "bag_id": item["bag_id"],
                "topic": item["topic"],
                "message_count": 0,
                "first_timestamp_ns": None,
                "last_timestamp_ns": None,
                "duration_s": None,
                "mean_rate_hz": None,
                "expected_rate_hz": expected_rate,
                "rate_ratio": 0.0 if expected_rate else None,
                "max_inter_message_gap_s": None,
                "p95_inter_message_gap_s": None,
                "gap_threshold_s": (
                    config.gap_threshold_multiplier / expected_rate if expected_rate else None
                ),
                "gap_event_count": 0,
                "estimated_dropped_messages": 0,
                "status": "error",
            }
        )
    return rows


def compute_topic_health(
    message_index: pl.DataFrame,
    config: AnalyticsConfig,
    topic_manifest: pl.DataFrame | None = None,
) -> pl.DataFrame:
    """Compute timing, rate, and dropout metrics per topic."""
    _validate_message_index(message_index)

    rows: list[dict[str, Any]] = []
    observed_topics: set[tuple[str, str]] = set()
    for partition in message_index.partition_by(["bag_id", "topic"], maintain_order=True):
        bag_id = partition.item(0, "bag_id")
        topic = partition.item(0, "topic")
        observed_topics.add((bag_id, topic))
        timestamps = partition.get_column("timestamp_ns").cast(pl.Int64).sort().to_list()
        gaps_ns = [
            current - previous
            for previous, current in zip(timestamps, timestamps[1:], strict=False)
        ]
        message_count = len(timestamps)
        first_timestamp = timestamps[0]
        last_timestamp = timestamps[-1]
        duration_ns = last_timestamp - first_timestamp
        duration_s = duration_ns / NS_PER_SECOND
        mean_rate = (
            (message_count - 1) * NS_PER_SECOND / duration_ns
            if message_count > 1 and duration_ns > 0
            else None
        )
        expected_rate = config.expected_rate(topic)
        rate_ratio = mean_rate / expected_rate if mean_rate is not None and expected_rate else None
        gap_threshold_s = config.gap_threshold_multiplier / expected_rate if expected_rate else None
        gap_threshold_ns = gap_threshold_s * NS_PER_SECOND if gap_threshold_s else None
        gap_events = (
            sum(gap > gap_threshold_ns for gap in gaps_ns) if gap_threshold_ns is not None else 0
        )
        estimated_drops = (
            max(0, round(duration_s * expected_rate) + 1 - message_count)
            if expected_rate and duration_ns > 0
            else 0
        )

        if message_count > 1 and duration_ns == 0:
            status = "error"
        elif message_count == 1:
            status = "warn"
        elif gap_events or (
            rate_ratio is not None
            and not (config.minimum_rate_ratio <= rate_ratio <= config.maximum_rate_ratio)
        ):
            status = "warn"
        else:
            status = "ok"

        rows.append(
            {
                "bag_id": bag_id,
                "topic": topic,
                "message_count": message_count,
                "first_timestamp_ns": first_timestamp,
                "last_timestamp_ns": last_timestamp,
                "duration_s": duration_s,
                "mean_rate_hz": mean_rate,
                "expected_rate_hz": expected_rate,
                "rate_ratio": rate_ratio,
                "max_inter_message_gap_s": max(gaps_ns) / NS_PER_SECOND if gaps_ns else None,
                "p95_inter_message_gap_s": (
                    _quantile(gaps_ns, 0.95) / NS_PER_SECOND if gaps_ns else None
                ),
                "gap_threshold_s": gap_threshold_s,
                "gap_event_count": gap_events,
                "estimated_dropped_messages": estimated_drops,
                "status": status,
            }
        )
    rows.extend(_zero_message_rows(topic_manifest, observed_topics, config))
    return (
        pl.DataFrame(rows, schema=TOPIC_HEALTH_SCHEMA).sort(["bag_id", "topic"])
        if rows
        else _empty_frame(TOPIC_HEALTH_SCHEMA)
    )


def _continuity_rows(
    message_index: pl.DataFrame,
    config: AnalyticsConfig,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    continuity = message_index.filter(
        pl.col("topic").map_elements(config.is_continuity_topic, return_dtype=pl.Boolean)
    )
    for partition in continuity.partition_by(["bag_id", "topic"], maintain_order=True):
        bag_id = partition.item(0, "bag_id")
        topic = partition.item(0, "topic")
        timestamps = sorted(partition.get_column("timestamp_ns").cast(pl.Int64).to_list())
        gaps = [
            current - previous
            for previous, current in zip(timestamps, timestamps[1:], strict=False)
        ]
        duration = timestamps[-1] - timestamps[0]
        mean_interval = duration / (len(timestamps) - 1) if len(timestamps) > 1 else None
        max_gap = max(gaps) if gaps else None
        gap_ratio = max_gap / mean_interval if max_gap is not None and mean_interval else None
        if len(timestamps) > 1 and duration == 0:
            status = "error"
        elif len(timestamps) == 1 or (gap_ratio and gap_ratio > config.continuity_gap_ratio_warn):
            status = "warn"
        else:
            status = "ok"
        rows.append(
            {
                "bag_id": bag_id,
                "check_type": "timestamp_continuity",
                "topic": topic,
                "topic_left": None,
                "topic_right": None,
                "message_count": len(timestamps),
                "mean_rate_hz": (
                    (len(timestamps) - 1) * NS_PER_SECOND / duration
                    if len(timestamps) > 1 and duration > 0
                    else None
                ),
                "max_inter_message_gap_s": max_gap / NS_PER_SECOND if max_gap is not None else None,
                "max_gap_to_mean_interval_ratio": gap_ratio,
                "left_message_count": None,
                "right_message_count": None,
                "paired_message_count": None,
                "unmatched_left_count": None,
                "unmatched_right_count": None,
                "max_abs_sync_skew_ns": None,
                "p95_abs_sync_skew_ns": None,
                "mean_abs_sync_skew_ns": None,
                "status": status,
                "detail": (
                    "single message topic"
                    if len(timestamps) == 1
                    else f"max gap is {gap_ratio:.2f}x mean interval"
                    if gap_ratio is not None
                    else "no timestamp span"
                ),
            }
        )
    return rows


def pair_timestamps(
    left_times: list[int],
    right_times: list[int],
    pairing_window_ns: int,
) -> tuple[list[int], int, int]:
    """Pair ordered stereo timestamps by nearest unused neighbor within a window."""
    left = sorted(left_times)
    right = sorted(right_times)
    skews: list[int] = []
    unmatched_left = 0
    unmatched_right = 0
    right_index = 0

    for left_timestamp in left:
        while right_index < len(right) and right[right_index] < left_timestamp - pairing_window_ns:
            unmatched_right += 1
            right_index += 1

        candidate_end = right_index
        while candidate_end < len(right) and right[candidate_end] <= (
            left_timestamp + pairing_window_ns
        ):
            candidate_end += 1
        candidates = range(right_index, candidate_end)
        if not candidates:
            unmatched_left += 1
            continue

        match_index = min(candidates, key=lambda index: abs(right[index] - left_timestamp))
        unmatched_right += match_index - right_index
        skews.append(abs(right[match_index] - left_timestamp))
        right_index = match_index + 1

    unmatched_right += len(right) - right_index
    return skews, unmatched_left, unmatched_right


def _stereo_rows(
    message_index: pl.DataFrame,
    config: AnalyticsConfig,
    topic_manifest: pl.DataFrame | None = None,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    bag_ids = set(message_index.get_column("bag_id").unique().to_list())
    if topic_manifest is not None and not topic_manifest.is_empty():
        bag_ids.update(topic_manifest.get_column("bag_id").unique().to_list())
    for bag_id in sorted(bag_ids):
        bag_partition = message_index.filter(pl.col("bag_id") == bag_id)
        topics = set(bag_partition.get_column("topic").unique().to_list())
        if topic_manifest is not None and not topic_manifest.is_empty():
            topics.update(
                topic_manifest.filter(pl.col("bag_id") == bag_id)
                .get_column("topic")
                .unique()
                .to_list()
            )
        for left_topic in sorted(topics):
            match = LEFT_TOPIC_PATTERN.match(left_topic)
            if not match:
                continue
            right_topic = f"{match.group('prefix')}/right/{match.group('suffix')}"
            left_times = (
                bag_partition.filter(pl.col("topic") == left_topic)
                .get_column("timestamp_ns")
                .cast(pl.Int64)
                .to_list()
            )
            right_times = (
                bag_partition.filter(pl.col("topic") == right_topic)
                .get_column("timestamp_ns")
                .cast(pl.Int64)
                .to_list()
                if right_topic in topics
                else []
            )
            skews, unmatched_left, unmatched_right = pair_timestamps(
                left_times,
                right_times,
                config.stereo_pairing_window_ns,
            )
            max_skew = max(skews) if skews else None
            status = (
                "error"
                if not right_times
                else "warn"
                if unmatched_left
                or unmatched_right
                or max_skew is None
                or max_skew > config.stereo_skew_warn_ns
                else "ok"
            )
            rows.append(
                {
                    "bag_id": bag_id,
                    "check_type": "stereo_sync",
                    "topic": f"{left_topic} <-> {right_topic}",
                    "topic_left": left_topic,
                    "topic_right": right_topic,
                    "message_count": None,
                    "mean_rate_hz": None,
                    "max_inter_message_gap_s": None,
                    "max_gap_to_mean_interval_ratio": None,
                    "left_message_count": len(left_times),
                    "right_message_count": len(right_times),
                    "paired_message_count": len(skews),
                    "unmatched_left_count": unmatched_left,
                    "unmatched_right_count": unmatched_right,
                    "max_abs_sync_skew_ns": max_skew,
                    "p95_abs_sync_skew_ns": _quantile(skews, 0.95),
                    "mean_abs_sync_skew_ns": sum(skews) / len(skews) if skews else None,
                    "status": status,
                    "detail": (
                        f"right topic has no messages: {right_topic}"
                        if not right_times
                        else f"paired {len(skews)}; unmatched left/right "
                        f"{unmatched_left}/{unmatched_right}; max skew {max_skew} ns"
                    ),
                }
            )
    return rows


def compute_vslam_quality(
    message_index: pl.DataFrame,
    config: AnalyticsConfig,
    topic_manifest: pl.DataFrame | None = None,
) -> pl.DataFrame:
    """Compute continuity and stereo synchronization checks."""
    _validate_message_index(message_index)
    if message_index.is_empty() and (topic_manifest is None or topic_manifest.is_empty()):
        return _empty_frame(VSLAM_QUALITY_SCHEMA)
    rows = _continuity_rows(message_index, config) + _stereo_rows(
        message_index, config, topic_manifest
    )
    return (
        pl.DataFrame(rows, schema=VSLAM_QUALITY_SCHEMA).sort(["bag_id", "check_type", "topic"])
        if rows
        else _empty_frame(VSLAM_QUALITY_SCHEMA)
    )


def analyze_message_index(
    message_index_path: Path,
    output_dir: Path,
    config: AnalyticsConfig,
) -> tuple[pl.DataFrame, pl.DataFrame]:
    """Run all configured analytics and persist their Parquet outputs."""
    message_index = pl.read_parquet(message_index_path)
    topic_manifest = pl.read_parquet(output_dir / "topic_manifest.parquet")
    topic_health = compute_topic_health(message_index, config, topic_manifest)
    vslam_quality = compute_vslam_quality(message_index, config, topic_manifest)
    topic_health.write_parquet(output_dir / "topic_health.parquet", compression="zstd")
    vslam_quality.write_parquet(output_dir / "vslam_quality.parquet", compression="zstd")
    return topic_health, vslam_quality


def build_analysis_summary(
    topic_health: pl.DataFrame,
    vslam_quality: pl.DataFrame,
) -> dict[str, Any]:
    topic_statuses = topic_health.get_column("status").to_list() if topic_health.height else []
    quality_statuses = vslam_quality.get_column("status").to_list() if vslam_quality.height else []
    statuses = topic_statuses + quality_statuses
    counts = Counter(statuses)
    return {
        "health_status": overall_status(statuses),
        "warning_count": counts["warn"],
        "error_count": counts["error"],
        "topic_health_counts": dict(Counter(topic_statuses)),
        "quality_check_counts": dict(Counter(quality_statuses)),
    }
