"""Capture a bounded Kafka offset snapshot for one live run without committing offsets."""

from __future__ import annotations

import argparse
import asyncio
import json
import time
from pathlib import Path


async def capture(bootstrap: str, run_id: str, timeout_s: float) -> dict:
    from aiokafka import AIOKafkaConsumer

    topics = [
        f"telemetry.{kind}.v1" for kind in ("events", "metrics", "anomalies", "late", "dead-letter")
    ]
    consumer = AIOKafkaConsumer(
        *topics,
        bootstrap_servers=bootstrap,
        group_id=None,
        enable_auto_commit=False,
        auto_offset_reset="earliest",
        isolation_level="read_committed",
    )
    await consumer.start()
    try:
        partitions = sorted(consumer.assignment(), key=lambda p: (p.topic, p.partition))
        if {p.topic for p in partitions} != set(topics):
            raise RuntimeError("Kafka did not assign all requested evidence topics")
        beginnings = await consumer.beginning_offsets(partitions)
        for partition, offset in beginnings.items():
            consumer.seek(partition, offset)
        ends = await consumer.end_offsets(partitions)
        records = {topic: [] for topic in topics}
        deadline = time.monotonic() + timeout_s
        while True:
            remaining = [p for p in partitions if await consumer.position(p) < ends[p]]
            if not remaining:
                break
            if time.monotonic() >= deadline:
                raise TimeoutError("Kafka capture did not reach its frozen offset boundary")
            batches = await consumer.getmany(*remaining, timeout_ms=200, max_records=2000)
            for partition, messages in batches.items():
                for message in messages:
                    if message.offset >= ends[partition]:
                        continue
                    value = json.loads(message.value)
                    embedded_run = None
                    if isinstance(value.get("raw_value"), str):
                        try:
                            embedded_run = json.loads(value["raw_value"]).get("run_id")
                        except (ValueError, AttributeError):
                            pass
                    if value.get("run_id") == run_id or embedded_run == run_id:
                        records[partition.topic].append(
                            {
                                "partition": partition.partition,
                                "offset": message.offset,
                                "broker_timestamp_ms": message.timestamp,
                                "value": value,
                            }
                        )
        return {
            "run_id": run_id,
            "isolation_level": "read_committed",
            "snapshot_start_offsets": {
                f"{p.topic}:{p.partition}": n for p, n in beginnings.items()
            },
            "snapshot_end_offsets": {f"{p.topic}:{p.partition}": n for p, n in ends.items()},
            "records": records,
        }
    finally:
        await consumer.stop()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bootstrap-servers", default="kafka:9092")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--timeout-s", type=float, default=30)
    args = parser.parse_args()
    result = asyncio.run(capture(args.bootstrap_servers, args.run_id, args.timeout_s))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, sort_keys=True, indent=2) + "\n")
    print(json.dumps({k: len(v) for k, v in result["records"].items()}, sort_keys=True))


if __name__ == "__main__":
    main()
