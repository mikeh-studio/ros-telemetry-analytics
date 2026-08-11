from __future__ import annotations

import asyncio
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from demo.api.consumer import ProjectionConsumer
from demo.api.store import ProjectionStore
from demo.common.config import load_streaming_config

ROOT = Path(os.environ.get("DEMO_ROOT", Path(__file__).resolve().parents[2])).resolve()
CONFIG = load_streaming_config(ROOT / "configs/streaming_demo.yaml")
STORE = ProjectionStore(
    Path(os.environ.get("PROJECTION_DB_PATH", ROOT / "demo-state/projection.db")),
    Path(os.environ.get("DEMO_OUTPUT_ROOT", ROOT / "data/demo-output")),
)
REPLAYER_URL = os.environ.get("REPLAYER_URL", "http://replayer:8001")
FLINK_URL = os.environ.get("FLINK_URL", "http://flink-jobmanager:8081")


class EventHub:
    def __init__(self) -> None:
        self._subscribers: set[asyncio.Queue[dict[str, Any]]] = set()

    async def publish(self, event: dict[str, Any]) -> None:
        for queue in tuple(self._subscribers):
            if queue.full():
                try:
                    queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass
            queue.put_nowait(event)

    async def subscribe(self) -> AsyncIterator[dict[str, Any]]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=100)
        self._subscribers.add(queue)
        try:
            while True:
                try:
                    yield await asyncio.wait_for(queue.get(), timeout=15)
                except TimeoutError:
                    yield {"type": "heartbeat"}
        finally:
            self._subscribers.discard(queue)


HUB = EventHub()
VERIFYING_RUNS: set[str] = set()


async def _verify_summary_files(run_id: str) -> None:
    try:
        for _attempt in range(60):
            result = await asyncio.to_thread(STORE.verify_completion, run_id)
            if result["verified"]:
                await HUB.publish({"type": "completed", "run_id": run_id, "completion": result})
                return
            await asyncio.sleep(1)
        await HUB.publish(
            {
                "type": "completion_failed",
                "run_id": run_id,
                "detail": (
                    "Summary files did not satisfy the durable four-topic contract "
                    "within 60 seconds"
                ),
            }
        )
    finally:
        VERIFYING_RUNS.discard(run_id)


def _schedule_summary_verification(run_id: str) -> None:
    if run_id in VERIFYING_RUNS:
        return
    VERIFYING_RUNS.add(run_id)
    asyncio.create_task(
        _verify_summary_files(run_id),
        name=f"verify-summary-{run_id}",
    )


async def _resume_pending_summary_verification() -> None:
    current = await asyncio.to_thread(STORE.snapshot)
    run = current.get("run") or {}
    if (
        current.get("run_id")
        and run.get("payload", {}).get("status") == "summary_ready"
        and not current.get("completion", {}).get("verified", False)
    ):
        _schedule_summary_verification(str(current["run_id"]))


async def _on_projected(event: dict[str, Any]) -> None:
    await HUB.publish(event)
    payload = event.get("payload", {})
    if (
        event.get("stream_kind") == "metric"
        and payload.get("metric_type") == "run_status"
        and payload.get("payload", {}).get("status") == "summary_ready"
    ):
        run_id = str(payload["run_id"])
        _schedule_summary_verification(run_id)


CONSUMER = ProjectionConsumer(
    bootstrap_servers=os.environ.get("KAFKA_BOOTSTRAP_SERVERS", CONFIG.kafka.bootstrap_servers),
    store=STORE,
    on_projected=_on_projected,
)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    await CONSUMER.start()
    await _resume_pending_summary_verification()
    yield
    await CONSUMER.stop()


app = FastAPI(title="Robot Telemetry Flight Deck API", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[os.environ.get("WEB_ORIGIN", "http://localhost:3000")],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


class StartRequest(BaseModel):
    rate: int = Field(default=1)
    scenario: str | None = None
    run_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$",
    )


async def _replayer_post(path: str, query: dict[str, str | int] | None = None) -> dict[str, Any]:
    suffix = f"?{urllib.parse.urlencode(query)}" if query else ""

    def call() -> dict[str, Any]:
        request = urllib.request.Request(f"{REPLAYER_URL}{path}{suffix}", method="POST")
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8")
            raise HTTPException(status_code=exc.code, detail=detail) from exc
        except urllib.error.URLError as exc:
            raise HTTPException(status_code=503, detail="Replay service is unavailable") from exc

    return await asyncio.to_thread(call)


