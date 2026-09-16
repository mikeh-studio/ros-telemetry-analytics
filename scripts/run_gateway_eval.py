"""Run a real DDS silence or QoS-repair experiment against a healthy local stack."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
import urllib.request
import uuid
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--image", default="ros-telemetry-gateway:development")
    parser.add_argument("--network", default="robot-telemetry-flight-deck_default")
    parser.add_argument("--api", default="http://localhost:8000")
    parser.add_argument("--domain", type=int, default=45)
    parser.add_argument(
        "--fault", choices=["clean", "silence", "qos", "duplicate", "delay"], default="silence"
    )
    parser.add_argument("--duration-s", type=int, default=45)
    parser.add_argument("--dropout-start-s", type=int, default=12)
    parser.add_argument("--dropout-end-s", type=int, default=19)
    args = parser.parse_args()
    if not 6 <= args.dropout_start_s < args.dropout_end_s < args.duration_s - 12:
        parser.error("Fault must follow startup grace and leave 12 seconds for recovery")
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)

    def docker(*command, timeout=60):
        return subprocess.check_output(["docker", *command], text=True, timeout=timeout).strip()

    def fetch(path):
        with urllib.request.urlopen(args.api + path, timeout=5) as response:
            return json.load(response)

    health = fetch("/api/health")
    if health["status"] != "ready":
        raise RuntimeError("Start the local Kafka/Flink/API stack before evaluation")
    prefix = "gateway-eval-" + uuid.uuid4().hex[:10]
    gateway_name, publisher_name = prefix + "-gateway", prefix + "-publisher"
    config = yaml.safe_load((ROOT / "configs/gateway.yaml").read_text())
    config.update(robot_id=prefix, duration_ms=args.duration_s * 1000)
    if args.fault == "qos":
        next(topic for topic in config["topics"] if topic["topic"] == "/scan")["reliability"] = (
            "reliable"
        )
    (output / "config.yaml").write_text(yaml.safe_dump(config))
    image_id = docker("image", "inspect", "--format", "{{.Id}}", args.image)
    (output / "manifest.json").write_text(
        json.dumps(
            {
                "image_id": image_id,
                "domain": args.domain,
                "health": health,
                "fault_start_s": (
                    None
                    if args.fault == "clean"
                    else 0
                    if args.fault == "qos"
                    else args.dropout_start_s
                ),
                "fault_end_s": None
                if args.fault in {"clean", "duplicate", "delay"}
                else args.dropout_end_s,
                "transport_injection_count": 10 if args.fault in {"duplicate", "delay"} else 0,
                "transport_delay_s": 10 if args.fault == "delay" else 0,
                "duration_s": args.duration_s,
                "scope": "DDS transport fixture",
                "fault": args.fault,
            },
            indent=2,
        )
        + "\n"
    )
    common = [
        "--network",
        args.network,
        "-e",
        f"ROS_DOMAIN_ID={args.domain}",
        "-e",
        f"STREAM_FAULT={args.fault}",
        "-e",
        f"STREAM_FAULT_START_S={args.dropout_start_s}",
        "-e",
        "PYTHONPATH=/app",
        "-v",
        f"{output}:/validation",
        "-v",
        f"{ROOT / 'scripts'}:/tools:ro",
    ]
    owned = []
    try:
        docker(
            "run",
            "-d",
            "--name",
            gateway_name,
            *common,
            image_id,
            "python3",
            *(
                ["/tools/gateway_fault_transport.py"]
                if args.fault in {"duplicate", "delay"}
                else ["-m", "demo.gateway.ros_node"]
            ),
            "--config",
            "/validation/config.yaml",
            "--outbox",
            "/validation/gateway.sqlite",
        )
        owned.append(gateway_name)
        docker(
            "run",
            "-d",
            "--name",
            publisher_name,
            *common,
            image_id,
            "python3",
            "/tools/ros_gateway_fixture.py",
            "--fault",
            args.fault,
            "--duration-s",
            str(args.duration_s),
            "--dropout-start-s",
            str(args.dropout_start_s),
            "--dropout-end-s",
            str(args.dropout_end_s),
            "--output",
            "/validation/fixture.json",
        )
        owned.append(publisher_name)
        print("Running independently timed DDS fault experiment", flush=True)
        deadline = time.monotonic() + args.duration_s + 60
        for name in owned:
            while True:
                state = json.loads(docker("inspect", "--format", "{{json .State}}", name))
                if not state["Running"]:
                    log = docker("logs", name)
                    (output / f"{name}.log").write_text(log + "\n")
                    if state["ExitCode"] != 0:
                        raise RuntimeError(f"{name} failed with exit {state['ExitCode']}")
                    break
                if time.monotonic() >= deadline:
                    raise TimeoutError("Evaluation containers exceeded their deadline")
                time.sleep(0.5)
        ledger = json.loads(docker("logs", gateway_name).splitlines()[-1])
        (output / "gateway-ledger.json").write_text(json.dumps(ledger, indent=2) + "\n")
        run_id = ledger["run_id"]
        deadline = time.monotonic() + 60
        while True:
            snapshot = fetch(f"/api/runs/current/snapshot?run_id={run_id}")
            if snapshot["completion"]["verified"] or time.monotonic() >= deadline:
                break
            time.sleep(1)
        (output / "snapshot.json").write_text(json.dumps(snapshot, indent=2) + "\n")
        print(
            docker(
                "run",
                "--rm",
                *common,
                image_id,
                "python3",
                "/tools/capture_gateway_run.py",
                "--run-id",
                run_id,
                "--output",
                "/validation/kafka.json",
            ),
            flush=True,
        )
        result = subprocess.run(
            [
                sys.executable,
                str(
                    ROOT
                    / (
                        "scripts/evaluate_transport_fault.py"
                        if args.fault in {"duplicate", "delay"}
                        else "scripts/evaluate_gateway_run.py"
                    )
                ),
                "--capture",
                str(output / "kafka.json"),
                "--fixture",
                str(output / "fixture.json"),
                "--snapshot",
                str(output / "snapshot.json"),
                "--output",
                str(output / "evaluation.json"),
                *(
                    ["--injections", str(output / "injections.json")]
                    if args.fault in {"duplicate", "delay"}
                    else []
                ),
            ]
        )
        raise SystemExit(result.returncode)
    finally:
        for name in owned:
            docker("stop", "--timeout", "10", name, timeout=20)


if __name__ == "__main__":
    main()
