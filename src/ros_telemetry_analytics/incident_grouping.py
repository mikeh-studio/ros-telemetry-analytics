"""Stable recording-event identity and conservative, non-causal grouping."""

from __future__ import annotations

import hashlib
import json
from collections import Counter

GROUPING_VERSION = "recording-overlap-v1"
IMAGE_TYPES = frozenset({"dark_frames", "bright_frames", "low_sharpness"})


def digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def event_key(event: dict) -> str:
    """Exclude presentation prose and publication IDs from the detector identity."""
    return digest(
        {
            key: str(event[key]) if key.endswith("timestamp_ns") else event.get(key)
            for key in (
                "bag_id",
                "domain",
                "topic",
                "robot_id",
                "start_timestamp_ns",
                "end_timestamp_ns",
                "event_type",
                "observed_value",
                "threshold",
                "unit",
            )
        }
    )


def normalize_events(events: list[dict], source_sha256: str) -> list[dict]:
    occurrences: Counter = Counter()
    output = []
    for original in sorted(events, key=lambda e: (event_key(e), e.get("detail", ""))):
        key = event_key(original)
        ordinal = occurrences[key]
        occurrences[key] += 1
        event = {k: v for k, v in original.items() if not k.startswith("_")}
        event.update(event_key=key, event_id=digest([source_sha256, key, ordinal]))
        for field in ("start_timestamp_ns", "end_timestamp_ns"):
            event[field] = str(event[field])
        output.append(event)
    return sorted(output, key=event_order)


def event_order(event: dict) -> tuple:
    return (
        int(event["start_timestamp_ns"]),
        int(event["end_timestamp_ns"]),
        event["event_type"],
        event["topic"],
        event["event_id"],
    )


def family(event: dict) -> str:
    kind = event["event_type"]
    if kind in IMAGE_TYPES:
        return "image_content"
    if kind in {"recorded_gap", "reference_gap"}:
        return kind
    if kind == "command_without_motion":
        return "motion_disagreement"
    return "unsupported"


def group_events(events: list[dict], max_span_ns: int = 10_000_000_000) -> list[list[dict]]:
    """Only same-topic image events can merge; every member must overlap the seed."""
    groups: list[list[dict]] = []
    for event in sorted(events, key=event_order):
        start, end = int(event["start_timestamp_ns"]), int(event["end_timestamp_ns"])
        if end < start:
            raise ValueError("Event ends before it starts")
        target = None
        if family(event) == "image_content":
            for group in groups:
                seed = group[0]
                if (
                    family(seed) != "image_content"
                    or seed["topic"] != event["topic"]
                    or seed.get("robot_id") != event.get("robot_id")
                    or seed.get("bag_id") != event.get("bag_id")
                ):
                    continue
                lo = int(seed["start_timestamp_ns"])
                hi = max(end, *(int(e["end_timestamp_ns"]) for e in group))
                if start <= int(seed["end_timestamp_ns"]) and hi - lo <= max_span_ns:
                    target = group
                    break
        if target is None:
            groups.append([event])
        else:
            target.append(event)
    return groups
