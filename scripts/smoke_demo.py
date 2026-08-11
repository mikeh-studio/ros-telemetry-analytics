#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

EXPECTED_TOPICS = {"/camera/image_raw", "/imu/data", "/odom", "/diagnostics"}


def _json(url: str, *, body: dict | None = None) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(
        url,
        data=data,
        method="POST" if body is not None else "GET",
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        return json.loads(response.read().decode())


def assert_completed_snapshot(
    snapshot: dict[str, Any], *, scenario: str | None, after_stream_ms: int | None = None
) -> None:
    assert snapshot["completion"]["verified"] is True
    assert snapshot["completion"]["summary_file_count"] == 4
    assert snapshot["run"]["payload"]["status"] == "summary_ready"
    assert snapshot["mission_progress_ms"] == 90_000
    assert set(snapshot["mission_summaries"]) == EXPECTED_TOPICS
    if after_stream_ms is not None:
        assert snapshot["run_start_stream_ms"] > after_stream_ms

    summaries = snapshot["mission_summaries"]
    if scenario is None:
        assert snapshot["incident_history"] == []
        assert all(summary["payload"]["status"] == "ok" for summary in summaries.values())
        return

    camera = summaries["/camera/image_raw"]["payload"]
    assert camera["status"] == "warn"
    assert camera["accepted_late_count"] == 2
    assert camera["duplicate_count"] == 0
    assert camera["too_late_count"] == 0
    assert camera["gap_event_count"] >= 1
    assert camera["estimated_dropped_messages"] > 0
    assert all(
        summaries[topic]["payload"]["status"] == "ok"
        for topic in EXPECTED_TOPICS - {"/camera/image_raw"}
    )
    gap_history = [
        incident
        for incident in snapshot["incident_history"]
        if incident["topic"] == "/camera/image_raw" and incident["condition_type"] == "GAP"
    ]
    assert [incident["status"] for incident in gap_history] == ["active", "recovered"]
    assert gap_history[0]["anomaly_id"] == gap_history[1]["anomaly_id"]
    assert [incident["revision"] for incident in gap_history] == [0, 1]
    assert snapshot["incident_history"] == gap_history
    assert not [incident for incident in snapshot["anomalies"] if incident["status"] == "active"]
    assert snapshot["robot_health"]["payload"]["status"] == "healthy"


def _wait_for_stack(api: str, web: str, deadline: float) -> None:
    last_error = "not started"
    while time.monotonic() < deadline:
        try:
            health = _json(f"{api}/api/health")
            with urllib.request.urlopen(web, timeout=5) as response:
                if health["status"] == "ready" and response.status == 200:
                    return
        except (urllib.error.URLError, OSError, KeyError) as exc:
            last_error = str(exc)
        time.sleep(2)
    raise TimeoutError(f"stack did not become ready: {last_error}")


def _start_replay(api: str, *, rate: int, scenario: str | None, run_id: str | None) -> str:
    request_body: dict[str, Any] = {"rate": rate, "scenario": scenario}
    if run_id is not None:
        request_body["run_id"] = run_id
    started = _json(f"{api}/api/replay/start", body=request_body)
    return str(started["run_id"])


def main() -> None:
    parser = argparse.ArgumentParser(description="Exercise one recorded Compose mission.")
    parser.add_argument("--api", default="http://127.0.0.1:8000")
    parser.add_argument("--web", default="http://127.0.0.1:3000")
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument("--run-id")
    parser.add_argument("--rate", type=int, choices=(1, 5), default=5)
    parser.add_argument("--scenario", choices=("camera-dropout",))
    parser.add_argument("--result-file", type=Path)
    parser.add_argument("--after-result", type=Path)
    parser.add_argument("--wait-only", action="store_true")
    args = parser.parse_args()
    deadline = time.monotonic() + args.timeout
    wait_started = time.monotonic()
    _wait_for_stack(args.api, args.web, deadline)
    stack_ready_seconds = round(time.monotonic() - wait_started, 3)
    if args.wait_only:
        print(json.dumps({"status": "ready", "stack_ready_seconds": stack_ready_seconds}))
        return

    after_stream_ms = None
    if args.after_result:
        previous = json.loads(args.after_result.read_text(encoding="utf-8"))
        after_stream_ms = int(previous["latest_stream_ms"])

    run_id = _start_replay(
        args.api,
        rate=args.rate,
        scenario=args.scenario,
        run_id=args.run_id,
    )
    while time.monotonic() < deadline:
        snapshot = _json(f"{args.api}/api/runs/current/snapshot")
        if snapshot.get("run_id") == run_id and snapshot.get("completion", {}).get("verified"):
            assert_completed_snapshot(
                snapshot,
                scenario=args.scenario,
                after_stream_ms=after_stream_ms,
            )
            result = {
                "status": "passed",
                "run_id": run_id,
                "scenario": args.scenario,
                "run_start_stream_ms": snapshot["run_start_stream_ms"],
                "latest_stream_ms": snapshot["latest_stream_ms"],
                "stack_ready_seconds": stack_ready_seconds,
            }
            if args.result_file:
                args.result_file.write_text(
                    json.dumps(result, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8",
                )
            print(json.dumps(result, sort_keys=True))
            return
        time.sleep(2)
    raise TimeoutError(f"run {run_id} did not complete before the smoke-test deadline")


if __name__ == "__main__":
    main()
