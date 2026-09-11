"""Run the bounded local reliability experiments sequentially and preserve every result."""

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CASES = (
    "silence",
    "qos",
    "duplicate",
    "delay",
    "edge",
    "overflow",
    "fleet",
    "projection_restart",
    "flink_restart",
    "localization",
)


def case_command(name, output, domain):
    args = ["--output", str(output)]
    result = "evaluation.json"
    if name in {"silence", "qos", "duplicate", "delay"}:
        script = "run_gateway_eval.py"
        args += ["--fault", name, "--domain", str(domain)]
        if name != "silence":
            args += ["--duration-s", "50", "--dropout-start-s", "16", "--dropout-end-s", "24"]
    elif name in {"edge", "overflow"}:
        script = "run_edge_recovery_eval.py"
        args += ["--duration-s", "55", "--warmup-s", "10", "--outage-s", "15"]
        if name == "overflow":
            args += ["--max-pending-records", "96", "--expect-overflow"]
    elif name == "fleet":
        script = "run_fleet_isolation_eval.py"
        args += [
            "--duration-s",
            "65",
            "--warmup-s",
            "16",
            "--outage-s",
            "17",
            "--domain-base",
            str(domain),
        ]
    elif name == "projection_restart":
        script = "run_projection_restart_eval.py"
        args += [
            "--duration-s",
            "70",
            "--warmup-s",
            "16",
            "--outage-s",
            "18",
            "--domain",
            str(domain),
        ]
    elif name == "flink_restart":
        script = "run_flink_restart_eval.py"
        args += [
            "--duration-s",
            "110",
            "--warmup-s",
            "22",
            "--outage-s",
            "14",
            "--domain",
            str(domain),
        ]
    elif name == "localization":
        script = "run_nav2_localization_eval.py"
        args += ["--offset-m", "2.0", "--with-telemetry", "--domain", str(domain)]
        result = "telemetry-evaluation.json"
    else:
        raise ValueError(f"Unknown case: {name}")
    return [sys.executable, str(ROOT / "scripts" / script), *args], result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cases", choices=CASES, nargs="+", default=list(CASES))
    parser.add_argument("--domain-base", type=int, default=80)
    parser.add_argument("--keep-going", action="store_true")
    args = parser.parse_args()
    if not 0 <= args.domain_base <= 200 or len(set(args.cases)) != len(args.cases):
        parser.error("Use a domain base from 0 to 200 and distinct case names")
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    report = {
        "passed": False,
        "requested_cases": args.cases,
        "results": {},
        "scope": (
            "Local runtime fault suite; localization is a post-run diagnostic; "
            "browser review is separate"
        ),
    }
    for index, name in enumerate(args.cases):
        command, filename = case_command(name, output / name, args.domain_base + index * 3)
        print(f"Starting {name}", flush=True)
        started = time.monotonic()
        with (output / f"{name}.log").open("w") as log:
            code = subprocess.run(
                command, stdout=log, stderr=subprocess.STDOUT, cwd=ROOT
            ).returncode
        path = output / name / filename
        try:
            evidence = json.loads(path.read_text())
        except (OSError, ValueError):
            evidence = {
                "passed": False,
                "error": "Expected evaluation evidence is missing or invalid",
            }
        passed = code == 0 and evidence.get("passed") is True
        report["results"][name] = {
            "passed": passed,
            "exit_code": code,
            "elapsed_s": round(time.monotonic() - started, 3),
            "evidence_path": str(path.relative_to(output)),
            "evaluation": evidence,
        }
        report["passed"] = len(report["results"]) == len(args.cases) and all(
            row["passed"] for row in report["results"].values()
        )
        (output / "evaluation.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
        print(f"{name}: {'passed' if passed else 'failed'}", flush=True)
        if not passed and not args.keep_going:
            break
    raise SystemExit(0 if report["passed"] else 1)


if __name__ == "__main__":
    main()
