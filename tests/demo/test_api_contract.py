from __future__ import annotations

import asyncio
import json

import polars as pl

from demo.api import app as api_module
from demo.api.app import app


def test_public_api_matches_the_flight_deck_contract() -> None:
    routes = {(method, route.path) for route in app.routes for method in route.methods or set()}
    expected = {
        ("GET", "/api/health"),
        ("GET", "/api/runs/current"),
        ("GET", "/api/runs/current/snapshot"),
        ("GET", "/api/runs/current/events"),
        ("POST", "/api/replay/start"),
        ("POST", "/api/replay/pause"),
        ("POST", "/api/replay/resume"),
        ("POST", "/api/replay/restart"),
        ("POST", "/api/scenarios/camera-dropout"),
        ("GET", "/api/flink/summary"),
        ("GET", "/api/localization/evaluation"),
    }
    assert expected <= routes
    legacy_aliases = {
        ("GET", "/api/snapshot"),
        ("POST", "/api/runs/start"),
        ("POST", "/api/runs/pause"),
        ("POST", "/api/runs/resume"),
        ("POST", "/api/runs/restart"),
    }
    assert routes.isdisjoint(legacy_aliases)


def test_localization_evaluation_serves_bounded_trajectory(tmp_path, monkeypatch) -> None:
    evaluation = tmp_path / "evaluation"
    evaluation.mkdir()
    (evaluation / "localization_eval.json").write_text(
        json.dumps(
            {
                "sample_count": 2,
                "input_files": ["/private/path/run.processed.parquet"],
                "sample_metrics": {"precision": 0.8, "recall": 0.5, "f1": 0.6},
                "event_metrics": {"precision": 0.75, "recall": 0.7},
            }
        )
    )
    pl.DataFrame(
        {
            "timestamp_ns": [1_000_000_000, 2_000_000_000],
            "segment_id": [0, 0],
            "ground_truth_x": [0.0, 1.0],
            "ground_truth_y": [0.0, 0.0],
            "estimated_x": [0.0, 1.2],
            "estimated_y": [0.0, 0.1],
            "position_error_m": [0.0, 0.22],
            "label_failure": [False, True],
            "detector_failure": [False, True],
        }
    ).write_parquet(evaluation / "localization_samples.parquet")
    pl.DataFrame(
        {
            "expected_event_id": ["expected-1"],
            "observed_event_id": ["observed-1"],
            "detected": [True],
        }
    ).write_parquet(evaluation / "localization_event_matches.parquet")
    monkeypatch.setattr(api_module, "LOCALIZATION_EVAL_DIR", evaluation)

    payload = asyncio.run(api_module.localization_evaluation())

    assert payload["status"] == "available"
    assert payload["summary"]["input_files"] == ["run.processed.parquet"]
    assert payload["evaluation_start_timestamp_ns"] == 1_000_000_000
    assert payload["trajectory"][1]["elapsed_ms"] == 1_000
    assert payload["event_matches"][0]["detected"] is True


