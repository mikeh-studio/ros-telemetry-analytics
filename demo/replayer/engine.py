from __future__ import annotations

import asyncio
import re
import time
import uuid
from collections import defaultdict
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from statistics import median
from typing import Any, Protocol

import yaml

from demo.common.config import StreamingConfig, TopicSpec
from demo.common.contracts import (
    RunIdAlreadyAllocatedError,
    RunIdRegistry,
    StreamEpochAllocator,
    envelope,
    telemetry_event,
    topic_registration_envelope,
)
from demo.common.datasets import DEFAULT_DATASET_ID, ReplayDataset
from ros_telemetry_analytics.discovery import discover_bags
from ros_telemetry_analytics.reader import open_bag

SAFE_RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")

# These types normally represent continuously sampled robot state. Their coverage
# or regularity must not decide whether to monitor them: failures change both.
CONTINUOUS_MESSAGE_TYPES = frozenset(
    f"sensor_msgs/msg/{name}"
    for name in (
        "Image",
        "CompressedImage",
        "CameraInfo",
        "Imu",
        "LaserScan",
        "MultiEchoLaserScan",
        "PointCloud",
        "PointCloud2",
        "Range",
        "NavSatFix",
        "MagneticField",
        "FluidPressure",
        "Temperature",
        "RelativeHumidity",
        "JointState",
        "MultiDOFJointState",
    )
) | {"nav_msgs/msg/Odometry", "tf2_msgs/msg/TFMessage"}
EVENT_MESSAGE_TYPES = frozenset(
    {
        "std_msgs/msg/String",
        "std_msgs/msg/Empty",
        "diagnostic_msgs/msg/DiagnosticArray",
        "rcl_interfaces/msg/Log",
        "rcl_interfaces/msg/ParameterEvent",
        "rosgraph_msgs/msg/Log",
    }
)


class Publisher(Protocol):
    async def publish(self, key: str, value: dict[str, Any]) -> None: ...


class ReplayContractError(RuntimeError):
    """The durable lifecycle contract could not be established before replay."""


@dataclass(frozen=True)
class RecordedMessage:
    sequence: int
    topic: str
    message_type: str
    source_timestamp_ns: int
    source_offset_ms: int
    payload_size_bytes: int


@dataclass(frozen=True)
class ScheduledMessage:
    record: RecordedMessage
    publish_offset_ms: int
    disposition: str = "normal"


@dataclass(frozen=True)
class CameraDropoutScenario:
    name: str
    topic: str
    start_offset_ms: int
    end_offset_ms: int
    held_offsets_ms: tuple[int, ...]
    release_offset_ms: int
    allowed_rates: tuple[int, ...]


@dataclass
class RunState:
    run_id: str | None = None
    status: str = "idle"
    replay_rate: int = 1
    scenario: str | None = None
    mission_offset_ms: int = 0
    published_messages: int = 0
    total_messages: int = 0
    stream_start_ms: int | None = None
    detail: str | None = None
    dataset_id: str = DEFAULT_DATASET_ID
    dataset_name: str = "Warehouse Run 17"
    source_format: str = "rosbag2_mcap"
    mission_duration_ms: int = 90_000
    topic_count: int = 4
    supports_camera_dropout: bool = True

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def load_recorded_messages(fixture_path: Path) -> list[RecordedMessage]:
    bags = discover_bags([fixture_path])
    if len(bags) != 1:
        raise ValueError(f"Expected one recorded mission at {fixture_path}, found {len(bags)}")

    raw_records: list[tuple[int, str, str, int, int]] = []
    with open_bag(bags[0]) as reader:
        for sequence, (connection, timestamp_ns, rawdata) in enumerate(reader.messages()):
            raw_records.append(
                (
                    sequence,
                    connection.topic,
                    connection.msgtype,
                    int(timestamp_ns),
                    len(rawdata),
                )
            )
    if not raw_records:
        raise ValueError(f"Recorded mission contains no messages: {fixture_path}")

    source_start_ns = min(item[3] for item in raw_records)
    return [
        RecordedMessage(
            sequence=sequence,
            topic=topic,
            message_type=message_type,
            source_timestamp_ns=timestamp_ns,
            source_offset_ms=round((timestamp_ns - source_start_ns) / 1_000_000),
            payload_size_bytes=payload_size,
        )
        for sequence, topic, message_type, timestamp_ns, payload_size in raw_records
    ]


