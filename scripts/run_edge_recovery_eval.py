"""Isolate a ROS gateway from Kafka, crash it, then reconcile its durable backlog."""

from __future__ import annotations

import argparse
import json
import sqlite3
import subprocess
import time
import urllib.request
import uuid
from collections import Counter
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def side_output_counts(rows):
    """The late topic also contains sequence diagnostics, which are not rejected events."""
    counts = Counter(row["value"]["reason"] for row in rows)
    known = {
        "sequence_gap",
        "sequence_regression",
        "duplicate",
        "beyond_allowed_lateness",
        "unregistered_topic",
        "run_not_running",
    }
    if set(counts) - known:
        raise ValueError(f"Unclassified side-output reasons: {set(counts) - known}")
    return dict(counts)


def read_spool(path):
    with sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=10) as connection:
        connection.row_factory = sqlite3.Row
        connection.execute("BEGIN")
        state = dict(connection.execute("SELECT * FROM state WHERE id=1").fetchone())
        state["session"] = json.loads(state["session"])
        state["queued"] = [
            json.loads(row[0])
            for row in connection.execute("SELECT payload FROM outbox ORDER BY id")
        ]
        return state


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--image", default="ros-telemetry-gateway:development")
    parser.add_argument("--network", default="robot-telemetry-flight-deck_default")
    parser.add_argument("--api", default="http://localhost:8000")
    parser.add_argument("--max-pending-records", type=int, default=10000)
    parser.add_argument("--expect-overflow", action="store_true")
    parser.add_argument("--outage-s", type=int, default=12)
    parser.add_argument("--warmup-s", type=int, default=0)
    parser.add_argument("--duration-s", type=int, default=45)
    args = parser.parse_args()
    if not 5 <= args.outage_s <= args.duration_s - args.warmup_s - 15:
        parser.error("Leave at least 15 seconds for delivery after the outage")
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)

    def docker(*parts, timeout=60):
        return subprocess.check_output(
            ["docker", *parts],
            text=True,
            timeout=timeout,
            stderr=subprocess.STDOUT if parts[0] == "logs" else None,
        ).strip()

    def save(name, value):
        (output / name).write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")

    prefix = "edge-eval-" + uuid.uuid4().hex[:10]
    isolated = prefix + "-dds"
    gateway = prefix + "-gateway"
    publisher = prefix + "-publisher"
    image_id = docker("image", "inspect", "--format", "{{.Id}}", args.image)
    config = yaml.safe_load((ROOT / "configs/gateway.yaml").read_text())
    config.update(robot_id=prefix, duration_ms=args.duration_s * 1000)
    (output / "config.yaml").write_text(yaml.safe_dump(config))
    common = [
        "--network",
        isolated,
        "-e",
        "ROS_DOMAIN_ID=46",
        "-v",
        f"{output}:/validation",
        "-v",
        f"{ROOT / 'scripts'}:/tools:ro",
    ]
    owned = []
    docker("network", "create", isolated)
    try:
        docker(
            "run",
            "-d",
            "--name",
            gateway,
            *common,
            image_id,
            "python3",
            "-m",
            "demo.gateway.ros_node",
            "--config",
            "/validation/config.yaml",
            "--outbox",
            "/validation/gateway.sqlite",
            "--max-pending-records",
            str(args.max_pending_records),
        )
        owned.append(gateway)
        if args.warmup_s:
            docker("network", "connect", args.network, gateway)
        docker(
            "run",
            "-d",
            "--name",
            publisher,
            *common,
            image_id,
            "python3",
            "/tools/ros_gateway_fixture.py",
            "--duration-s",
            str(args.duration_s),
            "--dropout-start-s",
            "0",
            "--dropout-end-s",
            "0",
            "--output",
            "/validation/fixture.json",
        )
        owned.append(publisher)
        warmup = None
        if args.warmup_s:
            time.sleep(args.warmup_s)
            warmup = read_spool(output / "gateway.sqlite")
            save("warmup.json", warmup)
            docker("network", "disconnect", args.network, gateway)
        print("Kafka unreachable; DDS remains connected on the isolated network", flush=True)
        time.sleep(2)
        outage_baseline = read_spool(output / "gateway.sqlite")
        save("outage-baseline.json", outage_baseline)
        time.sleep(args.outage_s - 2)
        before = read_spool(output / "gateway.sqlite")
        save("before-crash.json", before)
        crashed_ms = time.time_ns() // 1_000_000
        docker("kill", "--signal", "KILL", gateway)
        state = json.loads(docker("inspect", "--format", "{{json .State}}", gateway))
        if state["Running"] or state["ExitCode"] != 137:
            raise RuntimeError("Abrupt termination was not verified")
        after = read_spool(output / "gateway.sqlite")
        save("after-crash.json", after)
        docker("network", "connect", args.network, gateway)
        docker("start", gateway)
        resumed_ms = time.time_ns() // 1_000_000
        print("Restarted the same durable session with Kafka connectivity", flush=True)
        deadline = time.monotonic() + args.duration_s + 50
        for name in owned:
            while True:
                state = json.loads(docker("inspect", "--format", "{{json .State}}", name))
                if not state["Running"]:
                    (output / f"{name}.log").write_text(docker("logs", name) + "\n")
                    if state["ExitCode"]:
                        raise RuntimeError(f"{name} exited {state['ExitCode']}")
                    break
                if time.monotonic() > deadline:
                    raise TimeoutError("Recovery experiment exceeded the deadline")
                time.sleep(0.5)
        final = read_spool(output / "gateway.sqlite")
        save("final-spool.json", final)
        run_id = final["session"]["run_id"]
        deadline = time.monotonic() + 60
        while True:
            with urllib.request.urlopen(
                args.api + f"/api/runs/current/snapshot?run_id={run_id}", timeout=5
            ) as response:
                snapshot = json.load(response)
            if snapshot["completion"]["verified"] or time.monotonic() > deadline:
                break
            time.sleep(1)
        save("snapshot.json", snapshot)
        docker(
            "run",
            "--rm",
            "--network",
            args.network,
            "-v",
            f"{output}:/validation",
            "-v",
            f"{ROOT / 'scripts'}:/tools:ro",
            image_id,
            "python3",
            "/tools/capture_gateway_run.py",
            "--run-id",
            run_id,
            "--output",
            "/validation/kafka.json",
        )
        capture = json.loads((output / "kafka.json").read_text())["records"]
        dispositions = side_output_counts(capture["telemetry.late.v1"])
        transitions = [r["value"] for r in capture["telemetry.anomalies.v1"]]
        offline = [r for r in transitions if r["condition_type"] == "ROBOT_OFFLINE"]
        offline_open = [r for r in offline if r["status"] == "active"]
        offline_recovered = [r for r in offline if r["status"] == "recovered"]
        opened_at = {
            r["anomaly_id"]: r["detected_stream_ms"] for r in transitions if r["status"] == "active"
        }
        rejected_by_stream = sum(
            dispositions.get(reason, 0)
            for reason in ("beyond_allowed_lateness", "unregistered_topic", "run_not_running")
        )
        events = [r["value"] for r in capture["telemetry.events.v1"]]
        captured_by_id = {r["envelope_id"]: r for r in events}
        ids = {r["envelope_id"] for r in events}
        telemetry = [r for r in events if r["envelope_type"] == "telemetry"]
        unique = {r["envelope_id"] for r in telemetry}
        sequences = {r["body"]["sequence"] for r in telemetry}
        queued_ids = {r["envelope_id"] for r in after["queued"]}
        summaries = sum(
            r["payload"]["message_count"] for r in snapshot["mission_summaries"].values()
        )
        source = json.loads((output / "fixture.json").read_text())["records"]
        published_keys = {(r["topic"], r["source_timestamp_ns"]) for r in source}
        observed_keys = {
            (r["topic"], r["body"]["attributes"]["ros_timestamp_ns"])
            for r in telemetry
            if r["body"]["attributes"].get("ros_timestamp_ns") is not None
        }
        checks = {
            "recovery_timestamps_do_not_precede_detection": all(
                r["detected_stream_ms"] >= opened_at.get(r["anomaly_id"], 0)
                for r in transitions
                if r["status"] == "recovered"
            ),
            "projection_has_no_active_incidents": not any(
                r["status"] == "active" for r in snapshot["anomalies"]
            ),
            "all_incidents_recovered": {
                r["anomaly_id"] for r in transitions if r["status"] == "active"
            }
            <= {r["anomaly_id"] for r in transitions if r["status"] == "recovered"},
            "observations_buffered_without_broker": sum(
                r["envelope_type"] == "telemetry" and not r["topic"].startswith("/_telemetry/")
                for r in before["queued"]
            )
            > 20
            and before["acknowledged"] == outage_baseline["acknowledged"],
            "healthy_delivery_before_disconnection": warmup is None or warmup["acknowledged"] > 20,
            "outage_detection_and_recovery": (
                warmup is None
                or args.outage_s < 12
                or (
                    len(offline_open) == len(offline_recovered) == 1
                    and offline_open[0]["anomaly_id"] == offline_recovered[0]["anomaly_id"]
                )
            ),
            "crash_preserved_all_queued_ids": {r["envelope_id"] for r in before["queued"]}
            <= queued_ids,
            "same_run_identity": before["session"]["run_id"] == run_id,
            "all_crash_backlog_delivered": queued_ids <= ids,
            "persisted_envelopes_unchanged": all(
                captured_by_id.get(r["envelope_id"]) == r for r in after["queued"]
            ),
            "overflow_matches_expectation": (final["rejected"] > 0) == args.expect_overflow,
            "queue_within_record_limit": before["pending_records"] <= args.max_pending_records + 32,
            "all_accepted_observations_delivered": len(unique)
            == final["received"] - final["rejected"],
            "ledger_balanced": final["received"] == final["acknowledged"] + final["rejected"],
            "sequence_gaps_match_rejections": (
                len(sequences) == len(unique)
                and all(0 <= sequence < final["next_sequence"] for sequence in sequences)
                and final["next_sequence"] - len(sequences) == final["rejected"]
            ),
            "outbox_drained": final["pending_records"] == 0,
            "schema_valid": not capture["telemetry.dead-letter.v1"],
            "received_source_records_have_provenance": observed_keys <= published_keys,
            "summaries_verified": snapshot["completion"]["verified"],
            "analytical_reconciliation": summaries + rejected_by_stream == len(unique),
            "registration_and_lifecycle_valid": not any(
                dispositions.get(reason, 0) for reason in ("unregistered_topic", "run_not_running")
            ),
        }
        report = {
            "run_id": run_id,
            "image_id": image_id,
            "checks": checks,
            "passed": all(checks.values()),
            "outage_s": args.outage_s,
            "warmup_s": args.warmup_s,
            "max_pending_records": args.max_pending_records,
            "crash_wall_ms": crashed_ms,
            "restart_wall_ms": resumed_ms,
            "received": final["received"],
            "rejected": final["rejected"],
            "acknowledged": final["acknowledged"],
            "pre_crash_pending": len(queued_ids),
            "duplicate_deliveries": len(telemetry) - len(unique),
            "summary_messages": summaries,
            "late_records": dispositions.get("beyond_allowed_lateness", 0),
            "side_output_counts": dispositions,
            "incident_transitions": [
                {
                    k: r.get(k)
                    for k in (
                        "condition_type",
                        "topic",
                        "status",
                        "detected_stream_ms",
                        "anomaly_id",
                    )
                }
                for r in transitions
            ],
            "source_publications": len(source),
            "matched_source_publications": len(observed_keys & published_keys),
            "unobserved_source_publications": len(published_keys - observed_keys),
            "boundary": (
                "Restart downtime and pre-discovery publications are not durably received; "
                "broker delivery may become late evidence. Unobserved publications also include "
                "overflow and the session boundary; aggregate counters do not assign "
                "per-message causes."
            ),
        }
        save("evaluation.json", report)
        print(json.dumps(report, sort_keys=True), flush=True)
        raise SystemExit(0 if report["passed"] else 1)
    finally:
        for name in owned:
            docker("stop", "--timeout", "10", name, timeout=20)
            docker("network", "disconnect", isolated, name)
        docker("network", "rm", isolated)


if __name__ == "__main__":
    main()
