from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from demo.common.config import TopicSpec

EnvelopeType = Literal[
    "run_started",
    "topic_registered",
    "telemetry",
    "run_paused",
    "run_resumed",
    "run_aborted",
    "run_failed",
    "run_ended",
    "watermark_flush",
]


def deterministic_id(*parts: object) -> str:
    encoded = "\x1f".join(str(part) for part in parts).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def now_ms() -> int:
    return time.time_ns() // 1_000_000


@dataclass(frozen=True)
class StreamEpoch:
    start_ms: int
    reserved_end_ms: int


class StreamEpochAllocator:
    """Persist non-overlapping event-time epochs across replay and container restarts."""

    def __init__(self, state_path: Path) -> None:
        self.state_path = state_path

    def allocate(
        self, mission_span_ms: int, flush_padding_ms: int, *, clock_ms: int
    ) -> StreamEpoch:
        if mission_span_ms <= 0 or flush_padding_ms < 0:
            raise ValueError("mission span must be positive and padding cannot be negative")
        previous_end = self._read_previous_end()
        start_ms = max(clock_ms, previous_end + 1_000)
        reserved_end_ms = start_ms + mission_span_ms + flush_padding_ms
        self._write_end(reserved_end_ms)
        return StreamEpoch(start_ms=start_ms, reserved_end_ms=reserved_end_ms)

    def _read_previous_end(self) -> int:
        try:
            payload = json.loads(self.state_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return -1
        except (json.JSONDecodeError, OSError) as exc:
            raise RuntimeError(f"Cannot read replay epoch state: {self.state_path}") from exc
        return int(payload["last_allocated_stream_end_ms"])

    def _write_end(self, value: int) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.state_path.with_suffix(f"{self.state_path.suffix}.tmp")
        temporary.write_text(
            json.dumps({"last_allocated_stream_end_ms": value}, sort_keys=True),
            encoding="utf-8",
        )
        os.replace(temporary, self.state_path)


def telemetry_event(
    *,
    run_id: str,
    robot_id: str,
    bag_id: str,
    sequence: int,
    topic: str,
    message_type: str,
    event_timestamp_ns: int,
    stream_timestamp_ms: int,
    attributes: dict[str, str | int | float | bool | None] | None = None,
    ingest_timestamp_ms: int | None = None,
) -> dict[str, Any]:
    event_id = deterministic_id(1, run_id, bag_id, sequence)
    return {
        "schema_version": 1,
        "event_id": event_id,
        "run_id": run_id,
        "robot_id": robot_id,
        "bag_id": bag_id,
        "sequence": sequence,
        "topic": topic,
        "message_type": message_type,
        "event_timestamp_ns": event_timestamp_ns,
        "stream_timestamp_ms": stream_timestamp_ms,
        "ingest_timestamp_ms": ingest_timestamp_ms or now_ms(),
        "source_mode": "recorded_replay",
        "attributes": attributes or {},
    }


def envelope(
    *,
    envelope_type: EnvelopeType,
    run_id: str,
    robot_id: str,
    topic: str | None,
    event_timestamp_ns: int,
    stream_timestamp_ms: int,
    body: dict[str, Any],
    ordinal: object,
    ingest_timestamp_ms: int | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "envelope_id": deterministic_id(
            1, run_id, robot_id, topic or "__robot__", envelope_type, ordinal
        ),
        "envelope_type": envelope_type,
        "run_id": run_id,
        "robot_id": robot_id,
        "topic": topic,
        "event_timestamp_ns": event_timestamp_ns,
        "stream_timestamp_ms": stream_timestamp_ms,
        "ingest_timestamp_ms": ingest_timestamp_ms or now_ms(),
        "body": body,
    }


def topic_registration_envelope(
    *,
    run_id: str,
    robot_id: str,
    topic_spec: TopicSpec,
    source_start_ns: int,
    stream_start_ms: int,
    startup_grace_ms: int,
) -> dict[str, Any]:
    return envelope(
        envelope_type="topic_registered",
        run_id=run_id,
        robot_id=robot_id,
        topic=topic_spec.topic,
        event_timestamp_ns=source_start_ns,
        stream_timestamp_ms=stream_start_ms,
        ordinal=topic_spec.topic,
        body={
            "message_type": topic_spec.message_type,
            "expected_rate_hz": topic_spec.expected_rate_hz,
            "startup_grace_ms": startup_grace_ms,
            "dropout_threshold_ms": topic_spec.dropout_threshold_ms,
        },
    )