@app.get("/healthz")
@app.get("/api/health")
async def health() -> JSONResponse:
    def probe(url: str) -> bool:
        try:
            with urllib.request.urlopen(url, timeout=2) as response:
                return 200 <= response.status < 300
        except (urllib.error.URLError, TimeoutError):
            return False

    def flink_job_probe() -> bool:
        try:
            with urllib.request.urlopen(f"{FLINK_URL}/jobs/overview", timeout=2) as response:
                payload = json.loads(response.read().decode("utf-8"))
            return any(job.get("state") == "RUNNING" for job in payload.get("jobs", []))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
            return False

    replayer_ready, flink_ready, flink_job_ready = await asyncio.gather(
        asyncio.to_thread(probe, f"{REPLAYER_URL}/healthz"),
        asyncio.to_thread(probe, f"{FLINK_URL}/overview"),
        asyncio.to_thread(flink_job_probe),
    )
    services = {
        "kafka": "ready" if CONSUMER.healthy else "unknown",
        "flink": "ready" if flink_ready else "unknown",
        "flink_job": "ready" if flink_job_ready else "unknown",
        "projection_api": "ready",
        "replayer": "ready" if replayer_ready else "unknown",
    }
    ready = all(value == "ready" for value in services.values())
    return JSONResponse(
        status_code=200 if ready else 503,
        content={
            "status": "ready" if ready else "starting",
            "services": services,
            "source": "recorded_replay",
        },
    )


@app.get("/api/snapshot")
@app.get("/api/runs/current/snapshot")
async def snapshot(run_id: str | None = Query(default=None)) -> dict[str, Any]:
    return await asyncio.to_thread(STORE.snapshot, run_id)


@app.get("/api/runs/current")
async def current_run() -> dict[str, Any]:
    current = await asyncio.to_thread(STORE.snapshot)
    return {
        "run_id": current["run_id"],
        "run": current["run"],
        "source": current["source"],
        "completion": current["completion"],
    }


@app.get("/api/events")
@app.get("/api/runs/current/events")
async def events(request: Request) -> StreamingResponse:
    async def stream() -> AsyncIterator[str]:
        initial = await asyncio.to_thread(STORE.snapshot)
        yield f"event: snapshot\ndata: {json.dumps(initial, separators=(',', ':'))}\n\n"
        async for event in HUB.subscribe():
            if await request.is_disconnected():
                return
            event_type = str(event.get("stream_kind", event.get("type", "update")))
            yield f"event: {event_type}\ndata: {json.dumps(event, separators=(',', ':'))}\n\n"

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/api/runs/start")
@app.post("/api/replay/start")
async def start_run(request: StartRequest) -> dict[str, Any]:
    if request.rate not in CONFIG.demo.supported_rates:
        raise HTTPException(status_code=422, detail="Replay rate must be 1 or 5")
    if request.scenario and request.rate != 1:
        raise HTTPException(status_code=422, detail="Fault injection is available only at 1x")
    query: dict[str, str | int] = {"rate": request.rate}
    if request.scenario:
        query["scenario"] = request.scenario
    if request.run_id:
        query["run_id"] = request.run_id
    return await _replayer_post("/start", query)


@app.post("/api/runs/pause")
@app.post("/api/replay/pause")
async def pause_run() -> dict[str, Any]:
    return await _replayer_post("/pause")


@app.post("/api/runs/resume")
@app.post("/api/replay/resume")
async def resume_run() -> dict[str, Any]:
    return await _replayer_post("/resume")


@app.post("/api/runs/restart")
@app.post("/api/replay/restart")
async def restart_run() -> dict[str, Any]:
    return await _replayer_post("/restart")


@app.post("/api/scenarios/camera-dropout")
async def camera_dropout() -> dict[str, Any]:
    return await _replayer_post("/scenarios/camera-dropout")


