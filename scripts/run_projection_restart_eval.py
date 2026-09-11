"""Interrupt the API projection process and measure catch-up to a frozen Kafka boundary."""

from __future__ import annotations

import argparse
import json
import sqlite3
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def offsets(snapshot):
    return {
        f"{row['topic']}:{row['partition']}": row["next_offset"]
        for row in snapshot["consumer_offsets"]
    }


def read_spool(path):
    with sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=10) as connection:
        return {
            "session": json.loads(
                connection.execute("SELECT session FROM state WHERE id=1").fetchone()[0]
            )
        }


def caught_up(snapshot, boundary):
    stored = offsets(snapshot)
    return bool(boundary) and all(stored.get(key, -1) >= value for key, value in boundary.items())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--warmup-s", type=int, default=12)
    parser.add_argument("--outage-s", type=int, default=15)
    parser.add_argument("--duration-s", type=int, default=65)
    parser.add_argument("--domain", type=int, default=65)
    parser.add_argument("--api", default="http://localhost:8000")
    args = parser.parse_args()
    if args.warmup_s + args.outage_s + 25 > args.duration_s:
        parser.error("Leave at least 25 seconds after restart")
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    container = "robot-telemetry-flight-deck-api-1"

    def docker(*command):
        return subprocess.check_output(["docker", *command], text=True, timeout=30).strip()

    def save(name, value):
        (output / name).write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")

    def snapshot(run_id):
        with urllib.request.urlopen(
            args.api + "/api/runs/current/snapshot?run_id=" + run_id, timeout=5
        ) as response:
            return json.load(response)

    original = json.loads(docker("inspect", "--format", "{{json .State}}", container))
    image_id = docker("inspect", "--format", "{{.Image}}", container)
    if not original["Running"]:
        raise RuntimeError("Projection API must be running before this evaluation")
    log = (output / "source.log").open("w")
    worker = subprocess.Popen(
        [
            sys.executable,
            str(ROOT / "scripts/run_gateway_eval.py"),
            "--output",
            str(output / "source"),
            "--fault",
            "clean",
            "--duration-s",
            str(args.duration_s),
            "--domain",
            str(args.domain),
            "--api",
            args.api,
        ],
        stdout=log,
        stderr=subprocess.STDOUT,
        cwd=ROOT,
    )
    stopped = False
    try:
        time.sleep(args.warmup_s)
        spool = read_spool(output / "source/gateway.sqlite")
        run_id = spool["session"]["run_id"]
        before = snapshot(run_id)
        save("before.json", before)
        print("Stopping projection API while DDS and Flink continue", flush=True)
        stopped = True
        docker("stop", "--time", "0", container)
        stop_state = json.loads(docker("inspect", "--format", "{{json .State}}", container))
        time.sleep(args.outage_s)
        boundary = json.loads(
            docker(
                "run",
                "--rm",
                "--network",
                "robot-telemetry-flight-deck_default",
                "-v",
                f"{ROOT / 'scripts'}:/tools:ro",
                "ros-telemetry-gateway:development",
                "python3",
                "/tools/probe_kafka_offsets.py",
                "--baseline",
                json.dumps(offsets(before)),
            )
        )
        save("boundary.json", boundary)
        resumed = time.monotonic()
        docker("start", container)
        stopped = False
        first = None
        reached = None
        deadline = resumed + 30
        while time.monotonic() < deadline:
            try:
                current = snapshot(run_id)
                if first is None:
                    first = current
                if caught_up(current, boundary):
                    reached = current
                    break
            except (OSError, ValueError):
                pass
            time.sleep(0.25)
        elapsed = time.monotonic() - resumed
        save("first-after-restart.json", first)
        save("caught-up.json", reached)
        print(f"Frozen boundary reached: {reached is not None}; elapsed {elapsed:.3f}s", flush=True)
        code = worker.wait(timeout=args.duration_s + 100)
        source = json.loads((output / "source/evaluation.json").read_text())
        final = snapshot(run_id)
        save("final.json", final)
        baseline = offsets(before)
        backlog = sum(max(0, value - baseline.get(key, 0)) for key, value in boundary.items())
        checks = {
            "api_hard_stopped": not stop_state["Running"] and stop_state["ExitCode"] == 137,
            "backlog_accumulated": backlog >= 100,
            "caught_up_within_thirty_seconds": reached is not None and elapsed <= 30,
            "source_evaluation_passed": code == 0 and source["passed"],
            "summaries_verified_after_restart": final["completion"]["verified"],
            "same_run_retained": final["run_id"] == before["run_id"] == run_id,
            "no_active_incidents": not any(row["status"] == "active" for row in final["anomalies"]),
        }
        report = {
            "run_id": run_id,
            "api_image_id": image_id,
            "passed": all(checks.values()),
            "checks": checks,
            "catchup_ms": round(elapsed * 1000),
            "frozen_boundary_distance": backlog,
            "outage_s": args.outage_s,
            "warmup_s": args.warmup_s,
            "source_evaluation": source,
            "scope": (
                "API projection process hard stop and restart; Kafka/Flink stay running; "
                "boundary covers committed data records, excluding broker control markers"
            ),
        }
        save("evaluation.json", report)
        print(json.dumps(report), flush=True)
        raise SystemExit(0 if report["passed"] else 1)
    finally:
        if stopped:
            docker("start", container)
        if worker.poll() is None:
            worker.wait(timeout=args.duration_s + 100)
        log.close()


if __name__ == "__main__":
    main()