def infer_topic_specs(records: Sequence[RecordedMessage]) -> tuple[TopicSpec, ...]:
    """Infer cadence candidates, not an authoritative sensor configuration.

    Continuous sensor types retain monitoring despite gaps, jitter, or incomplete
    coverage. Unknown types need sustained regular cadence across most of the
    recording; static transforms and known event types remain exempt. The built-in
    Warehouse fixture bypasses inference and retains its declared expectations.
    """

    by_topic: dict[str, list[RecordedMessage]] = defaultdict(list)
    for record in records:
        by_topic[record.topic].append(record)
    recording_duration_s = max((record.source_offset_ms for record in records), default=0) / 1_000
    specs: list[TopicSpec] = []
    for topic, topic_records in sorted(by_topic.items()):
        message_type = topic_records[0].message_type
        timestamps = sorted({record.source_timestamp_ns for record in topic_records})
        topic_duration_s = (timestamps[-1] - timestamps[0]) / 1_000_000_000
        intervals_ns = [end - start for start, end in zip(timestamps, timestamps[1:], strict=False)]
        median_interval_ns = median(intervals_ns) if intervals_ns else 0
        static_or_event = topic.rstrip("/").split("/")[-1] == "tf_static" or (
            message_type in EVENT_MESSAGE_TYPES
        )
        continuous_type = message_type in CONTINUOUS_MESSAGE_TYPES
        regular_cadence = (
            len(intervals_ns) >= 10
            and topic_duration_s >= max(1.0, recording_duration_s * 0.8)
            and sum(
                abs(interval - median_interval_ns) <= median_interval_ns * 0.2
                for interval in intervals_ns
            )
            >= len(intervals_ns) * 0.8
        )
        rate_monitoring_enabled = (
            not static_or_event and bool(intervals_ns) and (continuous_type or regular_cadence)
        )
        if rate_monitoring_enabled:
            expected_rate_hz = 1_000_000_000 / median_interval_ns
            dropout_threshold_ms = round(min(60_000, max(1_000, 3_000 / expected_rate_hz)))
        else:
            expected_rate_hz = max(0.01, len(topic_records) / max(recording_duration_s, 1))
            dropout_threshold_ms = max(1_000, round(recording_duration_s * 1_000) + 1)
        specs.append(
            TopicSpec(
                topic=topic,
                message_type=message_type,
                expected_rate_hz=expected_rate_hz,
                dropout_threshold_ms=dropout_threshold_ms,
                rate_monitoring_enabled=rate_monitoring_enabled,
            )
        )
    return tuple(specs)


def load_camera_dropout_scenario(path: Path) -> CameraDropoutScenario:
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if raw.get("schema_version") != 1:
        raise ValueError("Replay scenario requires schema_version: 1")
    return CameraDropoutScenario(
        name=str(raw["name"]),
        topic=str(raw["topic"]),
        start_offset_ms=int(raw["start_offset_ms"]),
        end_offset_ms=int(raw["end_offset_ms"]),
        held_offsets_ms=tuple(int(value) for value in raw["held_offsets_ms"]),
        release_offset_ms=int(raw["release_offset_ms"]),
        allowed_rates=tuple(int(value) for value in raw["allowed_rates"]),
    )