@app.get("/api/flink/summary")
async def flink_summary() -> dict[str, Any]:
    def fetch() -> dict[str, Any]:
        def get_json(path: str) -> dict[str, Any] | list[dict[str, Any]]:
            with urllib.request.urlopen(f"{FLINK_URL}{path}", timeout=3) as response:
                return json.loads(response.read().decode("utf-8"))

        try:
            overview = get_json("/jobs/overview")
            assert isinstance(overview, dict)
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
            return {
                "status": "unknown",
                "job": None,
                "consumer_lag": None,
                "watermark_ms": None,
                "checkpoints": None,
                "restarts": None,
                "records_in": None,
                "records_out": None,
                "events_processed": None,
                "accepted_late_events": None,
                "duplicate_events": None,
                "too_late_events": None,
            }
        jobs = overview.get("jobs", [])
        job = jobs[0] if jobs else None
        if job is None:
            return {
                "status": "unknown",
                "job": None,
                "consumer_lag": None,
                "watermark_ms": None,
                "checkpoints": None,
                "restarts": None,
                "records_in": None,
                "records_out": None,
                "events_processed": None,
                "accepted_late_events": None,
                "duplicate_events": None,
                "too_late_events": None,
            }
        job_id = str(job["jid"])
        checkpoint_summary = None
        records_in = None
        records_out = None
        watermark = None
        source_lag = None
        events_processed = None
        accepted_late_events = None
        duplicate_events = None
        too_late_events = None
        restart_count = None

        def aggregated_metric(values: Any, aggregate: str) -> int | None:
            if not isinstance(values, list) or not values or not isinstance(values[0], dict):
                return None
            value = values[0].get("value", values[0].get(aggregate))
            if value is None:
                return None
            try:
                return int(float(value))
            except (TypeError, ValueError, OverflowError):
                return None

        def metric_value(vertex_id: str, suffix: str, aggregate: str) -> int | None:
            available = get_json(f"/jobs/{job_id}/vertices/{vertex_id}/subtasks/metrics")
            if not isinstance(available, list):
                return None
            metric_id = next(
                (str(item["id"]) for item in available if str(item.get("id", "")).endswith(suffix)),
                None,
            )
            if metric_id is None:
                return None
            values = get_json(
                f"/jobs/{job_id}/vertices/{vertex_id}/subtasks/metrics"
                f"?get={urllib.parse.quote(metric_id)}&agg={aggregate}"
            )
            return aggregated_metric(values, aggregate)

        def job_metric_value(suffix: str, aggregate: str) -> int | None:
            available = get_json(f"/jobs/{job_id}/metrics")
            if not isinstance(available, list):
                return None
            metric_id = next(
                (str(item["id"]) for item in available if str(item.get("id", "")).endswith(suffix)),
                None,
            )
            if metric_id is None:
                return None
            values = get_json(
                f"/jobs/{job_id}/metrics?get={urllib.parse.quote(metric_id)}&agg={aggregate}"
            )
            return aggregated_metric(values, aggregate)

        try:
            checkpoints = get_json(f"/jobs/{job_id}/checkpoints")
            assert isinstance(checkpoints, dict)
            completed = checkpoints.get("latest", {}).get("completed")
            checkpoint_summary = (
                {
                    "id": completed.get("id"),
                    "status": completed.get("status", "COMPLETED"),
                    "completed_at_ms": completed.get("latest_ack_timestamp"),
                    "age_ms": max(
                        0,
                        int(time.time() * 1_000) - int(completed.get("latest_ack_timestamp", 0)),
                    ),
                    "duration_ms": completed.get("end_to_end_duration"),
                }
                if completed
                else None
            )
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
            pass
        try:
            detail = get_json(f"/jobs/{job_id}")
            assert isinstance(detail, dict)
            vertices = detail.get("vertices", [])
            records_in = sum(
                int(vertex.get("metrics", {}).get("read-records", 0)) for vertex in vertices
            )
            records_out = sum(
                int(vertex.get("metrics", {}).get("write-records", 0)) for vertex in vertices
            )
            topic_vertex = next(
                (
                    vertex
                    for vertex in vertices
                    if "stateful-topic-health" in vertex.get("name", "")
                ),
                None,
            )
            if topic_vertex:
                watermark = metric_value(topic_vertex["id"], "currentInputWatermark", "min")
                events_processed = metric_value(
                    topic_vertex["id"], "robot_telemetry.events_processed", "sum"
                )
                accepted_late_events = metric_value(
                    topic_vertex["id"], "robot_telemetry.accepted_late_events", "sum"
                )
                duplicate_events = metric_value(
                    topic_vertex["id"], "robot_telemetry.duplicate_events", "sum"
                )
                too_late_events = metric_value(
                    topic_vertex["id"], "robot_telemetry.too_late_events", "sum"
                )
            source_vertex = next(
                (
                    vertex
                    for vertex in vertices
                    if "telemetry-kafka-source" in vertex.get("name", "")
                ),
                None,
            )
            if source_vertex:
                source_lag = metric_value(source_vertex["id"], "records-lag-max", "max")
            restart_count = job_metric_value("numRestarts", "max")
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, ValueError):
            pass
        return {
            "status": "available",
            "job": job,
            "consumer_lag": source_lag,
            "watermark_ms": watermark,
            "checkpoints": checkpoint_summary,
            "restarts": restart_count,
            "records_in": records_in,
            "records_out": records_out,
            "events_processed": events_processed,
            "accepted_late_events": accepted_late_events,
            "duplicate_events": duplicate_events,
            "too_late_events": too_late_events,
        }

    result = await asyncio.to_thread(fetch)
    result["projection_lag"] = CONSUMER.projection_lag()
    return result
