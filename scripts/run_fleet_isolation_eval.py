"""Run three concurrent DDS robots with one gateway outage and hard restart."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def isolation_checks(cases):
    run_ids = [case["snapshot"]["run_id"] for case in cases.values()]
    robot_ids = [case["snapshot"]["robot_id"] for case in cases.values()]
    intervals = []
    identities_valid = True
    for case in cases.values():
        snapshot, capture = case["snapshot"], case["capture"]
        events = [row["value"] for row in capture["records"]["telemetry.events.v1"]]
        intervals.append(
            (
                min(
                    row["stream_timestamp_ms"]
                    for row in events
                    if row["envelope_type"] == "run_started"
                ),
                min(
                    row["stream_timestamp_ms"]
                    for row in events
                    if row["envelope_type"] == "run_ended"
                ),
            )
        )
        for topic in ("telemetry.events.v1", "telemetry.metrics.v1", "telemetry.anomalies.v1"):
            identities_valid &= all(
                row["value"]["run_id"] == snapshot["run_id"]
                and row["value"]["robot_id"] == snapshot["robot_id"]
                for row in capture["records"][topic]
            )
        for group in (
            snapshot["topics"],
            snapshot["anomalies"],
            snapshot.get("observed_signals", []),
            snapshot.get("incident_history", []),
            list(snapshot["mission_summaries"].values()),
            [snapshot[key] for key in ("run", "robot_health") if snapshot.get(key)],
        ):
            identities_valid &= all(
                row["run_id"] == snapshot["run_id"] and row["robot_id"] == snapshot["robot_id"]
                for row in group
            )
    overlap_start, overlap_end = (
        max(start for start, _ in intervals),
        min(end for _, end in intervals),
    )
    fault = cases["fault"]["evaluation"]
    checks = {
        "three_distinct_runs": len(set(run_ids)) == len(cases) == 3,
        "three_distinct_robots": len(set(robot_ids)) == len(cases) == 3,
        "all_case_evaluations_pass": all(case["evaluation"]["passed"] for case in cases.values()),
        "identities_isolated": identities_valid,
        "concurrent_for_thirty_seconds": overlap_end - overlap_start >= 30000,
        "restart_during_shared_interval": overlap_start
        < fault["crash_wall_ms"]
        < fault["restart_wall_ms"]
        < overlap_end,
        "all_runs_still_retained_and_verified": all(
            case["snapshot"]["completion"]["verified"] for case in cases.values()
        ),
        "controls_have_no_incidents": all(
            not cases[name]["capture"]["records"]["telemetry.anomalies.v1"]
            and not cases[name]["snapshot"]["anomalies"]
            and not cases[name]["snapshot"].get("incident_history", [])
            for name in ("control_a", "control_b")
        ),
        "fault_has_detected_and_recovered_incident": any(
            row["status"] == "active" for row in fault["incident_transitions"]
        )
        and any(row["status"] == "recovered" for row in fault["incident_transitions"]),
    }
    return {
        "passed": all(checks.values()),
        "checks": checks,
        "overlap_ms": overlap_end - overlap_start,
        "runs": {
            name: {
                "run_id": case["snapshot"]["run_id"],
                "robot_id": case["snapshot"]["robot_id"],
                "summary_messages": sum(
                    row["payload"]["message_count"]
                    for row in case["snapshot"]["mission_summaries"].values()
                ),
            }
            for name, case in cases.items()
        },
        "scope": (
            "Three DDS fixture robots on one local Kafka/Flink/API stack; "
            "one gateway outage/restart, not production fleet capacity"
        ),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--duration-s", type=int, default=60)
    parser.add_argument("--warmup-s", type=int, default=12)
    parser.add_argument("--outage-s", type=int, default=15)
    parser.add_argument("--domain-base", type=int, default=60)
    parser.add_argument("--api", default="http://localhost:8000")
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    commands = {}
    for index, name in enumerate(("control_a", "control_b")):
        commands[name] = [
            sys.executable,
            str(ROOT / "scripts/run_gateway_eval.py"),
            "--output",
            str(output / name),
            "--fault",
            "clean",
            "--domain",
            str(args.domain_base + index),
            "--duration-s",
            str(args.duration_s),
            "--api",
            args.api,
        ]
    commands["fault"] = [
        sys.executable,
        str(ROOT / "scripts/run_edge_recovery_eval.py"),
        "--output",
        str(output / "fault"),
        "--duration-s",
        str(args.duration_s),
        "--warmup-s",
        str(args.warmup_s),
        "--outage-s",
        str(args.outage_s),
        "--api",
        args.api,
    ]

    def run(name):
        with (output / f"{name}.log").open("w") as log:
            return subprocess.run(commands[name], stdout=log, stderr=subprocess.STDOUT).returncode

    codes = {}
    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = {pool.submit(run, name): name for name in commands}
        for future in as_completed(futures):
            name = futures[future]
            codes[name] = future.result()
            print(f"{name} finished with exit {codes[name]}", flush=True)
    cases = {}
    for name in commands:
        folder = output / name
        if not (folder / "evaluation.json").exists():
            continue
        evaluation = json.loads((folder / "evaluation.json").read_text())
        with urllib.request.urlopen(
            args.api + "/api/runs/current/snapshot?run_id=" + evaluation["run_id"], timeout=10
        ) as response:
            snapshot = json.load(response)
        (folder / "retained-snapshot.json").write_text(json.dumps(snapshot, indent=2) + "\n")
        cases[name] = {
            "evaluation": evaluation,
            "snapshot": snapshot,
            "capture": json.loads((folder / "kafka.json").read_text()),
        }
    report = (
        isolation_checks(cases)
        if len(cases) == 3
        else {"passed": False, "checks": {"all_evidence_present": False}}
    )
    report["process_exit_codes"] = codes
    report["passed"] &= all(code == 0 for code in codes.values())
    (output / "evaluation.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps(report), flush=True)
    raise SystemExit(0 if report["passed"] else 1)


if __name__ == "__main__":
    main()