def test_localization_evaluation_reports_missing_artifacts(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(api_module, "LOCALIZATION_EVAL_DIR", tmp_path)

    payload = asyncio.run(api_module.localization_evaluation())

    assert payload["status"] == "unavailable"
    assert "evaluate-localization" in payload["detail"]


def test_localization_trajectory_sampling_preserves_short_failures(tmp_path, monkeypatch) -> None:
    evaluation = tmp_path / "evaluation"
    evaluation.mkdir()
    sample_count = 1_200
    (evaluation / "localization_eval.json").write_text(
        json.dumps(
            {
                "sample_count": sample_count,
                "sample_metrics": {"precision": 1.0, "recall": 1.0, "f1": 1.0},
                "event_metrics": {"precision": 1.0, "recall": 1.0},
            }
        )
    )
    failure = [False] * sample_count
    failure[1] = True
    pl.DataFrame(
        {
            "timestamp_ns": list(range(sample_count)),
            "segment_id": [0] * sample_count,
            "ground_truth_x": [float(index) for index in range(sample_count)],
            "ground_truth_y": [0.0] * sample_count,
            "estimated_x": [float(index) for index in range(sample_count)],
            "estimated_y": [0.0] * sample_count,
            "position_error_m": [0.0] * sample_count,
            "label_failure": failure,
            "detector_failure": failure,
        }
    ).write_parquet(evaluation / "localization_samples.parquet")
    pl.DataFrame(
        {
            "expected_event_id": ["expected-1"],
            "observed_event_id": ["observed-1"],
            "detected": [True],
        }
    ).write_parquet(evaluation / "localization_event_matches.parquet")
    monkeypatch.setattr(api_module, "LOCALIZATION_EVAL_DIR", evaluation)

    payload = asyncio.run(api_module.localization_evaluation())

    assert payload["status"] == "available"
    assert payload["trajectory_sample_count"] <= 600
    assert any(row["label_failure"] for row in payload["trajectory"])


def test_camera_dropout_endpoint_uses_the_running_mission_injector(monkeypatch) -> None:
    calls: list[tuple[str, dict | None]] = []

    async def fake_replayer_post(path: str, query: dict | None = None) -> dict:
        calls.append((path, query))
        return {"status": "running", "scenario": "camera-dropout"}

    monkeypatch.setattr(api_module, "_replayer_post", fake_replayer_post)

    result = asyncio.run(api_module.camera_dropout())

    assert result["scenario"] == "camera-dropout"
    assert calls == [("/scenarios/camera-dropout", None)]


def test_api_restart_resumes_pending_summary_verification(monkeypatch) -> None:
    scheduled: list[str] = []

    monkeypatch.setattr(
        api_module.STORE,
        "snapshot",
        lambda: {
            "run_id": "restored-run",
            "run": {"payload": {"status": "summary_ready"}},
            "completion": {"verified": False},
        },
    )
    monkeypatch.setattr(api_module, "_schedule_summary_verification", scheduled.append)

    asyncio.run(api_module._resume_pending_summary_verification())

    assert scheduled == ["restored-run"]


def test_health_reports_each_runtime_authority(monkeypatch) -> None:
    class FakeTask:
        @staticmethod
        def done() -> bool:
            return False

    class FakeResponse:
        status = 200

        def __init__(self, payload: dict | None = None) -> None:
            self.payload = payload

        def __enter__(self):
            return self

        def __exit__(self, *_args) -> None:
            return None

        def read(self) -> bytes:
            return json.dumps(self.payload or {}).encode()

    def urlopen(url: str, timeout: int):
        del timeout
        if url.endswith("/jobs/overview"):
            return FakeResponse({"jobs": [{"state": "RUNNING"}]})
        return FakeResponse()

    monkeypatch.setattr(api_module.CONSUMER, "_task", FakeTask())
    monkeypatch.setattr(api_module.CONSUMER, "consumer", object())
    monkeypatch.setattr(api_module.urllib.request, "urlopen", urlopen)

    response = asyncio.run(api_module.health())
    payload = json.loads(response.body)
    assert response.status_code == 200
    assert payload["status"] == "ready"
    assert payload["services"] == {
        "kafka": "ready",
        "flink": "ready",
        "flink_job": "ready",
        "projection_api": "ready",
        "replayer": "ready",
    }


def test_flink_summary_exposes_curated_runtime_authorities(monkeypatch) -> None:
    class FakeResponse:
        status = 200

        def __init__(self, payload):
            self.payload = payload

        def __enter__(self):
            return self

        def __exit__(self, *_args) -> None:
            return None

        def read(self) -> bytes:
            return json.dumps(self.payload).encode()

    def urlopen(url: str, timeout: int):
        del timeout
        path = url.split("http://flink-jobmanager:8081", 1)[-1]
        if path == "/jobs/overview":
            return FakeResponse({"jobs": [{"jid": "job-1", "state": "RUNNING"}]})
        if path == "/jobs/job-1/checkpoints":
            return FakeResponse(
                {
                    "latest": {
                        "completed": {
                            "id": 7,
                            "status": "COMPLETED",
                            "latest_ack_timestamp": 98_000,
                            "end_to_end_duration": 125,
                        }
                    }
                }
            )
        if path == "/jobs/job-1":
            return FakeResponse(
                {
                    "vertices": [
                        {
                            "id": "source",
                            "name": "Source: telemetry-kafka-source",
                            "metrics": {"read-records": 20, "write-records": 20},
                        },
                        {
                            "id": "topic-health",
                            "name": "stateful-topic-health -> metrics",
                            "metrics": {"read-records": 20, "write-records": 10},
                        },
                    ]
                }
            )
        available = {
            "/jobs/job-1/vertices/source/subtasks/metrics": [
                {"id": "KafkaSourceReader.records-lag-max"}
            ],
            "/jobs/job-1/vertices/topic-health/subtasks/metrics": [
                {"id": "currentInputWatermark"},
                {"id": "robot_telemetry.events_processed"},
                {"id": "robot_telemetry.accepted_late_events"},
                {"id": "robot_telemetry.duplicate_events"},
                {"id": "robot_telemetry.too_late_events"},
            ],
            "/jobs/job-1/metrics": [{"id": "numRestarts"}],
        }
        if path in available:
            return FakeResponse(available[path])
        metric_values = {
            "KafkaSourceReader.records-lag-max": 3,
            "currentInputWatermark": 67_010,
            "robot_telemetry.events_processed": 1_000,
            "robot_telemetry.accepted_late_events": 2,
            "robot_telemetry.duplicate_events": 1,
            "robot_telemetry.too_late_events": 0,
            "numRestarts": 4,
        }
        if "?get=" in path:
            metric_id = path.split("?get=", 1)[1].split("&", 1)[0]
            aggregate = path.split("&agg=", 1)[1]
            return FakeResponse([{aggregate: str(metric_values[metric_id])}])
        raise AssertionError(f"Unexpected Flink URL: {url}")

    monkeypatch.setattr(api_module.urllib.request, "urlopen", urlopen)
    monkeypatch.setattr(api_module.time, "time", lambda: 100.0)

    payload = asyncio.run(api_module.flink_summary())

    assert payload["status"] == "available"
    assert payload["consumer_lag"] == 3
    assert payload["watermark_ms"] == 67_010
    assert payload["checkpoints"] == {
        "id": 7,
        "status": "COMPLETED",
        "completed_at_ms": 98_000,
        "age_ms": 2_000,
        "duration_ms": 125,
    }
    assert payload["restarts"] == 4
    assert payload["records_in"] == 40
    assert payload["records_out"] == 30
    assert payload["events_processed"] == 1_000
    assert payload["accepted_late_events"] == 2
    assert payload["duplicate_events"] == 1
    assert payload["too_late_events"] == 0
    assert payload["projection_lag"] is None
