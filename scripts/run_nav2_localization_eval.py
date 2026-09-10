"""Launch an owned Nav2 sandbox and collect a controlled localization disturbance."""

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
    parser.add_argument("--domain", type=int, default=73)
    parser.add_argument("--offset-m", type=float, default=1.5)
    parser.add_argument("--with-telemetry", action="store_true")
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    prefix = "localization-eval-" + uuid.uuid4().hex[:10]
    owned = []

    def docker(*command):
        return subprocess.check_output(["docker", *command], text=True, timeout=30).strip()

    image = docker("image", "inspect", "--format", "{{.Id}}", "ros-telemetry-nav2:development")
    (output / "manifest.json").write_text(
        json.dumps(
            {
                "image_id": image,
                "domain": args.domain,
                "offset_m": args.offset_m,
                "with_telemetry": args.with_telemetry,
                "scope": "Owned stationary Gazebo/Nav2 sandbox",
            },
            indent=2,
        )
        + "\n"
    )
    common = [
        "--network",
        "robot-telemetry-flight-deck_default",
        "-e",
        f"ROS_DOMAIN_ID={args.domain}",
        "-v",
        f"{ROOT / 'scripts'}:/tools:ro",
        "-v",
        f"{output}:/results",
    ]
    try:
        simulation, experiment = prefix + "-simulation", prefix + "-experiment"
        docker("run", "-d", "--name", simulation, *common, image)
        owned.append(simulation)
        docker(
            "run",
            "-d",
            "--name",
            experiment,
            *common,
            image,
            "python3",
            "/tools/nav2_localization_fault.py",
            "--output",
            "/results/evaluation.json",
            "--offset-m",
            str(args.offset_m),
            *(
                ["--ready-file", "/results/ready", "--go-file", "/results/go"]
                if args.with_telemetry
                else []
            ),
        )
        owned.append(experiment)
        print("Running controlled localization disturbance in Nav2", flush=True)
        deadline = time.monotonic() + 120
        gateway = None
        if args.with_telemetry:
            while not (output / "ready").exists():
                state = json.loads(docker("inspect", "--format", "{{json .State}}", experiment))
                if not state["Running"] or time.monotonic() > deadline:
                    raise RuntimeError("Simulation did not establish baseline readiness")
                time.sleep(0.5)
            config = yaml.safe_load((ROOT / "configs/gateway_nav2.yaml").read_text())
            config.update(robot_id=prefix, duration_ms=45000)
            (output / "gateway.yaml").write_text(yaml.safe_dump(config))
            gateway_image = docker(
                "image", "inspect", "--format", "{{.Id}}", "ros-telemetry-gateway:development"
            )
            (output / "gateway-image.json").write_text(
                json.dumps({"image_id": gateway_image}) + "\n"
            )
            gateway = prefix + "-gateway"
            docker(
                "run",
                "-d",
                "--name",
                gateway,
                *common,
                gateway_image,
                "python3",
                "-m",
                "demo.gateway.ros_node",
                "--config",
                "/results/gateway.yaml",
                "--outbox",
                "/results/gateway.sqlite",
            )
            owned.append(gateway)
            time.sleep(5)
            (output / "go").touch()
        while True:
            state = json.loads(docker("inspect", "--format", "{{json .State}}", experiment))
            if not state["Running"]:
                break
            if time.monotonic() > deadline:
                raise TimeoutError("Nav2 experiment exceeded its deadline")
            time.sleep(0.5)
        report = json.loads((output / "evaluation.json").read_text())
        if gateway:
            while True:
                gateway_state = json.loads(
                    docker("inspect", "--format", "{{json .State}}", gateway)
                )
                if not gateway_state["Running"]:
                    break
                if time.monotonic() > deadline:
                    raise TimeoutError("Gateway did not finish its bounded session")
                time.sleep(0.5)
            if gateway_state["ExitCode"] != 0:
                raise RuntimeError("Gateway exited unsuccessfully")
            ledger = json.loads(docker("logs", gateway).splitlines()[-1])
            (output / "gateway-ledger.json").write_text(json.dumps(ledger, indent=2) + "\n")
            summary_deadline = time.monotonic() + 60
            while True:
                with urllib.request.urlopen(
                    "http://localhost:8000/api/runs/current/snapshot?run_id=" + ledger["run_id"],
                    timeout=5,
                ) as response:
                    snapshot = json.load(response)
                if snapshot["completion"]["verified"] or time.monotonic() > summary_deadline:
                    break
                time.sleep(0.5)
            (output / "snapshot.json").write_text(json.dumps(snapshot, indent=2) + "\n")
            docker(
                "run",
                "--rm",
                *common,
                gateway_image,
                "python3",
                "/tools/capture_gateway_run.py",
                "--run-id",
                ledger["run_id"],
                "--output",
                "/results/kafka.json",
            )
            checked = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "scripts.evaluate_nav2_telemetry",
                    "--directory",
                    str(output),
                ],
                check=False,
                cwd=ROOT,
            )
            if checked.returncode:
                report["passed"] = False
        print(json.dumps({key: value for key, value in report.items() if key != "samples"}))
        raise SystemExit(0 if state["ExitCode"] == 0 and report["passed"] else 1)
    finally:
        for name in reversed(owned):
            docker("stop", "--time", "5", name)
            (output / f"{name}.log").write_text(docker("logs", name) + "\n")


if __name__ == "__main__":
    main()
