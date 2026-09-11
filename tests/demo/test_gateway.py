from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from demo.gateway.core import (
    GatewayConfig,
    GatewayTopic,
    LiveGateway,
    deliver_forever,
    deliver_head,
)
from demo.gateway.outbox import DurableOutbox, OutboxFull
from demo.gateway.ros_node import observations


def config():
    return GatewayConfig(
        "robot-live-test", 10000, (GatewayTopic("/scan", "sensor_msgs/msg/LaserScan", 10, 1500),)
    )


def drain(outbox):
    rows = []
    while row := outbox.peek():
        rows.append(row["payload"])
        outbox.acknowledge(row["id"])
    return rows


def test_live_schema_clock_domains_lifecycle_and_source_mode(tmp_path):
    box = DurableOutbox(tmp_path / "edge.sqlite")
    clock = [1_000_000_000_000]
    gateway = LiveGateway(config(), box, wall_ns=lambda: clock[0], monotonic_ns=lambda: clock[0])
    controls = drain(box)
    assert [r["envelope_type"] for r in controls] == ["run_started"] + ["topic_registered"] * 3
    clock[0] += 1_000_000_000
    assert gateway.ingest("/scan", source_timestamp_ns=50)
    record = box.peek()["payload"]
    event = record["body"]
    assert event["source_mode"] == "live_ros2"
    assert event["attributes"]["ros_timestamp_ns"] == 50
    assert event["event_timestamp_ns"] == clock[0]
    root = Path(__file__).resolve().parents[2] / "schemas"
    event_schema = json.loads((root / "telemetry-event-v1.schema.json").read_text())
    envelope_schema = json.loads((root / "telemetry-envelope-v1.schema.json").read_text())
    registry = Registry().with_resource(event_schema["$id"], Resource.from_contents(event_schema))
    validator = Draft202012Validator(envelope_schema, registry=registry)
    for value in controls + [record]:
        validator.validate(value)
    gateway.finish()
    values = drain(box)
    for value in values:
        validator.validate(value)
    terminal = values[1:]
    assert [r["envelope_type"] for r in terminal] == ["run_ended"] * 4 + ["watermark_flush"] * 4
    assert terminal[-1]["stream_timestamp_ms"] - terminal[0]["stream_timestamp_ms"] == 7001
    with pytest.raises(RuntimeError, match="No open"):
        gateway.ingest("/scan", source_timestamp_ns=0)
    box.close()


def test_uncertain_send_retries_identical_envelope_after_restart(tmp_path):
    path = tmp_path / "edge.sqlite"
    box = DurableOutbox(path)
    gateway = LiveGateway(config(), box)
    drain(box)
    gateway.ingest("/scan", source_timestamp_ns=12)
    original = box.peek()
    sent = []

    class Publisher:
        async def publish(self, key, value):
            sent.append(value)
            raise ConnectionError("Broker accepted; acknowledgment was lost")

    with pytest.raises(ConnectionError):
        asyncio.run(deliver_head(box, Publisher()))
    assert box.peek() == original
    box.close()
    box = DurableOutbox(path)
    resumed = LiveGateway(config(), box)
    assert resumed.run_id == gateway.run_id
    assert box.peek() == original

    class Healthy:
        async def publish(self, key, value):
            sent.append(value)

    assert asyncio.run(deliver_head(box, Healthy()))
    assert sent[0] == sent[1]
    assert box.stats()["acknowledged"] == 1
    assert box.peek() is None
    resumed.ingest("/scan", source_timestamp_ns=13)
    assert box.peek()["payload"]["body"]["sequence"] == 1
    box.close()


def test_overflow_is_counted_and_does_not_consume_control_reserve(tmp_path):
    box = DurableOutbox(tmp_path / "edge.sqlite", max_bytes=2000, max_records=1)
    gateway = LiveGateway(config(), box)
    drain(box)
    assert gateway.ingest("/scan", source_timestamp_ns=0)
    assert not gateway.ingest("/scan", source_timestamp_ns=1)
    assert box.stats()["received"] == 2 and box.stats()["rejected"] == 1
    drain(box)
    assert gateway.ingest("/scan", source_timestamp_ns=2)
    assert box.peek()["payload"]["body"]["sequence"] == 2
    gateway.finish()
    assert box.session()["closed"]
    assert len(drain(box)) == 9
    assert box.stats()["acknowledged"] == 2
    box.close()


def test_failed_registration_is_atomic_and_second_owner_is_rejected(tmp_path):
    path = tmp_path / "edge.sqlite"
    box = DurableOutbox(path, max_bytes=1, max_records=1, control_reserve_bytes=1)
    with pytest.raises(OutboxFull):
        LiveGateway(config(), box)
    assert box.session() is None and box.peek() is None
    with pytest.raises(RuntimeError, match="already has an owner"):
        DurableOutbox(path)
    box.close()


