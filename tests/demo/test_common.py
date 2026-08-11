from __future__ import annotations

import json
from pathlib import Path

import polars as pl
import pytest
from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from demo.common.analytics import topic_summary
from demo.common.config import load_streaming_config
from demo.common.contracts import (
    StreamEpochAllocator,
    envelope,
    telemetry_event,
    topic_registration_envelope,
)
from ros_telemetry_analytics.analysis import compute_topic_health
from ros_telemetry_analytics.config import AnalyticsConfig, RateRule

ROOT = Path(__file__).resolve().parents[2]
HEALTH_CONTRACT = json.loads(
    (ROOT / "configs/health_math_contract_cases.json").read_text(encoding="utf-8")
)


def test_streaming_config_captures_demo_contract() -> None:
    config = load_streaming_config(ROOT / "configs/streaming_demo.yaml")

    assert config.demo.duration_s == 90
    assert config.demo.supported_rates == (1, 5)
    assert config.flink.state_ttl_minutes == 12
    assert config.kafka.topics["telemetry.events.v1"] == 4
    assert {topic.topic for topic in config.analytics.expected_topics} == {
        "/camera/image_raw",
        "/imu/data",
        "/odom",
        "/diagnostics",
    }


def test_stream_epoch_allocator_is_monotonic_across_instances(tmp_path: Path) -> None:
    state_path = tmp_path / "epoch.json"
    first = StreamEpochAllocator(state_path).allocate(90_000, 10_000, clock_ms=1_000)
    second = StreamEpochAllocator(state_path).allocate(90_000, 10_000, clock_ms=500)

    assert second.start_ms == first.reserved_end_ms + 1_000


def test_event_ids_are_deterministic_and_source_time_is_preserved() -> None:
    arguments = {
        "run_id": "run-1",
        "robot_id": "robot-17",
        "bag_id": "warehouse-run-17",
        "sequence": 42,
        "topic": "/odom",
        "message_type": "nav_msgs/msg/Odometry",
        "event_timestamp_ns": 1_700_000_000_000_000_000,
        "stream_timestamp_ms": 2_000,
        "ingest_timestamp_ms": 3_000,
    }

    first = telemetry_event(**arguments)
    second = telemetry_event(**arguments)

    assert first["event_id"] == second["event_id"]
    assert first["event_timestamp_ns"] == arguments["event_timestamp_ns"]
    assert first["stream_timestamp_ms"] == 2_000


def test_registration_carries_expected_topic_contract() -> None:
    config = load_streaming_config(ROOT / "configs/streaming_demo.yaml")
    registration = topic_registration_envelope(
        run_id="run-1",
        robot_id=config.demo.robot_id,
        topic_spec=config.analytics.expected_topics[0],
        source_start_ns=1_000,
        stream_start_ms=2_000,
        startup_grace_ms=config.analytics.startup_grace_ms,
    )

    assert registration["envelope_type"] == "topic_registered"
    assert registration["body"]["expected_rate_hz"] == 30


def test_topic_summary_handles_never_seen_topic() -> None:
    result = topic_summary([], expected_rate_hz=30)

    assert result["message_count"] == 0
    assert result["rate_ratio"] == 0.0
    assert result["status"] == "error"


def test_streaming_summary_matches_batch_oracle() -> None:
    timestamps = [0, 1_000_000_000, 2_000_000_000, 4_000_000_000]
    frame = pl.DataFrame(
        {
            "bag_id": ["bag"] * len(timestamps),
            "sequence": list(range(len(timestamps))),
            "topic": ["/diagnostics"] * len(timestamps),
            "timestamp_ns": timestamps,
        }
    )
    config = AnalyticsConfig(
        rate_rules=(RateRule(pattern=r"^/diagnostics$", expected_rate_hz=1.0),),
        gap_threshold_multiplier=1.5,
        minimum_rate_ratio=0.8,
        maximum_rate_ratio=1.2,
    )
    batch = compute_topic_health(frame, config).row(0, named=True)
    streaming = topic_summary(timestamps, expected_rate_hz=1.0)

    comparable = {
        "message_count",
        "mean_rate_hz",
        "rate_ratio",
        "max_inter_message_gap_s",
        "gap_event_count",
        "estimated_dropped_messages",
        "status",
    }
    for key in comparable:
        assert (
            streaming[key] == pytest.approx(batch[key])
            if isinstance(batch[key], float)
            else streaming[key] == batch[key]
        )


@pytest.mark.parametrize(
    "case",
    HEALTH_CONTRACT["cases"],
    ids=lambda case: case["name"],
)
def test_python_summary_matches_shared_java_formula_cases(case: dict[str, object]) -> None:
    actual = topic_summary(
        case["timestamps_ns"],
        expected_rate_hz=case["expected_rate_hz"],
        gap_threshold_multiplier=HEALTH_CONTRACT["gap_threshold_multiplier"],
        minimum_rate_ratio=HEALTH_CONTRACT["minimum_rate_ratio"],
        maximum_rate_ratio=HEALTH_CONTRACT["maximum_rate_ratio"],
    )
    expected = case["expected"]
    for key, value in expected.items():
        if isinstance(value, float):
            assert actual[key] == pytest.approx(value)
        else:
            assert actual[key] == value


@pytest.mark.parametrize(
    "schema_name",
    [
        "telemetry-event-v1.schema.json",
        "telemetry-envelope-v1.schema.json",
        "telemetry-metric-v1.schema.json",
        "telemetry-anomaly-v1.schema.json",
    ],
)
def test_schemas_are_valid_json(schema_name: str) -> None:
    payload = json.loads((ROOT / "schemas" / schema_name).read_text(encoding="utf-8"))
    assert payload["$schema"] == "https://json-schema.org/draft/2020-12/schema"


def test_generated_telemetry_envelope_satisfies_versioned_contracts() -> None:
    event_schema = json.loads(
        (ROOT / "schemas/telemetry-event-v1.schema.json").read_text(encoding="utf-8")
    )
    envelope_schema = json.loads(
        (ROOT / "schemas/telemetry-envelope-v1.schema.json").read_text(encoding="utf-8")
    )
    registry = Registry().with_resource(event_schema["$id"], Resource.from_contents(event_schema))
    event = telemetry_event(
        run_id="run-1",
        robot_id="robot-17",
        bag_id="warehouse-run-17",
        sequence=1,
        topic="/odom",
        message_type="nav_msgs/msg/Odometry",
        event_timestamp_ns=1_700_000_000_000_000_000,
        stream_timestamp_ms=2_000,
        ingest_timestamp_ms=3_000,
        attributes={"payload_size_bytes": 128},
    )
    wrapped = envelope(
        envelope_type="telemetry",
        run_id="run-1",
        robot_id="robot-17",
        topic="/odom",
        event_timestamp_ns=event["event_timestamp_ns"],
        stream_timestamp_ms=event["stream_timestamp_ms"],
        ingest_timestamp_ms=3_000,
        body=event,
        ordinal=1,
    )

    Draft202012Validator(event_schema).validate(event)
    Draft202012Validator(envelope_schema, registry=registry).validate(wrapped)
