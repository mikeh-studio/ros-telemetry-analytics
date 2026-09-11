from __future__ import annotations

import asyncio
import math
import re
import time
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import yaml

from demo.common.config import TopicSpec
from demo.common.contracts import envelope, telemetry_event, topic_registration_envelope
from demo.gateway.outbox import DurableOutbox

HEALTH_TOPIC = "/_telemetry/gateway_health"
EVENT_TOPIC = "/_telemetry/gateway_events"


@dataclass(frozen=True)
class GatewayTopic:
    topic: str
    message_type: str
    expected_rate_hz: float
    dropout_threshold_ms: int
    reliability: str = "best_effort"
    rate_monitoring_enabled: bool = True

    def __post_init__(self):
        if not re.fullmatch(r"/[A-Za-z0-9_/]+", self.topic) or len(self.topic) > 512:
            raise ValueError("Invalid ROS topic")
        if not re.fullmatch(r"[A-Za-z0-9_]+/msg/[A-Za-z0-9_]+", self.message_type):
            raise ValueError("Invalid ROS message type")
        if not math.isfinite(self.expected_rate_hz) or self.expected_rate_hz <= 0:
            raise ValueError("Expected rate must be finite and positive")
        if self.dropout_threshold_ms <= 0 or self.reliability not in {"best_effort", "reliable"}:
            raise ValueError("Invalid topic timing or reliability")

    def spec(self) -> TopicSpec:
        return TopicSpec(
            self.topic,
            self.message_type,
            self.expected_rate_hz,
            self.dropout_threshold_ms,
            self.rate_monitoring_enabled,
        )


@dataclass(frozen=True)
class GatewayConfig:
    robot_id: str
    duration_ms: int
    topics: tuple[GatewayTopic, ...]
    startup_grace_ms: int = 5000
    flush_padding_ms: int = 7001

    def __post_init__(self):
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", self.robot_id):
            raise ValueError("Invalid robot identity")
        if not 1000 <= self.duration_ms <= 3600000:
            raise ValueError("Live sessions must last 1 second to 1 hour")
        names = [t.topic for t in self.topics]
        if not 1 <= len(names) <= 12 or len(set(names)) != len(names):
            raise ValueError("Expected 1-12 unique live topics")
        if {HEALTH_TOPIC, EVENT_TOPIC} & set(names):
            raise ValueError("Gateway health topics are reserved")
        if self.startup_grace_ms < 0 or self.flush_padding_ms < 7001:
            raise ValueError("Invalid startup grace or insufficient Flink flush padding")

    @property
    def all_topics(self):
        return (
            *self.topics,
            GatewayTopic(HEALTH_TOPIC, "diagnostic_msgs/msg/DiagnosticArray", 1, 3000),
            GatewayTopic(
                EVENT_TOPIC,
                "diagnostic_msgs/msg/DiagnosticArray",
                1,
                3000,
                rate_monitoring_enabled=False,
            ),
        )


def load_gateway_config(path: Path) -> GatewayConfig:
    raw = yaml.safe_load(path.read_text())
    if raw.get("schema_version") != 1:
        raise ValueError("Gateway configuration requires schema_version 1")
    return GatewayConfig(
        robot_id=raw["robot_id"],
        duration_ms=raw["duration_ms"],
        topics=tuple(GatewayTopic(**t) for t in raw["topics"]),
    )


