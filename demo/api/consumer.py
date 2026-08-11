from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from aiokafka import AIOKafkaConsumer, TopicPartition

from demo.api.store import ProjectionStore

LOGGER = logging.getLogger(__name__)


class ProjectionConsumer:
    def __init__(
        self,
        *,
        bootstrap_servers: str,
        store: ProjectionStore,
        on_projected: Callable[[dict[str, Any]], Awaitable[None]],
        retry_delay_seconds: float = 1.0,
    ) -> None:
        self.bootstrap_servers = bootstrap_servers
        self.store = store
        self.on_projected = on_projected
        self.retry_delay_seconds = retry_delay_seconds
        self.consumer: AIOKafkaConsumer | None = None
        self._task: asyncio.Task[None] | None = None

    @property
    def healthy(self) -> bool:
        return self._task is not None and not self._task.done() and self.consumer is not None

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
        await self._connect()
        self._task = asyncio.create_task(self._supervise(), name="flight-deck-projection")

    async def _connect(self) -> None:
        consumer = AIOKafkaConsumer(
            "telemetry.metrics.v1",
            "telemetry.anomalies.v1",
            bootstrap_servers=self.bootstrap_servers,
            group_id="flight-deck-projection-v1",
            enable_auto_commit=False,
            auto_offset_reset="earliest",
            isolation_level="read_committed",
            value_deserializer=lambda raw: json.loads(raw.decode("utf-8")),
        )
        try:
            await consumer.start()
            self.consumer = consumer
            await self._seek_stored_offsets()
        except (Exception, asyncio.CancelledError):
            if self.consumer is consumer:
                self.consumer = None
            await consumer.stop()
            raise

    async def _disconnect(self) -> None:
        consumer = self.consumer
        self.consumer = None
        if consumer is not None:
            await consumer.stop()

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        await self._disconnect()

    async def _supervise(self) -> None:
        while True:
            try:
                if self.consumer is None:
                    await self._connect()
                await self._consume()
                raise RuntimeError("Kafka projection consumer stopped unexpectedly")
            except asyncio.CancelledError:
                raise
            except Exception:
                LOGGER.exception("Kafka projection failed; reconnecting from the stored offsets")
                try:
                    await self._disconnect()
                except Exception:
                    LOGGER.exception("Failed to close the unhealthy Kafka consumer")
                await asyncio.sleep(self.retry_delay_seconds)

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
