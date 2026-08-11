from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from typing import Any

from aiokafka import AIOKafkaConsumer, TopicPartition

from demo.api.store import ProjectionStore


class ProjectionConsumer:
    def __init__(
        self,
        *,
        bootstrap_servers: str,
        store: ProjectionStore,
        on_projected: Callable[[dict[str, Any]], Awaitable[None]],
    ) -> None:
        self.bootstrap_servers = bootstrap_servers
        self.store = store
        self.on_projected = on_projected
        self.consumer: AIOKafkaConsumer | None = None
        self._task: asyncio.Task[None] | None = None

    @property
    def healthy(self) -> bool:
        return self._task is not None and not self._task.done()

    def projection_lag(self) -> int | None:
        if self.consumer is None:
            return None
        stored = self.store.offsets()
        total = 0
        assigned = self.consumer.assignment()
        if not assigned:
            return None
        for partition in assigned:
            highwater = self.consumer.highwater(partition)
            if highwater is None:
                return None
            total += max(
                0,
                highwater - stored.get((partition.topic, partition.partition), 0),
            )
        return total

    async def start(self) -> None:
        self.consumer = AIOKafkaConsumer(
            "telemetry.metrics.v1",
            "telemetry.anomalies.v1",
            bootstrap_servers=self.bootstrap_servers,
            group_id="flight-deck-projection-v1",
            enable_auto_commit=False,
            auto_offset_reset="earliest",
            isolation_level="read_committed",
            value_deserializer=lambda raw: json.loads(raw.decode("utf-8")),
        )
        await self.consumer.start()
        await self._seek_stored_offsets()
        self._task = asyncio.create_task(self._consume(), name="flight-deck-projection")

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        if self.consumer is not None:
            await self.consumer.stop()
            self.consumer = None

    async def _seek_stored_offsets(self) -> None:
        assert self.consumer is not None
        for _attempt in range(50):
            assignment = self.consumer.assignment()
            if assignment:
                break
            await asyncio.sleep(0.1)
        stored = self.store.offsets()
        for partition in self.consumer.assignment():
            offset = stored.get((partition.topic, partition.partition))
            if offset is not None:
                self.consumer.seek(partition, offset)

    async def _consume(self) -> None:
        assert self.consumer is not None
        async for message in self.consumer:
            stream_kind = "metric" if message.topic == "telemetry.metrics.v1" else "anomaly"
            inserted = await asyncio.to_thread(
                self.store.project,
                stream_kind=stream_kind,
                payload=message.value,
                kafka_topic=message.topic,
                kafka_partition=message.partition,
                kafka_offset=message.offset,
            )
            await self.consumer.commit(
                {TopicPartition(message.topic, message.partition): message.offset + 1}
            )
            if inserted:
                await self.on_projected({"stream_kind": stream_kind, "payload": message.value})
