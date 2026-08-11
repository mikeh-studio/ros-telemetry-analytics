from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from demo.common.config import load_streaming_config
from demo.common.contracts import RunIdAlreadyAllocatedError
from demo.replayer.engine import (
    RecordedMessage,
    ReplayContractError,
    ReplayEngine,
    build_schedule,
    load_camera_dropout_scenario,
    load_recorded_messages,
)
from demo.replayer.generate_fixture import generate_fixture

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def _camera_message(offset_ms: int, sequence: int) -> RecordedMessage:
    return RecordedMessage(
        sequence=sequence,
        topic="/camera/image_raw",
        message_type="sensor_msgs/msg/Image",
        source_timestamp_ns=1_700_000_000_000_000_000 + offset_ms * 1_000_000,
        source_offset_ms=offset_ms,
        payload_size_bytes=1,
    )


def test_camera_dropout_schedule_has_exact_hold_drop_and_recovery_boundaries() -> None:
    scenario = load_camera_dropout_scenario(ROOT / "demo/scenarios/camera-dropout.yaml")
    records = [
        _camera_message(offset, index)
        for index, offset in enumerate([60_000, 60_500, 61_000, 62_000, 67_000, 68_000])
    ]

    schedule = build_schedule(records, scenario)
    by_source_offset = {item.record.source_offset_ms: item for item in schedule}

    assert set(by_source_offset) == {60_000, 61_000, 62_000, 68_000}
    assert by_source_offset[60_000].publish_offset_ms == 60_000
    assert by_source_offset[61_000].publish_offset_ms == 67_100
    assert by_source_offset[62_000].publish_offset_ms == 67_100
    assert by_source_offset[68_000].publish_offset_ms == 68_000
    assert by_source_offset[61_000].disposition == "held"


def test_scenario_rejects_fixture_without_exact_held_frames() -> None:
    scenario = load_camera_dropout_scenario(ROOT / "demo/scenarios/camera-dropout.yaml")
    records = [_camera_message(60_000, 0), _camera_message(68_000, 1)]

    with pytest.raises(ValueError, match="missing held scenario frames"):
        build_schedule(records, scenario)


@pytest.mark.demo_integration
def test_generated_fixture_has_exact_scenario_frames(tmp_path: Path) -> None:
    config = load_streaming_config(ROOT / "configs/streaming_demo.yaml")
    fixture = generate_fixture(tmp_path / "mission.mcap", config)
    records = load_recorded_messages(fixture)
    scenario = load_camera_dropout_scenario(ROOT / "demo/scenarios/camera-dropout.yaml")
    schedule = build_schedule(records, scenario)
    camera = {
        item.record.source_offset_ms: item
        for item in schedule
        if item.record.topic == scenario.topic
    }

    assert camera[60_000].disposition == "normal"
    assert camera[61_000].publish_offset_ms == 67_100
    assert camera[62_000].publish_offset_ms == 67_100
    assert camera[68_000].disposition == "normal"
    assert 60_500 not in camera


