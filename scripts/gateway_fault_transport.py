"""Test-only transport shim: repeat or hold selected envelopes after DDS reception.

The delay shim acknowledges its in-memory handoff before Kafka delivery. It is an
intentional fault fixture, not the gateway's durable delivery implementation.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from pathlib import Path

from demo.gateway import ros_node
from demo.replayer.kafka import KafkaEnvelopePublisher


class FaultPublisher(KafkaEnvelopePublisher):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.start_ms = None
        self.injections = []
        self.pending = []
        self.mode = os.environ["STREAM_FAULT"]
        self.fault_start_ms = float(os.getenv("STREAM_FAULT_START_S", "12")) * 1000
        self.output = Path("/validation/injections.json")

    async def publish(self, key, value):
        if value["envelope_type"] == "run_started":
            self.start_ms = value["stream_timestamp_ms"]
        selected = (
            value["envelope_type"] == "telemetry"
            and value["topic"] == "/scan"
            and self.start_ms is not None
            and value["stream_timestamp_ms"] - self.start_ms >= self.fault_start_ms
            and len(self.injections) < 10
        )
        if not selected:
            if value["envelope_type"] == "run_ended" and self.pending:
                await asyncio.gather(*self.pending)
            return await super().publish(key, value)
        record = {
            "event_id": value["body"]["event_id"],
            "envelope_id": value["envelope_id"],
            "stream_timestamp_ms": value["stream_timestamp_ms"],
            "handoff_wall_ns": time.time_ns(),
            "mode": self.mode,
        }
        self.injections.append(record)
        self.save()
        if self.mode == "duplicate":
            await super().publish(key, value)
            await super().publish(key, value)
            record["completed_wall_ns"] = time.time_ns()
            self.save()
        else:
            self.pending.append(asyncio.create_task(self.delayed(key, value, record)))

    async def delayed(self, key, value, record):
        await asyncio.sleep(10)
        await super().publish(key, value)
        record["completed_wall_ns"] = time.time_ns()
        self.save()

    def save(self):
        self.output.write_text(json.dumps(self.injections, indent=2) + "\n")

    async def stop(self):
        try:
            if self.pending:
                await asyncio.gather(*self.pending)
        finally:
            await super().stop()


if __name__ == "__main__":
    ros_node.KafkaEnvelopePublisher = FaultPublisher
    ros_node.main()