class LiveGateway:
    """ROS-independent ingress contract, used unchanged by the real ROS node."""

    def __init__(
        self,
        config: GatewayConfig,
        outbox: DurableOutbox,
        *,
        wall_ns=time.time_ns,
        monotonic_ns=time.monotonic_ns,
    ):
        self.config = config
        self.outbox = outbox
        self.wall_ns = wall_ns
        self.monotonic_ns = monotonic_ns
        self._anchor_mono = monotonic_ns()
        self._anchor_wall = max(wall_ns(), outbox.stats()["last_receipt_ns"] + 1)
        self.session = outbox.session()
        self.topics = {topic.topic: topic for topic in config.all_topics}
        if self.session is None:
            self.session = {
                "run_id": "live-" + uuid.uuid4().hex,
                "start_ms": self._anchor_wall // 1_000_000,
                "config": asdict(config),
                "closed": False,
            }
            controls = self._lifecycle("run_started", self.session["start_ms"])
            for topic in config.all_topics:
                controls.append(
                    (
                        config.robot_id,
                        topic_registration_envelope(
                            run_id=self.run_id,
                            robot_id=config.robot_id,
                            topic_spec=topic.spec(),
                            source_start_ns=self._anchor_wall,
                            stream_start_ms=self.session["start_ms"],
                            startup_grace_ms=config.startup_grace_ms,
                            expected_topic_count=len(config.all_topics),
                            dataset_id="live-ros2",
                            dataset_name=f"Live ROS 2 · {config.robot_id}",
                            source_format="live_ros2",
                            mission_duration_ms=config.duration_ms,
                        ),
                    )
                )
            outbox.begin_session(self.session, controls)
        elif self.session["config"] != json_compatible(asdict(config)):
            raise ValueError("Cannot resume a gateway session with a different configuration")
        self.transport_state = "connecting"
        self.delivery_started_mono_ns = None
        self.last_delivery_ack_ns = None
        self.last_transport_error: str | None = None

    @property
    def run_id(self):
        return self.session["run_id"]

    def receipt_ns(self) -> int:
        # NTP adjustments cannot move event time backwards within this process.
        return self._anchor_wall + max(0, self.monotonic_ns() - self._anchor_mono)

    def ingest(
        self,
        topic: str,
        *,
        source_timestamp_ns: int | None,
        attributes: dict[str, Any] | None = None,
    ) -> bool:
        spec = self.topics[topic]
        received = self.receipt_ns()
        if source_timestamp_ns is not None and source_timestamp_ns < 0:
            raise ValueError("Source timestamp cannot be negative")
        observed = {
            **(attributes or {}),
            "gateway_received_timestamp_ns": received,
            "ros_timestamp_ns": source_timestamp_ns,
            "timing_basis": "gateway_receive",
            "source_clock": "ros" if source_timestamp_ns is not None else "gateway",
        }
        if len(observed) > 64 or any(isinstance(v, (dict, list, tuple)) for v in observed.values()):
            raise ValueError("Gateway attributes must be bounded scalar evidence")

        def build(sequence):
            event = telemetry_event(
                run_id=self.run_id,
                robot_id=self.config.robot_id,
                bag_id=self.run_id,
                sequence=sequence,
                topic=topic,
                message_type=spec.message_type,
                event_timestamp_ns=received,
                stream_timestamp_ms=received // 1_000_000,
                ingest_timestamp_ms=received // 1_000_000,
                attributes=observed,
                source_mode="live_ros2",
            )
            return self.config.robot_id, envelope(
                envelope_type="telemetry",
                run_id=self.run_id,
                robot_id=self.config.robot_id,
                topic=topic,
                event_timestamp_ns=received,
                stream_timestamp_ms=received // 1_000_000,
                ingest_timestamp_ms=received // 1_000_000,
                body=event,
                ordinal=sequence,
            )

        return self.outbox.enqueue(build)

    def heartbeat(self):
        return self.ingest(
            HEALTH_TOPIC,
            source_timestamp_ns=None,
            attributes={
                **self.outbox.stats(),
                "transport_state": self.transport_state,
                "last_transport_error": self.last_transport_error,
                "delivery_wait_ms": (
                    max(0, self.monotonic_ns() - self.delivery_started_mono_ns) // 1_000_000
                    if self.delivery_started_mono_ns is not None
                    else 0
                ),
                "last_delivery_ack_ns": self.last_delivery_ack_ns,
            },
        )

    def qos_event(self, kind: str, topic: str, count: int):
        return self.ingest(
            EVENT_TOPIC,
            source_timestamp_ns=None,
            attributes={"event_kind": kind, "affected_topic": topic, "count": count},
        )

    def expired(self) -> bool:
        return self.receipt_ns() // 1_000_000 >= self.session["start_ms"] + self.config.duration_ms

    def finish(self):
        if self.session["closed"]:
            return
        timestamp = self.receipt_ns() // 1_000_000
        self.outbox.end_session(
            self._lifecycle("run_ended", timestamp)
            + self._lifecycle("watermark_flush", timestamp + self.config.flush_padding_ms)
        )
        self.session["closed"] = True

    def _lifecycle(self, kind, timestamp):
        topics = [None] if kind == "run_started" else [None, *self.topics]
        return [
            (
                self.config.robot_id,
                envelope(
                    envelope_type=kind,
                    run_id=self.run_id,
                    robot_id=self.config.robot_id,
                    topic=topic,
                    event_timestamp_ns=timestamp * 1_000_000,
                    stream_timestamp_ms=timestamp,
                    ordinal=f"{kind}:{topic}",
                    body={
                        "dataset_id": "live-ros2",
                        "dataset_name": f"Live ROS 2 · {self.config.robot_id}",
                        "source_format": "live_ros2",
                        "source_mode": "live_ros2",
                        "mission_duration_ms": self.config.duration_ms,
                        "expected_topic_count": len(self.topics),
                    },
                ),
            )
            for topic in topics
        ]


def json_compatible(value):
    import json

    return json.loads(json.dumps(value))


async def deliver_head(outbox: DurableOutbox, publisher, *, wall_ms=None) -> bool:
    """An exception or cancellation leaves the head unchanged for retry."""
    record = outbox.peek()
    if record is None:
        return False
    clock = time.time_ns() // 1_000_000 if wall_ms is None else wall_ms()
    if (
        record["payload"].get("envelope_type") == "watermark_flush"
        and record["payload"]["stream_timestamp_ms"] > clock
    ):
        return False
    await publisher.publish(record["partition_key"], record["payload"])
    outbox.acknowledge(record["id"])
    return True


async def deliver_forever(gateway: LiveGateway, publisher_factory, stop: asyncio.Event):
    while not stop.is_set():
        publisher = publisher_factory()
        try:
            await publisher.start()
            gateway.transport_state = "connected"
            gateway.last_transport_error = None
            while not stop.is_set():
                gateway.transport_state = "awaiting_ack"
                gateway.delivery_started_mono_ns = gateway.monotonic_ns()
                delivered = await deliver_head(gateway.outbox, publisher)
                gateway.delivery_started_mono_ns = None
                gateway.transport_state = "connected"
                if delivered:
                    gateway.last_delivery_ack_ns = gateway.receipt_ns()
                else:
                    await asyncio.sleep(0.05)
        except Exception as exc:
            gateway.delivery_started_mono_ns = None
            gateway.transport_state = "disconnected"
            gateway.last_transport_error = type(exc).__name__
            try:
                await asyncio.wait_for(stop.wait(), timeout=1)
            except TimeoutError:
                pass
        finally:
            try:
                await publisher.stop()
            except Exception as exc:
                gateway.transport_state = "disconnected"
                gateway.last_transport_error = type(exc).__name__
