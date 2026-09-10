"""Hard-stop a Flink worker and prove checkpoint restoration during live DDS traffic."""

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


def restored_checkpoint(before, after):
    restored = after.get("latest", {}).get("restored") or {}
    completed = after.get("latest", {}).get("completed") or {}
    previous = before.get("latest", {}).get("completed") or {}
    return (
        after.get("counts", {}).get("restored", 0) > before.get("counts", {}).get("restored", 0)
        and restored.get("id", -1) >= previous.get("id", 0)
        and completed.get("id", -1) > restored.get("id", -1)
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--duration-s", type=int, default=100)
    parser.add_argument("--warmup-s", type=int, default=18)
    parser.add_argument("--outage-s", type=int, default=12)
    parser.add_argument("--domain", type=int, default=68)
    args = parser.parse_args()
    if args.duration_s < args.warmup_s + args.outage_s + 65:
        parser.error("Leave 65 seconds after restart for recovery and source completion")
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)

    def fetch(path):
        with urllib.request.urlopen("http://localhost:8081" + path, timeout=5) as response:
            return json.load(response)

    def save(name, value):
        (output / name).write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")

    def docker(*args):
        return subprocess.check_output(["docker", *args], text=True, timeout=30).strip()

    jobs = [job for job in fetch("/jobs/overview")["jobs"] if job["state"] == "RUNNING"]
    if len(jobs) != 1:
        raise RuntimeError("Expected one running local Flink job")
    job_id = jobs[0]["jid"]
    container = "robot-telemetry-flight-deck-flink-taskmanager-1"
    image = docker("inspect", "--format", "{{.Image}}", container)
    log = (output / "source.log").open("w")
    source = subprocess.Popen(
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
        ],
        stdout=log,
        stderr=subprocess.STDOUT,
        cwd=ROOT,
    )
    stopped = False
    try:
        time.sleep(args.warmup_s)
        with sqlite3.connect(f"file:{output / 'source/gateway.sqlite'}?mode=ro", uri=True) as conn:
            session = json.loads(conn.execute("SELECT session FROM state WHERE id=1").fetchone()[0])
        before = fetch(f"/jobs/{job_id}/checkpoints")
        if (before.get("latest", {}).get("completed") or {}).get("trigger_timestamp", 0) <= session[
            "start_ms"
        ]:
            raise RuntimeError("No completed checkpoint from the active source run")
        save("before-checkpoints.json", before)
        stopped = True
        docker("stop", "--time", "0", container)
        stopped_state = json.loads(docker("inspect", "--format", "{{json .State}}", container))
        print("Flink worker stopped; DDS and Kafka remain running", flush=True)
        time.sleep(args.outage_s)
        start = time.monotonic()
        docker("start", container)
        stopped = False
        restored = False
        observations = []
        while time.monotonic() - start < 60:
            try:
                after = fetch(f"/jobs/{job_id}/checkpoints")
                status = fetch(f"/jobs/{job_id}")
                observations.append(
                    {
                        "elapsed_ms": round((time.monotonic() - start) * 1000),
                        "state": status["state"],
                        "counts": after["counts"],
                        "latest": after["latest"],
                    }
                )
                if restored_checkpoint(before, after) and status["state"] == "RUNNING":
                    restored = True
                    break
            except (OSError, ValueError):
                pass
            time.sleep(0.5)
        elapsed_ms = round((time.monotonic() - start) * 1000)
        save("recovery-observations.json", observations)
        print(
            f"Checkpoint restoration and new checkpoint: {restored} in {elapsed_ms} ms", flush=True
        )
        code = source.wait(timeout=args.duration_s + 100)
        evaluation = json.loads((output / "source/evaluation.json").read_text())
        capture = json.loads((output / "source/kafka.json").read_text())
        active_output_before_checkpoint = any(
            row["value"]["run_id"] == session["run_id"]
            and row["broker_timestamp_ms"] <= before["latest"]["completed"]["trigger_timestamp"]
            and row["value"]["stream_timestamp_ms"] >= session["start_ms"]
            for row in capture["records"]["telemetry.metrics.v1"]
        )
        final = fetch(f"/jobs/{job_id}/checkpoints")
        save("after-checkpoints.json", final)
        checks = {
            "worker_hard_stopped": stopped_state["ExitCode"] == 137
            and not stopped_state["Running"],
            "checkpoint_from_active_run": before["latest"]["completed"]["trigger_timestamp"]
            > session["start_ms"],
            "same_job_restored_and_checkpointed_within_sixty_seconds": restored,
            "source_evaluation_passed": code == 0 and evaluation["passed"],
            "final_checkpoint_progress": restored_checkpoint(before, final),
            "active_run_output_precedes_checkpoint": active_output_before_checkpoint,
        }
        report = {
            "passed": all(checks.values()),
            "checks": checks,
            "job_id": job_id,
            "worker_image_id": image,
            "recovery_ms": elapsed_ms,
            "warmup_s": args.warmup_s,
            "outage_s": args.outage_s,
            "source_evaluation": evaluation,
            "restored_checkpoint": final["latest"].get("restored"),
            "scope": (
                "Local Flink TaskManager hard stop with JobManager, Kafka and API running; "
                "not JobManager disaster recovery"
            ),
        }
        save("evaluation.json", report)
        print(json.dumps(report), flush=True)
        raise SystemExit(0 if report["passed"] else 1)
    finally:
        if stopped:
            docker("start", container)
        if source.poll() is None:
            source.wait(timeout=args.duration_s + 100)
        log.close()


if __name__ == "__main__":
    main()
