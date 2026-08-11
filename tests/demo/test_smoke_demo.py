from __future__ import annotations

import pytest

from scripts import smoke_demo
from scripts.smoke_demo import EXPECTED_TOPICS, assert_completed_snapshot


def _summary(status: str, **overrides) -> dict:
    payload = {
        "status": status,
        "accepted_late_count": 0,
        "duplicate_count": 0,
        "too_late_count": 0,
        "gap_event_count": 0,
        "estimated_dropped_messages": 0,
        **overrides,
    }
    return {"payload": payload}


def _snapshot() -> dict:
    return {
        "completion": {"verified": True, "summary_file_count": 4},
        "run": {"payload": {"status": "summary_ready"}},
        "mission_progress_ms": 90_000,
        "run_start_stream_ms": 200_000,
        "latest_stream_ms": 290_000,
        "mission_summaries": {topic: _summary("ok") for topic in EXPECTED_TOPICS},
        "incident_history": [],
        "anomalies": [],
        "robot_health": {"payload": {"status": "healthy"}},
    }


def test_clean_smoke_contract_and_epoch_order() -> None:
    assert_completed_snapshot(_snapshot(), scenario=None, after_stream_ms=199_999)


def test_dropout_smoke_contract_requires_one_recovered_gap() -> None:
    snapshot = _snapshot()
    snapshot["mission_summaries"]["/camera/image_raw"] = _summary(
        "warn",
        accepted_late_count=2,
        gap_event_count=1,
        estimated_dropped_messages=237,
    )
    snapshot["incident_history"] = [
        {
            "anomaly_id": "gap-1",
            "revision": 0,
            "topic": "/camera/image_raw",
            "condition_type": "GAP",
            "status": "active",
        },
        {
            "anomaly_id": "gap-1",
            "revision": 1,
            "topic": "/camera/image_raw",
            "condition_type": "GAP",
            "status": "recovered",
        },
    ]
    snapshot["anomalies"] = [snapshot["incident_history"][1]]

    assert_completed_snapshot(snapshot, scenario="camera-dropout")


def test_dropout_smoke_contract_rejects_a_late_frame_that_recovers_the_incident() -> None:
    snapshot = _snapshot()
    snapshot["mission_summaries"]["/camera/image_raw"] = _summary(
        "warn", accepted_late_count=1, gap_event_count=1, estimated_dropped_messages=237
    )

    with pytest.raises(AssertionError):
        assert_completed_snapshot(snapshot, scenario="camera-dropout")


def test_wait_for_stack_retries_connection_resets(monkeypatch: pytest.MonkeyPatch) -> None:
    attempts = iter((ConnectionResetError("API restarting"), {"status": "ready"}))

    def fake_json(_url: str) -> dict:
        result = next(attempts)
        if isinstance(result, Exception):
            raise result
        return result

    class ReadyResponse:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

    monkeypatch.setattr(smoke_demo, "_json", fake_json)
    monkeypatch.setattr(
        smoke_demo.urllib.request,
        "urlopen",
        lambda *_args, **_kwargs: ReadyResponse(),
    )
    monkeypatch.setattr(smoke_demo.time, "sleep", lambda _seconds: None)

    smoke_demo._wait_for_stack("http://api", "http://web", smoke_demo.time.monotonic() + 1)
