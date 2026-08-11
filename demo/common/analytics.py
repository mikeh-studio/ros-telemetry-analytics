from __future__ import annotations

import math
from typing import Any


def nearest_rank(values: list[int], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return float(ordered[max(0, math.ceil(percentile * len(ordered)) - 1)])


def topic_summary(
    timestamps_ns: list[int],
    *,
    expected_rate_hz: float | None,
    gap_threshold_multiplier: float = 1.5,
    minimum_rate_ratio: float = 0.8,
    maximum_rate_ratio: float = 1.2,
) -> dict[str, Any]:
    timestamps = sorted(int(value) for value in timestamps_ns)
    count = len(timestamps)
    if not timestamps:
        return {
            "message_count": 0,
            "first_timestamp_ns": None,
            "last_timestamp_ns": None,
            "duration_s": None,
            "mean_rate_hz": None,
            "expected_rate_hz": expected_rate_hz,
            "rate_ratio": 0.0 if expected_rate_hz else None,
            "max_inter_message_gap_s": None,
            "p95_inter_message_gap_s": None,
            "gap_threshold_s": (
                gap_threshold_multiplier / expected_rate_hz if expected_rate_hz else None
            ),
            "gap_event_count": 0,
            "estimated_dropped_messages": 0,
            "status": "error",
        }

    first_timestamp = timestamps[0]
    last_timestamp = timestamps[-1]
    duration_ns = last_timestamp - first_timestamp
    duration_s = duration_ns / 1_000_000_000
    gaps_ns = [
        current - previous for previous, current in zip(timestamps, timestamps[1:], strict=False)
    ]
    mean_rate = (count - 1) * 1_000_000_000 / duration_ns if count > 1 and duration_ns else None
    rate_ratio = (
        mean_rate / expected_rate_hz if mean_rate is not None and expected_rate_hz else None
    )
    gap_threshold_s = gap_threshold_multiplier / expected_rate_hz if expected_rate_hz else None
    gap_threshold_ns = gap_threshold_s * 1_000_000_000 if gap_threshold_s else None
    gap_count = sum(gap > gap_threshold_ns for gap in gaps_ns) if gap_threshold_ns else 0
    estimated_drops = (
        max(0, round(duration_s * expected_rate_hz) + 1 - count)
        if expected_rate_hz and duration_ns > 0
        else 0
    )

    if count > 1 and duration_ns == 0:
        status = "error"
    elif count == 1:
        status = "warn"
    elif gap_count or (
        rate_ratio is not None and not minimum_rate_ratio <= rate_ratio <= maximum_rate_ratio
    ):
        status = "warn"
    else:
        status = "ok"

    return {
        "message_count": count,
        "first_timestamp_ns": first_timestamp,
        "last_timestamp_ns": last_timestamp,
        "duration_s": duration_s,
        "mean_rate_hz": mean_rate,
        "expected_rate_hz": expected_rate_hz,
        "rate_ratio": rate_ratio,
        "max_inter_message_gap_s": max(gaps_ns) / 1_000_000_000 if gaps_ns else None,
        "p95_inter_message_gap_s": (
            nearest_rank(gaps_ns, 0.95) / 1_000_000_000 if gaps_ns else None
        ),
        "gap_threshold_s": gap_threshold_s,
        "gap_event_count": gap_count,
        "estimated_dropped_messages": estimated_drops,
        "status": status,
    }
