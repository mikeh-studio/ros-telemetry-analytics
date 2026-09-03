from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class TopicSpec:
    topic: str
    message_type: str
    expected_rate_hz: float
    dropout_threshold_ms: int
    rate_monitoring_enabled: bool = True


@dataclass(frozen=True)
class AnalyticsSpec:
    window_size_ms: int
    window_slide_ms: int
    recovery_gate_ms: int
    maximum_out_of_orderness_ms: int
    allowed_lateness_ms: int
    idle_partition_timeout_ms: int
    startup_grace_ms: int
    whole_robot_silence_ms: int
    minimum_rate_ratio: float
    maximum_rate_ratio: float
    gap_threshold_multiplier: float
    expected_topics: tuple[TopicSpec, ...]


@dataclass(frozen=True)
class DemoSpec:
    robot_id: str
    bag_id: str
    fixture_path: Path
    duration_s: int
    default_rate: int
    supported_rates: tuple[int, ...]


@dataclass(frozen=True)
class KafkaSpec:
    bootstrap_servers: str
    retention_ms: int
    topics: dict[str, int]


@dataclass(frozen=True)
class FlinkSpec:
    state_ttl_minutes: int
    checkpoint_interval_ms: int
    checkpoint_min_pause_ms: int
    checkpoint_timeout_ms: int
    restart_attempts: int
    restart_delay_ms: int
    kafka_transaction_timeout_ms: int


@dataclass(frozen=True)
class StreamingConfig:
    schema_version: int
    demo: DemoSpec
    analytics: AnalyticsSpec
    kafka: KafkaSpec
    flink: FlinkSpec

    @property
    def topics_by_name(self) -> dict[str, TopicSpec]:
        return {item.topic: item for item in self.analytics.expected_topics}


def _positive_int(raw: dict[str, Any], name: str) -> int:
    value = int(raw[name])
    if value <= 0:
        raise ValueError(f"{name} must be greater than zero")
    return value


def _positive_float(raw: dict[str, Any], name: str) -> float:
    value = float(raw[name])
    if value <= 0:
        raise ValueError(f"{name} must be greater than zero")
    return value


def load_streaming_config(path: Path) -> StreamingConfig:
    path = path.expanduser().resolve()
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if raw.get("schema_version") != 1:
        raise ValueError("streaming demo config requires schema_version: 1")

    demo_raw = raw["demo"]
    analytics_raw = raw["analytics"]
    kafka_raw = raw["kafka"]
    flink_raw = raw["flink"]

    topics = tuple(
        TopicSpec(
            topic=str(item["topic"]),
            message_type=str(item["message_type"]),
            expected_rate_hz=_positive_float(item, "expected_rate_hz"),
            dropout_threshold_ms=_positive_int(item, "dropout_threshold_ms"),
        )
        for item in analytics_raw["expected_topics"]
    )
    if len({item.topic for item in topics}) != len(topics):
        raise ValueError("expected topic names must be unique")

    minimum_ratio = _positive_float(analytics_raw, "minimum_rate_ratio")
    maximum_ratio = _positive_float(analytics_raw, "maximum_rate_ratio")
    if minimum_ratio > maximum_ratio:
        raise ValueError("minimum_rate_ratio cannot exceed maximum_rate_ratio")

    supported_rates = tuple(int(value) for value in demo_raw["supported_rates"])
    if not supported_rates or any(value <= 0 for value in supported_rates):
        raise ValueError("supported replay rates must be positive")
    default_rate = int(demo_raw["default_rate"])
    if default_rate not in supported_rates:
        raise ValueError("default replay rate must be supported")

    return StreamingConfig(
        schema_version=1,
        demo=DemoSpec(
            robot_id=str(demo_raw["robot_id"]),
            bag_id=str(demo_raw["bag_id"]),
            fixture_path=Path(demo_raw["fixture_path"]),
            duration_s=_positive_int(demo_raw, "duration_s"),
            default_rate=default_rate,
            supported_rates=supported_rates,
        ),
        analytics=AnalyticsSpec(
            window_size_ms=_positive_int(analytics_raw, "window_size_ms"),
            window_slide_ms=_positive_int(analytics_raw, "window_slide_ms"),
            recovery_gate_ms=_positive_int(analytics_raw, "recovery_gate_ms"),
            maximum_out_of_orderness_ms=_positive_int(analytics_raw, "maximum_out_of_orderness_ms"),
            allowed_lateness_ms=_positive_int(analytics_raw, "allowed_lateness_ms"),
            idle_partition_timeout_ms=_positive_int(analytics_raw, "idle_partition_timeout_ms"),
            startup_grace_ms=_positive_int(analytics_raw, "startup_grace_ms"),
            whole_robot_silence_ms=_positive_int(analytics_raw, "whole_robot_silence_ms"),
            minimum_rate_ratio=minimum_ratio,
            maximum_rate_ratio=maximum_ratio,
            gap_threshold_multiplier=_positive_float(analytics_raw, "gap_threshold_multiplier"),
            expected_topics=topics,
        ),
        kafka=KafkaSpec(
            bootstrap_servers=str(kafka_raw["bootstrap_servers"]),
            retention_ms=_positive_int(kafka_raw, "retention_ms"),
            topics={str(name): int(partitions) for name, partitions in kafka_raw["topics"].items()},
        ),
        flink=FlinkSpec(
            state_ttl_minutes=_positive_int(flink_raw, "state_ttl_minutes"),
            checkpoint_interval_ms=_positive_int(flink_raw, "checkpoint_interval_ms"),
            checkpoint_min_pause_ms=_positive_int(flink_raw, "checkpoint_min_pause_ms"),
            checkpoint_timeout_ms=_positive_int(flink_raw, "checkpoint_timeout_ms"),
            restart_attempts=_positive_int(flink_raw, "restart_attempts"),
            restart_delay_ms=_positive_int(flink_raw, "restart_delay_ms"),
            kafka_transaction_timeout_ms=_positive_int(flink_raw, "kafka_transaction_timeout_ms"),
        ),
    )