def test_new_session_requires_fully_drained_terminal_state(tmp_path):
    box = DurableOutbox(tmp_path / "edge.sqlite")
    gateway = LiveGateway(config(), box)
    with pytest.raises(RuntimeError, match="Cannot reset"):
        box.reset_completed_session()
    gateway.finish()
    with pytest.raises(RuntimeError, match="Cannot reset"):
        box.reset_completed_session()
    drain(box)
    box.reset_completed_session()
    assert LiveGateway(config(), box).run_id != gateway.run_id
    box.close()


def test_reception_clock_does_not_regress_across_process_restart(tmp_path):
    path = tmp_path / "edge.sqlite"
    box = DurableOutbox(path)
    gateway = LiveGateway(config(), box, wall_ns=lambda: 1_000_000, monotonic_ns=lambda: 0)
    drain(box)
    gateway.ingest("/scan", source_timestamp_ns=999)
    previous = drain(box)[0]["event_timestamp_ns"]
    box.close()
    box = DurableOutbox(path)
    gateway = LiveGateway(config(), box, wall_ns=lambda: 1, monotonic_ns=lambda: 0)
    gateway.ingest("/scan", source_timestamp_ns=0)
    assert box.peek()["payload"]["event_timestamp_ns"] > previous
    box.close()


def test_abrupt_process_exit_preserves_committed_observation(tmp_path):
    path = tmp_path / "edge.sqlite"
    script = """
import os
from pathlib import Path
from demo.gateway.outbox import DurableOutbox
box=DurableOutbox(Path(os.environ['TEST_GATEWAY_PATH']))
box.begin_session({'closed':False}, [])
box.enqueue(lambda sequence: ('robot', {'id':sequence, 'event_timestamp_ns':1}))
os._exit(17)
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        env={**os.environ, "TEST_GATEWAY_PATH": str(path)},
        check=False,
    )
    assert result.returncode == 17
    box = DurableOutbox(path)
    assert box.peek()["payload"]["id"] == 0
    assert box.stats()["received"] == 1
    box.close()


def test_real_ros_diagnostic_byte_levels_are_decoded():
    message = SimpleNamespace(status=[SimpleNamespace(level=b"\x02"), SimpleNamespace(level=1)])
    stamp, values = observations(message)
    assert stamp is None
    assert values == {"diagnostic_count": 2, "diagnostic_max_level": 2}


def test_ros_coordinate_frame_is_preserved_and_bounded():
    message = SimpleNamespace(
        header=SimpleNamespace(stamp=SimpleNamespace(sec=3, nanosec=4), frame_id="map")
    )
    stamp, values = observations(message)
    assert stamp == 3_000_000_004
    assert values["frame_id"] == "map"
    message.header.frame_id = "x" * 600
    assert observations(message)[1]["frame_id"] == ""


def test_pending_broker_ack_is_observable_without_blocking_ingestion(tmp_path):
    async def scenario():
        box = DurableOutbox(tmp_path / "edge.sqlite")
        ticks = [1_000_000_000_000]
        gateway = LiveGateway(config(), box, monotonic_ns=lambda: ticks[0])
        entered, release, stop = asyncio.Event(), asyncio.Event(), asyncio.Event()

        class Publisher:
            async def start(self):
                pass

            async def stop(self):
                pass

            async def publish(self, key, value):
                entered.set()
                await release.wait()

        task = asyncio.create_task(deliver_forever(gateway, Publisher, stop))
        await asyncio.wait_for(entered.wait(), 1)
        ticks[0] += 3_000_000_000
        assert gateway.heartbeat()
        assert gateway.transport_state == "awaiting_ack"
        stop.set()
        release.set()
        await asyncio.wait_for(task, 1)
        rows = drain(box)
        health = rows[-1]["body"]["attributes"]
        assert health["delivery_wait_ms"] == 3000
        assert health["last_delivery_ack_ns"] is None
        assert gateway.last_delivery_ack_ns is not None
        box.close()

    asyncio.run(scenario())


def test_terminal_flush_never_advances_live_watermark_ahead_of_wall_clock(tmp_path):
    box = DurableOutbox(tmp_path / "edge.sqlite")
    box.begin_session(
        {"closed": False},
        [("robot", {"envelope_type": "watermark_flush", "stream_timestamp_ms": 100})],
    )
    sent = []

    class Publisher:
        async def publish(self, key, value):
            sent.append(value)

    assert not asyncio.run(deliver_head(box, Publisher(), wall_ms=lambda: 99))
    assert box.peek() is not None and not sent
    assert asyncio.run(deliver_head(box, Publisher(), wall_ms=lambda: 100))
    assert box.peek() is None and len(sent) == 1
    box.close()
