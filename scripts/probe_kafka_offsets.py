"""Read a frozen metrics/anomalies offset boundary without changing consumers."""

import argparse
import asyncio
import json
import time


async def main(baseline):
    from aiokafka import AIOKafkaConsumer

    consumer = AIOKafkaConsumer(
        "telemetry.metrics.v1",
        "telemetry.anomalies.v1",
        bootstrap_servers="kafka:9092",
        group_id=None,
        enable_auto_commit=False,
        isolation_level="read_committed",
    )
    await consumer.start()
    try:
        ends = await consumer.end_offsets(consumer.assignment())
        boundary = {
            f"{p.topic}:{p.partition}": baseline.get(f"{p.topic}:{p.partition}", 0) for p in ends
        }
        for partition in ends:
            consumer.seek(partition, boundary[f"{partition.topic}:{partition.partition}"])
        deadline = time.monotonic() + 20
        while any([await consumer.position(p) < end for p, end in ends.items()]):
            if time.monotonic() > deadline:
                raise TimeoutError("Committed capture did not reach the frozen broker boundary")
            batches = await consumer.getmany(timeout_ms=200, max_records=2000)
            for partition, records in batches.items():
                key = f"{partition.topic}:{partition.partition}"
                for record in records:
                    if record.offset < ends[partition]:
                        boundary[key] = max(boundary[key], record.offset + 1)
        print(json.dumps(boundary))
    finally:
        await consumer.stop()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", required=True)
    args = parser.parse_args()
    asyncio.run(main(json.loads(args.baseline)))
