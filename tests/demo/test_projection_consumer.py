from __future__ import annotations

import asyncio
from typing import Any

from aiokafka import TopicPartition

import demo.api.consumer as consumer_module
from demo.api.consumer import ProjectionConsumer


class _Store:
    def offsets(self) -> dict[tuple[str, int], int]:
        return {("telemetry.metrics.v1", 0): 17}


class _FakeKafkaConsumer:
    def __init__(self) -> None:
        self.started = False
        self.stopped = False
        self.seek_calls: list[tuple[TopicPartition, int]] = []

    async def start(self) -> None:
        self.started = True

    async def stop(self) -> None:
        self.stopped = True

    def assignment(self) -> set[TopicPartition]:
        return {TopicPartition("telemetry.metrics.v1", 0)}

    def seek(self, partition: TopicPartition, offset: int) -> None:
        self.seek_calls.append((partition, offset))


def test_processing_failure_reconnects_and_reseeks_stored_offset(monkeypatch: Any) -> None:
    created: list[_FakeKafkaConsumer] = []

    def consumer_factory(*_args: Any, **_kwargs: Any) -> _FakeKafkaConsumer:
        consumer = _FakeKafkaConsumer()
        created.append(consumer)
        return consumer

    monkeypatch.setattr(consumer_module, "AIOKafkaConsumer", consumer_factory)

    async def exercise() -> None:
        resumed = asyncio.Event()
        consume_calls = 0

        async def on_projected(_event: dict[str, Any]) -> None:
            return None

        projection = ProjectionConsumer(
            bootstrap_servers="kafka:9092",
            store=_Store(),  # type: ignore[arg-type]
            on_projected=on_projected,
            retry_delay_seconds=0,
        )

        async def consume() -> None:
            nonlocal consume_calls
            consume_calls += 1
            if consume_calls == 1:
                raise RuntimeError("temporary projection failure")
            resumed.set()
            await asyncio.Event().wait()

        projection._consume = consume  # type: ignore[method-assign]

        await projection.start()
        await asyncio.wait_for(resumed.wait(), timeout=1)

        assert projection.healthy is True
        assert len(created) == 2
        assert created[0].stopped is True
        assert created[1].started is True
        assert created[1].seek_calls == [(TopicPartition("telemetry.metrics.v1", 0), 17)]

        await projection.stop()
        assert projection.healthy is False
        assert created[1].stopped is True

    asyncio.run(exercise())


class _BlockingStartKafkaConsumer(_FakeKafkaConsumer):
    def __init__(self, reconnect_started: asyncio.Event) -> None:
        super().__init__()
        self.reconnect_started = reconnect_started

    async def start(self) -> None:
        self.started = True
        self.reconnect_started.set()
        await asyncio.Event().wait()


def test_reconnecting_consumer_is_reported_unhealthy(monkeypatch: Any) -> None:
    async def exercise() -> None:
        reconnect_started = asyncio.Event()
        created: list[_FakeKafkaConsumer] = []

        def consumer_factory(*_args: Any, **_kwargs: Any) -> _FakeKafkaConsumer:
            consumer: _FakeKafkaConsumer
            if created:
                consumer = _BlockingStartKafkaConsumer(reconnect_started)
            else:
                consumer = _FakeKafkaConsumer()
            created.append(consumer)
            return consumer

        monkeypatch.setattr(consumer_module, "AIOKafkaConsumer", consumer_factory)

        async def on_projected(_event: dict[str, Any]) -> None:
            return None

        projection = ProjectionConsumer(
            bootstrap_servers="kafka:9092",
            store=_Store(),  # type: ignore[arg-type]
            on_projected=on_projected,
            retry_delay_seconds=0,
        )

        async def fail_consume() -> None:
            raise RuntimeError("temporary projection failure")

        projection._consume = fail_consume  # type: ignore[method-assign]

        await projection.start()
        await asyncio.wait_for(reconnect_started.wait(), timeout=1)

        assert projection.healthy is False
        assert projection._task is not None
        assert projection._task.done() is False

        await projection.stop()
        assert created[1].stopped is True

    asyncio.run(exercise())
