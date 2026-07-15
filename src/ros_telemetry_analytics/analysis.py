from __future__ import annotations

import math
import re
from collections import Counter
from pathlib import Path
from typing import Any

import polars as pl

from ros_telemetry_analytics.config import AnalyticsConfig, TopicRelationshipRule

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

RELATIONSHIP_HEALTH_SCHEMA = {
    "bag_id": pl.Utf8,
    "relationship_name": pl.Utf8,
    "relationship_type": pl.Utf8,
    "source": pl.Utf8,
    "topic_a": pl.Utf8,
    "topic_b": pl.Utf8,
    "topic_a_message_count": pl.Int64,
    "topic_b_message_count": pl.Int64,
    "paired_message_count": pl.Int64,
    "unmatched_topic_a_count": pl.Int64,
    "unmatched_topic_b_count": pl.Int64,
    "max_abs_skew_ns": pl.Int64,
    "p95_abs_skew_ns": pl.Float64,
    "mean_abs_skew_ns": pl.Float64,
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


def _topic_timestamps(bag_partition: pl.DataFrame, topic: str) -> list[int]:
    return (
        bag_partition.filter(pl.col("topic") == topic)
        .get_column("timestamp_ns")
        .cast(pl.Int64)
        .to_list()
    )


def _relationship_row(
    bag_id: str,
    bag_partition: pl.DataFrame,
    rule: TopicRelationshipRule,
    config: AnalyticsConfig,
    *,
    source: str,
) -> dict[str, Any]:
    topic_a_times = _topic_timestamps(bag_partition, rule.topic_a)
    topic_b_times = _topic_timestamps(bag_partition, rule.topic_b)
    pairing_window_ns = (
        rule.pairing_window_ns
        if rule.pairing_window_ns is not None
        else config.stereo_pairing_window_ns
    )
    skew_warn_ns = (
        rule.skew_warn_ns if rule.skew_warn_ns is not None else config.stereo_skew_warn_ns
    )
    skews, unmatched_a, unmatched_b = pair_timestamps(
        topic_a_times,
        topic_b_times,
        pairing_window_ns,
    )
    max_skew = max(skews) if skews else None

    missing_topics = [
        topic
        for topic, timestamps in ((rule.topic_a, topic_a_times), (rule.topic_b, topic_b_times))
        if not timestamps
    ]
    if missing_topics:
        status = "error" if rule.required else "warn"
        detail = "topic has no messages: " + ", ".join(missing_topics)
    elif unmatched_a or unmatched_b or max_skew is None or max_skew > skew_warn_ns:
        status = "warn"
        detail = (
            f"paired {len(skews)}; unmatched topic_a/topic_b {unmatched_a}/{unmatched_b}; "
            f"max skew {max_skew} ns"
        )
    else:
        status = "ok"
        detail = f"paired {len(skews)}; unmatched topic_a/topic_b 0/0; max skew {max_skew} ns"

    return {
        "bag_id": bag_id,
        "relationship_name": rule.name,
        "relationship_type": rule.relationship_type,
        "source": source,
        "topic_a": rule.topic_a,
        "topic_b": rule.topic_b,
        "topic_a_message_count": len(topic_a_times),
        "topic_b_message_count": len(topic_b_times),
        "paired_message_count": len(skews),
        "unmatched_topic_a_count": unmatched_a,
        "unmatched_topic_b_count": unmatched_b,
        "max_abs_skew_ns": max_skew,
        "p95_abs_skew_ns": _quantile(skews, 0.95),
        "mean_abs_skew_ns": sum(skews) / len(skews) if skews else None,
        "status": status,
        "detail": detail,
    }


def _automatic_stereo_rules(topics: set[str]) -> list[TopicRelationshipRule]:
    rules: list[TopicRelationshipRule] = []
    for left_topic in sorted(topics):
        match = LEFT_TOPIC_PATTERN.match(left_topic)
        if not match:
            continue
        right_topic = f"{match.group('prefix')}/right/{match.group('suffix')}"
        rules.append(
            TopicRelationshipRule(
                name=f"auto_stereo:{left_topic}",
                relationship_type="stereo_sync",
                topic_a=left_topic,
                topic_b=right_topic,
            )
        )
    return rules


def compute_relationship_health(
    message_index: pl.DataFrame,
    config: AnalyticsConfig,
    topic_manifest: pl.DataFrame | None = None,
) -> pl.DataFrame:
    """Evaluate configured timestamp pairs and conventional stereo topic pairs."""
    _validate_message_index(message_index)
    if message_index.is_empty() and (topic_manifest is None or topic_manifest.is_empty()):
        return _empty_frame(RELATIONSHIP_HEALTH_SCHEMA)

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

        configured_pairs: set[frozenset[str]] = set()
        for rule in config.topic_relationships:
            configured_pairs.add(frozenset((rule.topic_a, rule.topic_b)))
            if rule.topic_a not in topics and rule.topic_b not in topics:
                continue
            rows.append(_relationship_row(bag_id, bag_partition, rule, config, source="configured"))

        for rule in _automatic_stereo_rules(topics):
            if frozenset((rule.topic_a, rule.topic_b)) in configured_pairs:
                continue
            rows.append(_relationship_row(bag_id, bag_partition, rule, config, source="automatic"))

    return (
        pl.DataFrame(rows, schema=RELATIONSHIP_HEALTH_SCHEMA).sort(["bag_id", "relationship_name"])
        if rows
        else _empty_frame(RELATIONSHIP_HEALTH_SCHEMA)
    )


def _relationship_vslam_rows(relationship_health: pl.DataFrame) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    stereo = relationship_health.filter(pl.col("relationship_type") == "stereo_sync")
    for relationship in stereo.iter_rows(named=True):
        rows.append(
            {
                "bag_id": relationship["bag_id"],
                "check_type": "stereo_sync",
                "topic": f"{relationship['topic_a']} <-> {relationship['topic_b']}",
                "topic_left": relationship["topic_a"],
                "topic_right": relationship["topic_b"],
                "message_count": None,
                "mean_rate_hz": None,
                "max_inter_message_gap_s": None,
                "max_gap_to_mean_interval_ratio": None,
                "left_message_count": relationship["topic_a_message_count"],
                "right_message_count": relationship["topic_b_message_count"],
                "paired_message_count": relationship["paired_message_count"],
                "unmatched_left_count": relationship["unmatched_topic_a_count"],
                "unmatched_right_count": relationship["unmatched_topic_b_count"],
                "max_abs_sync_skew_ns": relationship["max_abs_skew_ns"],
                "p95_abs_sync_skew_ns": relationship["p95_abs_skew_ns"],
                "mean_abs_sync_skew_ns": relationship["mean_abs_skew_ns"],
                "status": relationship["status"],
                "detail": relationship["detail"],
            }
        )
    return rows


def compute_vslam_quality(
    message_index: pl.DataFrame,
    config: AnalyticsConfig,
    topic_manifest: pl.DataFrame | None = None,
    relationship_health: pl.DataFrame | None = None,
) -> pl.DataFrame:
    """Compute continuity and stereo synchronization checks."""
    _validate_message_index(message_index)
    if message_index.is_empty() and (topic_manifest is None or topic_manifest.is_empty()):
        return _empty_frame(VSLAM_QUALITY_SCHEMA)
    relationships = relationship_health
    if relationships is None:
        relationships = compute_relationship_health(message_index, config, topic_manifest)
    rows = _continuity_rows(message_index, config) + _relationship_vslam_rows(relationships)
    return (
        pl.DataFrame(rows, schema=VSLAM_QUALITY_SCHEMA).sort(["bag_id", "check_type", "topic"])
        if rows
        else _empty_frame(VSLAM_QUALITY_SCHEMA)
    )


def analyze_message_index(
    message_index_path: Path,
    output_dir: Path,
    config: AnalyticsConfig,
) -> tuple[pl.DataFrame, pl.DataFrame, pl.DataFrame]:
    """Run all configured analytics and persist their Parquet outputs."""
    message_index = pl.read_parquet(message_index_path)
    topic_manifest = pl.read_parquet(output_dir / "topic_manifest.parquet")
    topic_health = compute_topic_health(message_index, config, topic_manifest)
    relationship_health = compute_relationship_health(message_index, config, topic_manifest)
    vslam_quality = compute_vslam_quality(
        message_index,
        config,
        topic_manifest,
        relationship_health,
    )
    topic_health.write_parquet(output_dir / "topic_health.parquet", compression="zstd")
    vslam_quality.write_parquet(output_dir / "vslam_quality.parquet", compression="zstd")
    relationship_health.write_parquet(
        output_dir / "relationship_health.parquet", compression="zstd"
    )
    return topic_health, vslam_quality, relationship_health


def build_analysis_summary(
    topic_health: pl.DataFrame,
    vslam_quality: pl.DataFrame,
    relationship_health: pl.DataFrame | None = None,
) -> dict[str, Any]:
    topic_statuses = topic_health.get_column("status").to_list() if topic_health.height else []
    if relationship_health is None:
        relationship_statuses: list[str] = []
        quality_statuses = (
            vslam_quality.get_column("status").to_list() if vslam_quality.height else []
        )
    else:
        relationship_statuses = (
            relationship_health.get_column("status").to_list() if relationship_health.height else []
        )
        continuity = vslam_quality.filter(pl.col("check_type") != "stereo_sync")
        quality_statuses = continuity.get_column("status").to_list() if continuity.height else []
    findings: list[dict[str, str]] = []
    for row in topic_health.filter(pl.col("status") != "ok").iter_rows(named=True):
        details: list[str] = []
        if row["message_count"] == 0:
            details.append("no messages were recorded")
        elif row["expected_rate_hz"] is not None and row["mean_rate_hz"] is not None:
            details.append(
                f"mean rate {row['mean_rate_hz']:.3g} Hz vs "
                f"expected {row['expected_rate_hz']:.3g} Hz"
            )
        if row["gap_event_count"]:
            details.append(
                f"{row['gap_event_count']} gap events and approximately "
                f"{row['estimated_dropped_messages']} dropped messages"
            )
        findings.append(
            {
                "source": "topic_health",
                "check": "rate_and_gaps",
                "topic": row["topic"],
                "status": row["status"],
                "detail": "; ".join(details) or "topic health thresholds were not met",
            }
        )

    quality_findings = (
        vslam_quality
        if relationship_health is None
        else vslam_quality.filter(pl.col("check_type") != "stereo_sync")
    )
    for row in quality_findings.filter(pl.col("status") != "ok").iter_rows(named=True):
        topic = row["topic"] or f"{row['topic_left']} <-> {row['topic_right']}"
        findings.append(
            {
                "source": "vslam_quality",
                "check": row["check_type"],
                "topic": topic,
                "status": row["status"],
                "detail": row["detail"],
            }
        )

    if relationship_health is not None:
        for row in relationship_health.filter(pl.col("status") != "ok").iter_rows(named=True):
            findings.append(
                {
                    "source": "relationship_health",
                    "check": row["relationship_name"],
                    "topic": f"{row['topic_a']} <-> {row['topic_b']}",
                    "status": row["status"],
                    "detail": row["detail"],
                }
            )

    findings.sort(
        key=lambda finding: (
            {"error": 0, "warn": 1}.get(finding["status"], 2),
            finding["source"],
            finding["topic"],
        )
    )
    statuses = topic_statuses + quality_statuses + relationship_statuses
    counts = Counter(statuses)
    return {
        "health_status": overall_status(statuses),
        "warning_count": counts["warn"],
        "error_count": counts["error"],
        "topic_health_counts": dict(Counter(topic_statuses)),
        "quality_check_counts": dict(Counter(quality_statuses)),
        "relationship_check_counts": dict(Counter(relationship_statuses)),
        "health_findings": findings[:100],
    }
