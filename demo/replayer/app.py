from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Literal

from fastapi import FastAPI, HTTPException, Query

from demo.common.config import load_streaming_config
from demo.replayer.engine import ReplayContractError, ReplayEngine
from demo.replayer.generate_fixture import generate_fixture
from demo.replayer.kafka import KafkaEnvelopePublisher

ROOT = Path(os.environ.get("DEMO_ROOT", Path(__file__).resolve().parents[2])).resolve()
CONFIG = load_streaming_config(ROOT / "configs/streaming_demo.yaml")
FIXTURE = ROOT / CONFIG.demo.fixture_path
PUBLISHER = KafkaEnvelopePublisher(
    bootstrap_servers=os.environ.get("KAFKA_BOOTSTRAP_SERVERS", CONFIG.kafka.bootstrap_servers),
    topic="telemetry.events.v1",
)
ENGINE = ReplayEngine(
    config=CONFIG,
    fixture_path=FIXTURE,
    scenario_path=ROOT / "demo/scenarios/camera-dropout.yaml",
    epoch_state_path=ROOT / "demo-state/replay-epoch.json",
    publisher=PUBLISHER,
)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    generate_fixture(FIXTURE, CONFIG)
    await PUBLISHER.start()
    yield
    await ENGINE.abort()
    await PUBLISHER.stop()


app = FastAPI(title="Recorded Mission Replayer", lifespan=lifespan)


def _translate_error(exc: Exception) -> HTTPException:
    status = (
        503
        if isinstance(exc, ReplayContractError)
        else 409
        if isinstance(exc, RuntimeError)
        else 422
    )
    return HTTPException(status_code=status, detail=str(exc))


@app.get("/healthz")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/state")
async def state() -> dict[str, object]:
    return ENGINE.snapshot()


@app.post("/start")
async def start(
    replay_rate: Annotated[int, Query(alias="rate")] = 1,
    scenario: Literal["camera-dropout"] | None = None,
    run_id: str | None = None,
) -> dict[str, object]:
    try:
        return await ENGINE.start(
            replay_rate=replay_rate,
            scenario_name=scenario,
            requested_run_id=run_id,
        )
    except (RuntimeError, ValueError) as exc:
        raise _translate_error(exc) from exc


@app.post("/pause")
async def pause() -> dict[str, object]:
    try:
        return await ENGINE.pause()
    except RuntimeError as exc:
        raise _translate_error(exc) from exc


@app.post("/resume")
async def resume() -> dict[str, object]:
    try:
        return await ENGINE.resume()
    except RuntimeError as exc:
        raise _translate_error(exc) from exc


@app.post("/restart")
async def restart() -> dict[str, object]:
    try:
        return await ENGINE.restart()
    except (RuntimeError, ValueError) as exc:
        raise _translate_error(exc) from exc


@app.post("/scenarios/camera-dropout")
async def camera_dropout() -> dict[str, object]:
    try:
        return await ENGINE.activate_camera_dropout()
    except RuntimeError as exc:
        raise _translate_error(exc) from exc


@app.post("/abort")
async def abort() -> dict[str, object]:
    return await ENGINE.abort()