def build_schedule(
    records: Sequence[RecordedMessage],
    scenario: CameraDropoutScenario | None = None,
) -> list[ScheduledMessage]:
    scheduled: list[ScheduledMessage] = []
    held_found: set[int] = set()
    for record in records:
        if scenario is None or record.topic != scenario.topic:
            scheduled.append(ScheduledMessage(record, record.source_offset_ms))
            continue
        offset = record.source_offset_ms
        if offset in scenario.held_offsets_ms:
            held_found.add(offset)
            scheduled.append(
                ScheduledMessage(record, scenario.release_offset_ms, disposition="held")
            )
        elif scenario.start_offset_ms < offset < scenario.end_offset_ms:
            continue
        else:
            scheduled.append(ScheduledMessage(record, offset))

    if scenario is not None and held_found != set(scenario.held_offsets_ms):
        missing = sorted(set(scenario.held_offsets_ms) - held_found)
        raise ValueError(f"Recorded fixture is missing held scenario frames at {missing}")
    return sorted(
        scheduled,
        key=lambda item: (
            item.publish_offset_ms,
            item.record.source_offset_ms,
            item.record.sequence,
        ),
    )


class ReplayEngine:
    def __init__(
        self,
        *,
        config: StreamingConfig,
        fixture_path: Path,
        scenario_path: Path,
        epoch_state_path: Path,
        run_id_state_path: Path | None = None,
        publisher: Publisher,
        dataset_resolver: Callable[[str], ReplayDataset] | None = None,
        monotonic: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self.config = config
        self.fixture_path = fixture_path
        self.scenario = load_camera_dropout_scenario(scenario_path)
        self.epoch_allocator = StreamEpochAllocator(epoch_state_path)
        self.run_ids = RunIdRegistry(
            run_id_state_path or epoch_state_path.with_name("allocated-run-ids.json")
        )
        self.publisher = publisher
        self.dataset_resolver = dataset_resolver
        self.monotonic = monotonic
        self.sleep = sleep
        self.state = RunState(replay_rate=config.demo.default_rate)
        self._task: asyncio.Task[None] | None = None
        self._run_token = 0
        self._pause_gate = asyncio.Event()
        self._pause_gate.set()
        self._pause_started_at: float | None = None
        self._accumulated_pause_s = 0.0
        self._wall_start = 0.0
        self._lock = asyncio.Lock()
        self._active_dataset = self._default_dataset()
        self._active_topic_specs = config.analytics.expected_topics

    def _default_dataset(self) -> ReplayDataset:
        return ReplayDataset(
            dataset_id=DEFAULT_DATASET_ID,
            name="Warehouse Run 17",
            description="Deterministic recorded mission.",
            source="built_in",
            file_format="rosbag2_mcap",
            path=self.fixture_path,
            status="ready",
            size_bytes=self.fixture_path.stat().st_size if self.fixture_path.is_file() else None,
            mission_duration_ms=90_000,
            supports_camera_dropout=True,
        )

    def _resolve_dataset(self, dataset_id: str) -> ReplayDataset:
        if self.dataset_resolver is not None:
            return self.dataset_resolver(dataset_id)
        if dataset_id != DEFAULT_DATASET_ID:
            raise ValueError(f"Unknown dataset: {dataset_id}")
        return self._default_dataset()

    def snapshot(self) -> dict[str, Any]:
        return self.state.as_dict()

    async def wait_for_completion(self) -> dict[str, Any]:
        task = self._task
        if task is not None:
            await task
        return self.snapshot()

    async def start(
        self,
        *,
        replay_rate: int,
        scenario_name: str | None,
        requested_run_id: str | None = None,
        dataset_id: str = DEFAULT_DATASET_ID,
    ) -> dict[str, Any]:
        async with self._lock:
            if self._task and not self._task.done():
                raise RuntimeError("A replay is already active")
            if replay_rate not in self.config.demo.supported_rates:
                raise ValueError(f"Unsupported replay rate: {replay_rate}")
            dataset = self._resolve_dataset(dataset_id)
            assert dataset.path is not None
            scenario = None
            if scenario_name:
                if not dataset.supports_camera_dropout:
                    raise ValueError("Camera dropout is available only for Warehouse Run 17")
                if scenario_name != self.scenario.name:
                    raise ValueError(f"Unknown scenario: {scenario_name}")
                if replay_rate not in self.scenario.allowed_rates:
                    raise ValueError(f"{scenario_name} is available only at 1x replay")
                scenario = self.scenario

            records = load_recorded_messages(dataset.path)
            topic_specs = (
                self.config.analytics.expected_topics
                if dataset.supports_camera_dropout
                else infer_topic_specs(records)
            )
            recorded_duration_ms = max(1, max(record.source_offset_ms for record in records))
            duration_ms = max(recorded_duration_ms, dataset.mission_duration_ms or 0)
            schedule = build_schedule(records, scenario)
            if requested_run_id is not None and not SAFE_RUN_ID.fullmatch(requested_run_id):
                raise ValueError(
                    "run_id must contain 1 to 128 letters, digits, dots, underscores, or hyphens"
                )
            if requested_run_id is not None:
                run_id = requested_run_id
                self.run_ids.reserve(run_id)
            else:
                while True:
                    run_id = str(uuid.uuid4())
                    try:
                        self.run_ids.reserve(run_id)
                    except RunIdAlreadyAllocatedError:
                        continue
                    break
            self._run_token += 1
            token = self._run_token
            epoch = self.epoch_allocator.allocate(
                duration_ms,
                self.config.analytics.allowed_lateness_ms
                + self.config.analytics.maximum_out_of_orderness_ms
                + 1_000,
                clock_ms=int(time.time() * 1_000),
            )
            self.state = RunState(
                run_id=run_id,
                status="starting",
                replay_rate=replay_rate,
                scenario=scenario_name,
                total_messages=len(schedule),
                stream_start_ms=epoch.start_ms,
                dataset_id=dataset.dataset_id,
                dataset_name=dataset.name,
                source_format=dataset.file_format,
                mission_duration_ms=duration_ms,
                topic_count=len(topic_specs),
                supports_camera_dropout=dataset.supports_camera_dropout,
            )
            self._active_dataset = dataset
            self._active_topic_specs = topic_specs
            self._pause_gate.set()
            self._pause_started_at = None
            self._accumulated_pause_s = 0.0
            source_start_ns = min(item.record.source_timestamp_ns for item in schedule)
            try:
                await self._establish_run_contract(
                    source_start_ns,
                    stream_start_ms=epoch.start_ms,
                    topic_specs=topic_specs,
                    duration_ms=duration_ms,
                )
            except Exception as exc:
                self.state.status = "failed"
                self.state.detail = str(exc)
                try:
                    await self._publish_lifecycle("run_failed", detail=str(exc))
                except Exception as lifecycle_exc:
                    self.state.detail = f"{exc}; failed to publish run_failed: {lifecycle_exc}"
                raise ReplayContractError(self.state.detail) from exc
            self.state.status = "running"
            self._task = asyncio.create_task(
                self._run(token, schedule, epoch.start_ms, duration_ms),
                name=f"recorded-replay-{self.state.run_id}",
            )
            return self.snapshot()

    async def activate_camera_dropout(self) -> dict[str, Any]:
        async with self._lock:
            if self.state.status != "running" or self._task is None or self._task.done():
                raise RuntimeError("Camera dropout requires a running mission")
            if not self.state.supports_camera_dropout:
                raise RuntimeError("Camera dropout is available only for Warehouse Run 17")
            if self.state.replay_rate not in self.scenario.allowed_rates:
                raise RuntimeError("Camera dropout is available only during a 1x replay")
            if self.state.scenario is not None:
                raise RuntimeError("A replay scenario is already active")
            if self.state.mission_offset_ms > self.scenario.start_offset_ms:
                raise RuntimeError("Camera dropout injection window has already passed")
            assert self._active_dataset.path is not None
            records = load_recorded_messages(self._active_dataset.path)
            self.state.scenario = self.scenario.name
            self.state.total_messages = len(build_schedule(records, self.scenario))
            return self.snapshot()

    async def pause(self) -> dict[str, Any]:
        async with self._lock:
            if self.state.status != "running":
                raise RuntimeError("Only a running replay can be paused")
            self.state.status = "paused"
            self._pause_started_at = self.monotonic()
            self._pause_gate.clear()
            await self._publish_lifecycle("run_paused")
            return self.snapshot()

    async def resume(self) -> dict[str, Any]:
        async with self._lock:
            if self.state.status != "paused" or self._pause_started_at is None:
                raise RuntimeError("Only a paused replay can be resumed")
            self._accumulated_pause_s += self.monotonic() - self._pause_started_at
            self._pause_started_at = None
            self.state.status = "running"
            self._pause_gate.set()
            await self._publish_lifecycle("run_resumed")
            return self.snapshot()

    async def abort(self) -> dict[str, Any]:
        async with self._lock:
            if not self._task or self._task.done():
                return self.snapshot()
            self._run_token += 1
            self.state.status = "aborted"
            task = self._task
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            self._pause_gate.set()
            await self._publish_lifecycle("run_aborted")
            return self.snapshot()

    async def restart(self) -> dict[str, Any]:
        replay_rate = self.state.replay_rate
        scenario = self.state.scenario
        dataset_id = self.state.dataset_id
        await self.abort()
        task = self._task
        if task:
            try:
                await task
            except asyncio.CancelledError:
                pass
        return await self.start(
            replay_rate=replay_rate,
            scenario_name=scenario,
            dataset_id=dataset_id,
        )

    async def _run(
        self,
        token: int,
        schedule: Sequence[ScheduledMessage],
        stream_start_ms: int,
        duration_ms: int,
    ) -> None:
        try:
            assert self.state.run_id is not None
            source_start_ns = min(item.record.source_timestamp_ns for item in schedule)
            self._wall_start = self.monotonic()
            held_records: list[RecordedMessage] = []
            for item in schedule:
                if token != self._run_token:
                    return
                await self._pause_gate.wait()
                await self._wait_until(item.publish_offset_ms)
                record = item.record
                self.state.mission_offset_ms = record.source_offset_ms
                scenario_active = self.state.scenario == self.scenario.name
                if (
                    scenario_active
                    and held_records
                    and record.source_offset_ms >= self.scenario.release_offset_ms
                ):
                    for held_record in held_records:
                        await self._publish_telemetry(held_record, stream_start_ms)
                    held_records.clear()
                if scenario_active and record.topic == self.scenario.topic:
                    if record.source_offset_ms in self.scenario.held_offsets_ms:
                        held_records.append(record)
                        continue
                    if (
                        self.scenario.start_offset_ms
                        < record.source_offset_ms
                        < self.scenario.end_offset_ms
                    ):
                        continue
                await self._publish_telemetry(record, stream_start_ms)

            if held_records:
                await self._wait_until(self.scenario.release_offset_ms)
                for held_record in held_records:
                    await self._publish_telemetry(held_record, stream_start_ms)

            self.state.mission_offset_ms = duration_ms
            await self._publish_lifecycle("run_ended")
            flush_time = (
                stream_start_ms
                + duration_ms
                + self.config.analytics.allowed_lateness_ms
                + self.config.analytics.maximum_out_of_orderness_ms
                + 1
            )
            await self._publish_lifecycle(
                "watermark_flush",
                stream_timestamp_ms=flush_time,
                event_timestamp_ns=(source_start_ns + duration_ms * 1_000_000),
                reason="recorded_mission_complete",
            )
            self.state.status = "completed"
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self.state.status = "failed"
            self.state.detail = str(exc)
            try:
                await self._publish_lifecycle("run_failed", detail=str(exc))
            except Exception as lifecycle_exc:
                self.state.detail = f"{exc}; failed to publish run_failed: {lifecycle_exc}"

    async def _establish_run_contract(
        self,
        source_start_ns: int,
        *,
        stream_start_ms: int,
        topic_specs: Sequence[TopicSpec],
        duration_ms: int,
    ) -> None:
        assert self.state.run_id is not None
        await self._publish_lifecycle(
            "run_started",
            mission_duration_ms=duration_ms,
        )
        for topic_spec in topic_specs:
            registration = topic_registration_envelope(
                run_id=self.state.run_id,
                robot_id=self.config.demo.robot_id,
                topic_spec=topic_spec,
                source_start_ns=source_start_ns,
                stream_start_ms=stream_start_ms,
                startup_grace_ms=self.config.analytics.startup_grace_ms,
                expected_topic_count=len(topic_specs),
                dataset_id=self.state.dataset_id,
                dataset_name=self.state.dataset_name,
                source_format=self.state.source_format,
                mission_duration_ms=duration_ms,
            )
            await self.publisher.publish(self.config.demo.robot_id, registration)

    async def _publish_telemetry(self, record: RecordedMessage, stream_start_ms: int) -> None:
        assert self.state.run_id is not None
        event = telemetry_event(
            run_id=self.state.run_id,
            robot_id=self.config.demo.robot_id,
            bag_id=self.state.dataset_id,
            sequence=record.sequence,
            topic=record.topic,
            message_type=record.message_type,
            event_timestamp_ns=record.source_timestamp_ns,
            stream_timestamp_ms=stream_start_ms + record.source_offset_ms,
            attributes={
                "payload_size_bytes": record.payload_size_bytes,
            },
        )
        wrapped = envelope(
            envelope_type="telemetry",
            run_id=self.state.run_id,
            robot_id=self.config.demo.robot_id,
            topic=record.topic,
            event_timestamp_ns=record.source_timestamp_ns,
            stream_timestamp_ms=stream_start_ms + record.source_offset_ms,
            ordinal=record.sequence,
            body=event,
        )
        await self.publisher.publish(self.config.demo.robot_id, wrapped)
        self.state.published_messages += 1

    async def _wait_until(self, mission_offset_ms: int) -> None:
        while True:
            await self._pause_gate.wait()
            elapsed = self.monotonic() - self._wall_start - self._accumulated_pause_s
            remaining = mission_offset_ms / 1_000 / self.state.replay_rate - elapsed
            if remaining <= 0:
                return
            await self.sleep(min(remaining, 0.1))

    async def _publish_lifecycle(
        self,
        lifecycle_type: str,
        *,
        stream_timestamp_ms: int | None = None,
        event_timestamp_ns: int = 0,
        **body: Any,
    ) -> None:
        if self.state.run_id is None or self.state.stream_start_ms is None:
            return
        effective_stream_timestamp = stream_timestamp_ms or (
            self.state.stream_start_ms + self.state.mission_offset_ms
        )
        fanout_topics: tuple[str | None, ...] = (None,)
        if lifecycle_type in {
            "run_paused",
            "run_resumed",
            "run_aborted",
            "run_failed",
            "run_ended",
            "watermark_flush",
        }:
            fanout_topics += tuple(topic.topic for topic in self._active_topic_specs)
        for topic in fanout_topics:
            message = envelope(
                envelope_type=lifecycle_type,  # type: ignore[arg-type]
                run_id=self.state.run_id,
                robot_id=self.config.demo.robot_id,
                topic=topic,
                event_timestamp_ns=event_timestamp_ns,
                stream_timestamp_ms=effective_stream_timestamp,
                ordinal=f"{lifecycle_type}:{topic or '__robot__'}:{self.state.mission_offset_ms}",
                body={
                    "replay_rate": self.state.replay_rate,
                    "scenario_active": self.state.scenario is not None,
                    "dataset_id": self.state.dataset_id,
                    "dataset_name": self.state.dataset_name,
                    "source_format": self.state.source_format,
                    "mission_duration_ms": self.state.mission_duration_ms,
                    "expected_topic_count": self.state.topic_count,
                    **body,
                },
            )
            await self.publisher.publish(self.config.demo.robot_id, message)
