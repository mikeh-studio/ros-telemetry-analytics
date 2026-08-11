#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import re
import sys
import time
from pathlib import Path

import polars as pl

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT))

from demo.api.store import ProjectionStore  # noqa: E402
from demo.common.config import StreamingConfig, load_streaming_config  # noqa: E402
from demo.replayer.engine import load_recorded_messages  # noqa: E402
from ros_telemetry_analytics.analysis import compute_topic_health  # noqa: E402
from ros_telemetry_analytics.config import AnalyticsConfig, RateRule  # noqa: E402


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compare durable Flink mission summaries with the clean recorded-bag oracle."
    )
    parser.add_argument("run_id")
    parser.add_argument("--root", type=Path, default=REPOSITORY_ROOT)
    parser.add_argument("--timeout", type=int, default=60)
    return parser.parse_args()


def _durable_summaries(output_root: Path, run_id: str) -> dict[str, dict]:
    records: dict[str, dict] = {}
    for part in (output_root / run_id / "topic_health").glob("**/part-*"):
        for line in part.read_text(encoding="utf-8").splitlines():
            payload = json.loads(line)
            topic = str(payload["topic"])
            if topic in records:
                raise AssertionError(f"duplicate durable summary for {topic}")
            records[topic] = payload
    return records


def _batch_topic_health(root: Path, config: StreamingConfig) -> dict[str, dict]:
    records = load_recorded_messages(root / config.demo.fixture_path)
    message_index = pl.DataFrame(
        {
            "bag_id": [config.demo.bag_id] * len(records),
            "sequence": [record.sequence for record in records],
            "topic": [record.topic for record in records],
            "timestamp_ns": [record.source_timestamp_ns for record in records],
        }
    )
    analytics = AnalyticsConfig(
        rate_rules=tuple(
            RateRule(
                pattern=rf"^{re.escape(topic.topic)}$",
                expected_rate_hz=topic.expected_rate_hz,
            )
            for topic in config.analytics.expected_topics
        ),
        gap_threshold_multiplier=config.analytics.gap_threshold_multiplier,
        minimum_rate_ratio=config.analytics.minimum_rate_ratio,
        maximum_rate_ratio=config.analytics.maximum_rate_ratio,
    )
    result = compute_topic_health(message_index, analytics)
    return {str(row["topic"]): row for row in result.iter_rows(named=True)}


def compare(root: Path, run_id: str, timeout: int) -> dict[str, object]:
    config = load_streaming_config(root / "configs/streaming_demo.yaml")
    output_root = root / "data/demo-output"
    store = ProjectionStore(root / "demo-state/projection.db", output_root)
    deadline = time.monotonic() + timeout
    while True:
        completion = store.completion(run_id)
        if completion["verified"]:
            break
        if time.monotonic() >= deadline:
            raise TimeoutError(
                f"run {run_id} did not reach persisted completed state: {completion}"
            )
        time.sleep(1)

    durable_contract = store.verify_completion(run_id)
    if not durable_contract["verified"]:
        raise AssertionError(
            f"run {run_id} no longer satisfies the durable summary contract: {durable_contract}"
        )

    observed = _durable_summaries(output_root, run_id)
    expected_by_topic = _batch_topic_health(root, config)

    float_fields = {"mean_rate_hz", "max_inter_message_gap_s"}
    exact_fields = {
        "message_count",
        "first_timestamp_ns",
        "last_timestamp_ns",
        "estimated_dropped_messages",
        "status",
    }
    comparisons: dict[str, dict[str, object]] = {}
    for topic, expected in expected_by_topic.items():
        actual = observed[topic]["payload"]
        for field in exact_fields:
            if actual.get(field) != expected.get(field):
                raise AssertionError(
                    f"{topic} {field}: Flink={actual.get(field)!r}, batch={expected.get(field)!r}"
                )
        for field in float_fields:
            if not math.isclose(
                float(actual[field]), float(expected[field]), rel_tol=1e-9, abs_tol=1e-9
            ):
                raise AssertionError(
                    f"{topic} {field}: Flink={actual[field]!r}, batch={expected[field]!r}"
                )
        comparisons[topic] = {
            field: actual.get(field) for field in sorted(exact_fields | float_fields)
        }
    return {"run_id": run_id, "status": "passed", "topics": comparisons}


def main() -> None:
    args = _arguments()
    result = compare(args.root.resolve(), args.run_id, args.timeout)
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