class VirtualClock:
    def __init__(self) -> None:
        self.now = 0.0

    def monotonic(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.now += seconds


class CapturingPublisher:
    def __init__(self) -> None:
        self.messages: list[tuple[str, dict[str, Any]]] = []

    async def publish(self, key: str, value: dict[str, Any]) -> None:
        self.messages.append((key, value))


class FailingTelemetryPublisher(CapturingPublisher):
    async def publish(self, key: str, value: dict[str, Any]) -> None:
        if value["envelope_type"] == "telemetry":
            raise RuntimeError("simulated telemetry publish failure")
        await super().publish(key, value)


class FailingRegistrationPublisher(CapturingPublisher):
    async def publish(self, key: str, value: dict[str, Any]) -> None:
        if value["envelope_type"] == "topic_registered":
            raise RuntimeError("simulated registration failure")
        await super().publish(key, value)


class BlockingClock:
    def monotonic(self) -> float:
        return 0.0

    async def sleep(self, _seconds: float) -> None:
        await asyncio.Event().wait()


class GatedVirtualClock(VirtualClock):
    def __init__(self) -> None:
        super().__init__()
        self.release = asyncio.Event()

    async def sleep(self, seconds: float) -> None:
        await self.release.wait()
        await super().sleep(seconds)


async def _wait_until_running(engine: ReplayEngine) -> None:
    for _attempt in range(100):
        if engine.state.status == "running" and engine.state.published_messages > 0:
            return
        await asyncio.sleep(0)
    raise AssertionError("replay did not enter its running state")


async def _finish_cancellation(engine: ReplayEngine) -> None:
    task = engine._task
    if task is None:
        return
    try:
        await task
    except asyncio.CancelledError:
        pass


@pytest.mark.demo_integration
@pytest.mark.anyio
async def test_clean_replay_runs_end_to_end_with_one_partition_key(tmp_path: Path) -> None:
    config = load_streaming_config(ROOT / "configs/streaming_demo.yaml")
    fixture = generate_fixture(tmp_path / "mission.mcap", config)
    publisher = CapturingPublisher()
    clock = VirtualClock()
    engine = ReplayEngine(
        config=config,
        fixture_path=fixture,
        scenario_path=ROOT / "demo/scenarios/camera-dropout.yaml",
        epoch_state_path=tmp_path / "epoch.json",
        publisher=publisher,
        monotonic=clock.monotonic,
        sleep=clock.sleep,
    )

    started = await engine.start(replay_rate=5, scenario_name=None)
    completed = await engine.wait_for_completion()

    telemetry = [
        value for _key, value in publisher.messages if value["envelope_type"] == "telemetry"
    ]
    lifecycle = [value["envelope_type"] for _key, value in publisher.messages[:5]]
    assert started["status"] == "running"
    assert completed["status"] == "completed"
    assert completed["published_messages"] == completed["total_messages"]
    assert len(telemetry) == sum(
        int(config.demo.duration_s * topic.expected_rate_hz)
        for topic in config.analytics.expected_topics
    )
    assert lifecycle == ["run_started"] + ["topic_registered"] * 4
    assert {key for key, _value in publisher.messages} == {"robot-17"}
    assert [value["envelope_type"] for _key, value in publisher.messages[-10:-5]] == [
        "run_ended"
    ] * 5
    assert [value["envelope_type"] for _key, value in publisher.messages[-5:]] == [
        "watermark_flush"
    ] * 5
    assert {value["topic"] for _key, value in publisher.messages[-5:]} == {
        None,
        "/camera/image_raw",
        "/imu/data",
        "/odom",
        "/diagnostics",
    }
    assert all(
        "scenario" not in value["body"]["attributes"]
        and "replay_disposition" not in value["body"]["attributes"]
        for value in telemetry
    )


@pytest.mark.demo_integration
@pytest.mark.anyio
async def test_replay_failure_emits_durable_robot_and_topic_lifecycle(tmp_path: Path) -> None:
    config = load_streaming_config(ROOT / "configs/streaming_demo.yaml")
    fixture = generate_fixture(tmp_path / "mission.mcap", config)
    publisher = FailingTelemetryPublisher()
    clock = VirtualClock()
    engine = ReplayEngine(
        config=config,
        fixture_path=fixture,
        scenario_path=ROOT / "demo/scenarios/camera-dropout.yaml",
        epoch_state_path=tmp_path / "epoch.json",
        publisher=publisher,
        monotonic=clock.monotonic,
        sleep=clock.sleep,
    )

    await engine.start(replay_rate=5, scenario_name=None, requested_run_id="failed-run")
    failed = await engine.wait_for_completion()

    failure_events = [
        value for _key, value in publisher.messages if value["envelope_type"] == "run_failed"
    ]
    assert failed["status"] == "failed"
    assert failed["detail"] == "simulated telemetry publish failure"
    assert len(failure_events) == 5
    assert {value["topic"] for value in failure_events} == {
        None,
        "/camera/image_raw",
        "/imu/data",
        "/odom",
        "/diagnostics",
    }
    assert all(
        value["body"]["detail"] == "simulated telemetry publish failure" for value in failure_events
    )


@pytest.mark.demo_integration
@pytest.mark.anyio
async def test_start_waits_for_the_durable_registration_contract(tmp_path: Path) -> None:
    config = load_streaming_config(ROOT / "configs/streaming_demo.yaml")
    fixture = generate_fixture(tmp_path / "mission.mcap", config)
    publisher = FailingRegistrationPublisher()
    engine = ReplayEngine(
        config=config,
        fixture_path=fixture,
        scenario_path=ROOT / "demo/scenarios/camera-dropout.yaml",
        epoch_state_path=tmp_path / "epoch.json",
        publisher=publisher,
    )

    with pytest.raises(ReplayContractError, match="simulated registration failure"):
        await engine.start(
            replay_rate=5,
            scenario_name=None,
            requested_run_id="failed-contract",
        )

    assert engine.state.status == "failed"
    assert engine._task is None
    assert [value["envelope_type"] for _key, value in publisher.messages] == [
        "run_started",
        "run_failed",
        "run_failed",
        "run_failed",
        "run_failed",
        "run_failed",
    ]


@pytest.mark.demo_integration
@pytest.mark.anyio
async def test_camera_dropout_can_be_injected_into_a_running_one_x_mission(
    tmp_path: Path,
) -> None:
    config = load_streaming_config(ROOT / "configs/streaming_demo.yaml")
    fixture = generate_fixture(tmp_path / "mission.mcap", config)
    publisher = CapturingPublisher()
    clock = GatedVirtualClock()
    engine = ReplayEngine(
        config=config,
        fixture_path=fixture,
        scenario_path=ROOT / "demo/scenarios/camera-dropout.yaml",
        epoch_state_path=tmp_path / "epoch.json",
        publisher=publisher,
        monotonic=clock.monotonic,
        sleep=clock.sleep,
    )

    await engine.start(replay_rate=1, scenario_name=None, requested_run_id="injected-run")
    await _wait_until_running(engine)
    injected = await engine.activate_camera_dropout()
    clock.release.set()
    completed = await engine.wait_for_completion()

    records = load_recorded_messages(fixture)
    expected_sequences = [item.record.sequence for item in build_schedule(records, engine.scenario)]
    actual_sequences = [
        value["body"]["sequence"]
        for _key, value in publisher.messages
        if value["envelope_type"] == "telemetry"
    ]
    assert injected["scenario"] == "camera-dropout"
    assert completed["status"] == "completed"
    assert completed["published_messages"] == completed["total_messages"]
    assert actual_sequences == expected_sequences


@pytest.mark.anyio
async def test_camera_dropout_injection_rejects_an_idle_replayer(tmp_path: Path) -> None:
    config = load_streaming_config(ROOT / "configs/streaming_demo.yaml")
    engine = ReplayEngine(
        config=config,
        fixture_path=tmp_path / "not-needed.mcap",
        scenario_path=ROOT / "demo/scenarios/camera-dropout.yaml",
        epoch_state_path=tmp_path / "epoch.json",
        publisher=CapturingPublisher(),
    )

    with pytest.raises(RuntimeError, match="requires a running mission"):
        await engine.activate_camera_dropout()


@pytest.mark.demo_integration
@pytest.mark.anyio
async def test_abort_stops_telemetry_before_the_terminal_lifecycle(tmp_path: Path) -> None:
    config = load_streaming_config(ROOT / "configs/streaming_demo.yaml")
    fixture = generate_fixture(tmp_path / "mission.mcap", config)
    publisher = CapturingPublisher()
    clock = BlockingClock()
    engine = ReplayEngine(
        config=config,
        fixture_path=fixture,
        scenario_path=ROOT / "demo/scenarios/camera-dropout.yaml",
        epoch_state_path=tmp_path / "epoch.json",
        publisher=publisher,
        monotonic=clock.monotonic,
        sleep=clock.sleep,
    )

    await engine.start(replay_rate=1, scenario_name=None, requested_run_id="abort-order")
    await _wait_until_running(engine)
    await engine.abort()

    types = [value["envelope_type"] for _key, value in publisher.messages]
    first_abort = types.index("run_aborted")
    assert types[first_abort:] == ["run_aborted"] * 5


@pytest.mark.demo_integration
@pytest.mark.anyio
async def test_requested_run_id_is_deterministic_for_contract_tests(tmp_path: Path) -> None:
    config = load_streaming_config(ROOT / "configs/streaming_demo.yaml")
    fixture = generate_fixture(tmp_path / "mission.mcap", config)
    publisher = CapturingPublisher()
    clock = VirtualClock()
    engine = ReplayEngine(
        config=config,
        fixture_path=fixture,
        scenario_path=ROOT / "demo/scenarios/camera-dropout.yaml",
        epoch_state_path=tmp_path / "epoch.json",
        publisher=publisher,
        monotonic=clock.monotonic,
        sleep=clock.sleep,
    )

    state = await engine.start(
        replay_rate=5,
        scenario_name=None,
        requested_run_id="contract-run-001",
    )
    await engine.wait_for_completion()

    assert state["run_id"] == "contract-run-001"
    assert {value["run_id"] for _key, value in publisher.messages} == {"contract-run-001"}


@pytest.mark.demo_integration
@pytest.mark.anyio
async def test_completed_run_id_remains_reserved_across_replayer_restart(tmp_path: Path) -> None:
    config = load_streaming_config(ROOT / "configs/streaming_demo.yaml")
    fixture = generate_fixture(tmp_path / "mission.mcap", config)
    state_path = tmp_path / "epoch.json"
    clock = VirtualClock()
    first = ReplayEngine(
        config=config,
        fixture_path=fixture,
        scenario_path=ROOT / "demo/scenarios/camera-dropout.yaml",
        epoch_state_path=state_path,
        publisher=CapturingPublisher(),
        monotonic=clock.monotonic,
        sleep=clock.sleep,
    )

    await first.start(replay_rate=5, scenario_name=None, requested_run_id="completed-run")
    await first.wait_for_completion()

    restarted = ReplayEngine(
        config=config,
        fixture_path=fixture,
        scenario_path=ROOT / "demo/scenarios/camera-dropout.yaml",
        epoch_state_path=state_path,
        publisher=CapturingPublisher(),
    )
    with pytest.raises(RunIdAlreadyAllocatedError, match="completed-run"):
        await restarted.start(
            replay_rate=5,
            scenario_name=None,
            requested_run_id="completed-run",
        )


@pytest.mark.demo_integration
@pytest.mark.anyio
async def test_failed_run_id_remains_reserved(tmp_path: Path) -> None:
    config = load_streaming_config(ROOT / "configs/streaming_demo.yaml")
    fixture = generate_fixture(tmp_path / "mission.mcap", config)
    state_path = tmp_path / "epoch.json"
    engine = ReplayEngine(
        config=config,
        fixture_path=fixture,
        scenario_path=ROOT / "demo/scenarios/camera-dropout.yaml",
        epoch_state_path=state_path,
        publisher=FailingRegistrationPublisher(),
    )

    with pytest.raises(ReplayContractError, match="simulated registration failure"):
        await engine.start(replay_rate=5, scenario_name=None, requested_run_id="failed-run-id")

    restarted = ReplayEngine(
        config=config,
        fixture_path=fixture,
        scenario_path=ROOT / "demo/scenarios/camera-dropout.yaml",
        epoch_state_path=state_path,
        publisher=CapturingPublisher(),
    )
    with pytest.raises(RunIdAlreadyAllocatedError, match="failed-run-id"):
        await restarted.start(
            replay_rate=5,
            scenario_name=None,
            requested_run_id="failed-run-id",
        )


@pytest.mark.demo_integration
@pytest.mark.anyio
async def test_aborted_run_id_remains_reserved_across_replayer_restart(tmp_path: Path) -> None:
    config = load_streaming_config(ROOT / "configs/streaming_demo.yaml")
    fixture = generate_fixture(tmp_path / "mission.mcap", config)
    state_path = tmp_path / "epoch.json"
    clock = BlockingClock()
    engine = ReplayEngine(
        config=config,
        fixture_path=fixture,
        scenario_path=ROOT / "demo/scenarios/camera-dropout.yaml",
        epoch_state_path=state_path,
        publisher=CapturingPublisher(),
        monotonic=clock.monotonic,
        sleep=clock.sleep,
    )

    await engine.start(replay_rate=1, scenario_name=None, requested_run_id="aborted-run")
    await _wait_until_running(engine)
    await engine.abort()

    restarted = ReplayEngine(
        config=config,
        fixture_path=fixture,
        scenario_path=ROOT / "demo/scenarios/camera-dropout.yaml",
        epoch_state_path=state_path,
        publisher=CapturingPublisher(),
    )
    with pytest.raises(RunIdAlreadyAllocatedError, match="aborted-run"):
        await restarted.start(
            replay_rate=1,
            scenario_name=None,
            requested_run_id="aborted-run",
        )


@pytest.mark.demo_integration
@pytest.mark.anyio
async def test_requested_run_id_cannot_escape_the_summary_output_root(tmp_path: Path) -> None:
    config = load_streaming_config(ROOT / "configs/streaming_demo.yaml")
    fixture = generate_fixture(tmp_path / "mission.mcap", config)
    engine = ReplayEngine(
        config=config,
        fixture_path=fixture,
        scenario_path=ROOT / "demo/scenarios/camera-dropout.yaml",
        epoch_state_path=tmp_path / "epoch.json",
        publisher=CapturingPublisher(),
    )

    with pytest.raises(ValueError, match="letters, digits"):
        await engine.start(
            replay_rate=5,
            scenario_name=None,
            requested_run_id="../../outside",
        )


@pytest.mark.demo_integration
@pytest.mark.anyio
async def test_epochs_advance_across_pause_abort_restart_and_replayer_instance(
    tmp_path: Path,
) -> None:
    config = load_streaming_config(ROOT / "configs/streaming_demo.yaml")
    fixture = generate_fixture(tmp_path / "mission.mcap", config)
    state_path = tmp_path / "epoch.json"
    publisher = CapturingPublisher()
    clock = BlockingClock()
    engine = ReplayEngine(
        config=config,
        fixture_path=fixture,
        scenario_path=ROOT / "demo/scenarios/camera-dropout.yaml",
        epoch_state_path=state_path,
        publisher=publisher,
        monotonic=clock.monotonic,
        sleep=clock.sleep,
    )

    first = await engine.start(replay_rate=1, scenario_name=None, requested_run_id="first")
    await _wait_until_running(engine)
    await engine.pause()
    assert engine.state.status == "paused"
    await engine.resume()
    await engine.abort()
    await _finish_cancellation(engine)

    second = await engine.start(replay_rate=1, scenario_name=None, requested_run_id="second")
    await _wait_until_running(engine)
    third = await engine.restart()
    await _wait_until_running(engine)
    await engine.abort()
    await _finish_cancellation(engine)

    restarted_engine = ReplayEngine(
        config=config,
        fixture_path=fixture,
        scenario_path=ROOT / "demo/scenarios/camera-dropout.yaml",
        epoch_state_path=state_path,
        publisher=CapturingPublisher(),
        monotonic=clock.monotonic,
        sleep=clock.sleep,
    )
    fourth = await restarted_engine.start(
        replay_rate=1,
        scenario_name=None,
        requested_run_id="container-restart",
    )
    await restarted_engine.abort()
    await _finish_cancellation(restarted_engine)

    starts = [
        first["stream_start_ms"],
        second["stream_start_ms"],
        third["stream_start_ms"],
        fourth["stream_start_ms"],
    ]
    assert starts == sorted(starts)
    assert len(set(starts)) == 4
    assert all(
        current > previous + 90_000 for previous, current in zip(starts, starts[1:], strict=False)
    )
