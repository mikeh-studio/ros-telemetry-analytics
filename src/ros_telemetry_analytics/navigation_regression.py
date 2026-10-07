"""Offline, fail-closed scoring of paired navigation experiments.

This consumes evaluator-owned simulator evidence, never AMCL/odometry as truth.
It does not launch ROS or certify the provenance of a supplied JSON document.
"""

from __future__ import annotations

import hashlib
import html
import json
import math
import re
from collections import Counter
from pathlib import Path
from typing import Any

import numpy as np

MAX_INPUT_BYTES = 128 * 1024 * 1024
MAX_SCENARIOS = 10000
MAX_BOOTSTRAP_WORK = 50_000_000

DEFAULT_POLICY = {
    "position_tolerance_m": 0.25,
    "heading_tolerance_rad": 0.25,
    "hold_s": 1.0,
    "timeout_s": 120.0,
    "max_evidence_gap_s": 0.25,
    "success_margin": 0.02,
    "time_ratio_limit": 1.10,
    "min_maps": 20,
    "bootstrap_samples": 5000,
    "bootstrap_seed": 20261006,
}


def _number(value: Any, name: str, *, minimum: float = 0) -> float:
    if isinstance(value, bool) or not isinstance(value, (float, int)):
        raise ValueError(f"{name} must be a finite number")
    try:
        finite = math.isfinite(value)
    except OverflowError:
        finite = False
    if not finite or value < minimum:
        raise ValueError(f"Invalid {name}")
    return float(value)


def _pose(value: Any) -> list[float]:
    if not isinstance(value, list) or len(value) != 3:
        raise ValueError("Pose must contain x, y, yaw")
    return [_number(v, "pose", minimum=-math.inf) for v in value]


def _hash(value: Any) -> str:
    if not isinstance(value, str) or len(value) != 64:
        raise ValueError("Expected SHA-256 digest")
    if any(c not in "0123456789abcdef" for c in value):
        raise ValueError("Expected lowercase SHA-256 digest")
    return value


def _text(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Expected nonempty identifier")
    return value


def _policy(raw: dict) -> dict:
    if not isinstance(raw, dict):
        raise ValueError("Scoring policy must be an object")
    if set(raw) - set(DEFAULT_POLICY):
        raise ValueError("Unknown scoring policy field")
    policy = DEFAULT_POLICY | raw
    for key in policy:
        _number(policy[key], key)
    for key in ("min_maps", "bootstrap_samples", "bootstrap_seed"):
        if type(policy[key]) is not int:
            raise ValueError(f"{key} must be an integer")
    if policy["min_maps"] < 2 or not 100 <= policy["bootstrap_samples"] <= 100000:
        raise ValueError("Insufficient maps or invalid bootstrap size")
    if not 0 < policy["success_margin"] < 1 or policy["time_ratio_limit"] <= 1:
        raise ValueError("Invalid comparison margins")
    for key in (
        "position_tolerance_m",
        "heading_tolerance_rad",
        "hold_s",
        "timeout_s",
        "max_evidence_gap_s",
    ):
        if policy[key] <= 0:
            raise ValueError(f"{key} must be positive")
    if policy["hold_s"] > policy["timeout_s"]:
        raise ValueError("Goal hold cannot exceed timeout")
    if policy["max_evidence_gap_s"] > policy["hold_s"]:
        raise ValueError("Evidence gap cannot exceed goal hold duration")
    return policy


def _coverage(times: list, end: float, gap: float) -> None:
    if not times:
        raise ValueError("Missing continuous scoring evidence")
    values = [_number(t, "evidence timestamp") for t in times]
    if values[0] != 0 or abs(values[-1] - end) > 1e-9:
        raise ValueError("Evidence must cover the entire attempt, including endpoints")
    if any(b <= a or b - a > gap + 1e-9 for a, b in zip(values, values[1:], strict=False)):
        raise ValueError("Evidence contains duplicate, reversed or missing timestamps")


def score_attempt(attempt: dict, scenario: dict, policy: dict) -> dict:
    """Score one normalized attempt; malformed evidence returns INVALID."""
    result = {
        "run_id": attempt.get("run_id"),
        "scenario_id": scenario["scenario_id"],
        "seed": scenario["seed"],
        "configuration": attempt.get("configuration"),
        "outcome": "invalid",
        "success": False,
        "collision": None,
        "completion_s": None,
        "path_length_m": None,
        "reason": None,
    }
    try:
        end = _number(attempt["elapsed_s"], "elapsed_s")
        termination = attempt["termination"]
        if termination not in {"finished", "timeout", "rejected", "crash", "harness_error"}:
            raise ValueError("Unknown termination")
        if termination == "harness_error":
            raise ValueError("Harness failed")
        if termination == "rejected":
            if end != 0:
                raise ValueError("Rejected goals must end before mission execution")
            if any(
                attempt.get(field) not in (None, [])
                for field in ("ground_truth", "contact_heartbeat_s", "obstacle_contacts")
            ):
                raise ValueError("Rejected goals cannot contain execution evidence")
            return result | {"outcome": "rejected", "reason": "Goal rejected before execution"}
        poses = attempt["ground_truth"]
        _coverage([p["t"] for p in poses], end, policy["max_evidence_gap_s"])
        _coverage(attempt["contact_heartbeat_s"], end, policy["max_evidence_gap_s"])
        coordinates = [_pose(p["pose"]) for p in poses]
        start, goal = _pose(scenario["start"]), _pose(scenario["goal"])
        if any(abs(a - b) > 1e-6 for a, b in zip(coordinates[0], start, strict=True)):
            raise ValueError("Ground-truth start differs from frozen scenario")
        contacts = attempt["obstacle_contacts"]
        if not isinstance(contacts, list):
            raise ValueError("Contacts must be an explicit list (empty means observed zero)")
        for event in contacts:
            if _number(event["t"], "contact timestamp") > end:
                raise ValueError("Contact outside attempt")
            _text(event["obstacle"])
        path = sum(
            math.hypot(b[0] - a[0], b[1] - a[1])
            for a, b in zip(coordinates, coordinates[1:], strict=False)
        )
        _number(path, "derived path length")
        result.update(collision=bool(contacts), path_length_m=path)
        held_since = None
        completion = None
        for sample, pose in zip(poses, coordinates, strict=True):
            yaw_error = abs(math.atan2(math.sin(pose[2] - goal[2]), math.cos(pose[2] - goal[2])))
            inside = (
                math.hypot(pose[0] - goal[0], pose[1] - goal[1]) <= policy["position_tolerance_m"]
                and yaw_error <= policy["heading_tolerance_rad"]
            )
            if not inside:
                held_since = None
            elif held_since is None:
                held_since = sample["t"]
            if held_since is not None and sample["t"] - held_since >= policy["hold_s"]:
                completion = sample["t"]
                break
        # Collision anywhere in the captured mission overrides eventual arrival.
        if contacts:
            outcome = "collision"
        elif termination == "crash":
            outcome = "crash"
        elif completion is not None and completion <= policy["timeout_s"]:
            outcome = "success"
            result["completion_s"] = completion
        elif end >= policy["timeout_s"]:
            outcome = "timeout"
        elif termination == "timeout":
            raise ValueError("Timeout recorded before the simulation-time deadline")
        else:
            outcome = "goal_not_verified"
        return result | {"outcome": outcome, "success": outcome == "success"}
    except (KeyError, ValueError, TypeError, IndexError) as error:
        return result | {"outcome": "invalid", "success": False, "reason": str(error)}


def evaluate_suite(document: dict) -> dict:
    """Validate schedule/identities, score attempts, and compare paired map clusters."""
    if not isinstance(document, dict):
        raise ValueError("Suite must be a JSON object")
    if type(document.get("schema_version")) is not int or document["schema_version"] != 1:
        raise ValueError("Unsupported navigation suite schema")
    kind = document["evidence_kind"]
    if kind not in {"synthetic", "simulator"}:
        raise ValueError("Evidence kind must be synthetic or simulator")
    _text(document["suite_id"])
    policy = _policy(document.get("policy", {}))
    configurations = document["configurations"]
    if not isinstance(configurations, dict) or set(configurations) != {"baseline", "candidate"}:
        raise ValueError("Exactly baseline and candidate configurations are required")
    for config in configurations.values():
        if not isinstance(config, dict):
            raise ValueError("Configuration must be an object")
        _hash(config["config_sha256"])
        _text(config["git_revision"])
    runtime = _hash(document["runtime_sha256"])
    if not isinstance(document["scenarios"], list) or not isinstance(document["attempts"], list):
        raise ValueError("Scenarios and attempts must be arrays")
    if not document["scenarios"]:
        raise ValueError("Empty scenario schedule")
    if len(document["scenarios"]) > MAX_SCENARIOS:
        raise ValueError("Scenario schedule exceeds 10000 pairs")
    if len(document["attempts"]) > 2 * len(document["scenarios"]):
        raise ValueError("Duplicate or excess attempts in schedule")
    scenarios = {}
    map_identity = {}
    for scenario in document["scenarios"]:
        if not isinstance(scenario, dict):
            raise ValueError("Scenario must be an object")
        sid = _text(scenario["scenario_id"])
        seed = scenario["seed"]
        if type(seed) is not int or seed < 0:
            raise ValueError("Seed must be a nonnegative integer")
        _pose(scenario["start"])
        _pose(scenario["goal"])
        map_hash = _hash(scenario["map_sha256"])
        _hash(scenario["scenario_sha256"])
        if sid in map_identity and map_identity[sid] != map_hash:
            raise ValueError("A scenario ID cannot refer to different maps")
        map_identity[sid] = map_hash
        key = (sid, seed)
        if key in scenarios:
            raise ValueError("Duplicate scheduled scenario/seed")
        scenarios[key] = scenario
    if not scenarios:
        raise ValueError("Empty scenario schedule")
    if len(set(map_identity.values())) * policy["bootstrap_samples"] > MAX_BOOTSTRAP_WORK:
        raise ValueError("Map count times bootstrap samples exceeds evaluation work limit")
    # A map reused through aliases remains one statistical cluster.
    attempts = {}
    run_ids = set()
    for attempt in document["attempts"]:
        if not isinstance(attempt, dict) or type(attempt.get("seed")) is not int:
            raise ValueError("Attempt must have an integer seed")
        key = (attempt["scenario_id"], attempt["seed"], attempt["configuration"])
        if key[:2] not in scenarios or key[2] not in configurations:
            raise ValueError("Unscheduled attempt")
        rid = _text(attempt["run_id"])
        if rid in run_ids or key in attempts:
            raise ValueError("Duplicate run or attempt; retries need a separate suite")
        run_ids.add(rid)
        config = configurations[key[2]]
        scenario = scenarios[key[:2]]
        if (
            attempt["config_sha256"] != config["config_sha256"]
            or attempt["git_revision"] != config["git_revision"]
            or attempt["runtime_sha256"] != runtime
            or attempt["scenario_sha256"] != scenario["scenario_sha256"]
        ):
            raise ValueError("Attempt provenance differs from frozen manifest")
        attempts[key] = score_attempt(attempt, scenario, policy)
    scored, pairs = [], []
    for key, scenario in scenarios.items():
        pair = {}
        for role in configurations:
            score = attempts.get((*key, role))
            if score is None:
                score = {
                    "run_id": None,
                    "scenario_id": key[0],
                    "seed": key[1],
                    "configuration": role,
                    "outcome": "invalid",
                    "success": False,
                    "collision": None,
                    "completion_s": None,
                    "path_length_m": None,
                    "reason": "Scheduled attempt missing",
                }
            scored.append(score)
            pair[role] = score
        pairs.append(
            {"scenario_id": key[0], "seed": key[1], "map_sha256": scenario["map_sha256"], **pair}
        )
    counts = {
        role: dict(Counter(r["outcome"] for r in scored if r["configuration"] == role))
        for role in configurations
    }
    result = {
        "schema_version": 1,
        "suite_id": document["suite_id"],
        "evidence_kind": kind,
        "status": "INCONCLUSIVE",
        "policy": policy,
        "counts": counts,
        "scheduled_pairs": len(pairs),
        "attempts": scored,
        "pairs": pairs,
        "success_delta": None,
        "time_ratio": None,
        "reasons": [],
        "statistical_scope": "Paired map-cluster bootstrap; descriptive of this frozen "
        "suite, not a bound on unseen or rare failures.",
    }
    if any(r["outcome"] == "invalid" for r in scored):
        return result | {"status": "INVALID", "reasons": ["Incomplete or invalid evidence"]}
    new_collisions = [
        p
        for p in pairs
        if p["candidate"]["collision"] is True and p["baseline"]["collision"] is False
    ]
    result["new_collision_pairs"] = [
        {"scenario_id": p["scenario_id"], "seed": p["seed"]} for p in new_collisions
    ]
    groups = {}
    time_groups = {}
    for pair in pairs:
        b, c = pair["baseline"], pair["candidate"]
        groups.setdefault(pair["map_sha256"], []).append(int(c["success"]) - int(b["success"]))
        if b["success"] and c["success"]:
            time_groups.setdefault(pair["map_sha256"], []).append(
                math.log(c["completion_s"]) - math.log(b["completion_s"])
            )
    result["independent_maps"] = len(groups)
    result["paired_success_maps"] = len(time_groups)
    result["paired_success_attempts"] = sum(map(len, time_groups.values()))
    rng = np.random.default_rng(policy["bootstrap_seed"])

    def interval(group: dict, transform=lambda x: x):
        if not group:
            return None
        values = np.array([np.mean(group[key]) for key in sorted(group)])
        # Bound peak memory even for large map collections.
        draws = np.array(
            [
                rng.choice(values, size=len(values), replace=True).mean()
                for _ in range(policy["bootstrap_samples"])
            ]
        )
        low, high = np.quantile(draws, [0.025, 0.975])
        return {
            "estimate": float(transform(values.mean())),
            "ci95": [float(transform(low)), float(transform(high))],
        }

    result["success_delta"] = interval(groups)
    result["time_ratio"] = interval(time_groups, math.exp)
    if new_collisions:
        return result | {"status": "REGRESSION", "reasons": ["New paired collision observed"]}
    success_low, success_high = result["success_delta"]["ci95"]
    if len(groups) >= policy["min_maps"] and success_high < -policy["success_margin"]:
        return result | {"status": "REGRESSION", "reasons": ["Success loss exceeds frozen margin"]}
    if len(groups) < policy["min_maps"] or len(time_groups) < policy["min_maps"]:
        return result | {"reasons": ["Insufficient independent maps or matched-success maps"]}
    time_low, time_high = result["time_ratio"]["ci95"]
    if success_high < -policy["success_margin"] or time_low > policy["time_ratio_limit"]:
        result.update(status="REGRESSION", reasons=["Comparison exceeds frozen margin"])
    elif success_low > -policy["success_margin"] and time_high < policy["time_ratio_limit"]:
        if kind == "synthetic":
            result["reasons"] = ["Synthetic evidence cannot approve a navigation change"]
        else:
            result.update(status="PASS", reasons=["All observed-suite acceptance gates passed"])
    else:
        result["reasons"] = ["Uncertainty overlaps an acceptance boundary"]
    return result


def _unique_object(pairs: list[tuple[str, Any]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def _markdown_cell(value: Any) -> str:
    # User-controlled IDs and validation reasons must remain inert report text.
    escaped = html.escape(str(value), quote=True)
    escaped = re.sub(r"[\r\n\t]+", " ", escaped)
    return re.sub(r"([\\`*_{}\[\]()!|])", r"\\\1", escaped)


def evaluate_navigation_file(source: Path, output: Path) -> dict:
    """Retain exact input and its digest in a new, non-overwriting artifact directory."""
    with source.open("rb") as stream:
        raw = stream.read(MAX_INPUT_BYTES + 1)
    if len(raw) > MAX_INPUT_BYTES:
        raise ValueError("Navigation input exceeds 128 MiB")
    document = json.loads(
        raw,
        object_pairs_hook=_unique_object,
        parse_constant=lambda value: (_ for _ in ()).throw(
            ValueError(f"Nonfinite JSON constant: {value}")
        ),
    )
    result = evaluate_suite(document)
    result["input_sha256"] = hashlib.sha256(raw).hexdigest()
    output.mkdir(parents=True, exist_ok=False)
    (output / "input.json").write_bytes(raw)
    (output / "evaluation.json").write_text(json.dumps(result, indent=2, allow_nan=False) + "\n")
    lines = [
        "# Navigation regression",
        "",
        f"Decision: **{result['status']}**",
        "",
        f"Evidence: **{result['evidence_kind']}**. Scheduled pairs: {result['scheduled_pairs']}.",
        "",
        *[f"- {r}" for r in result["reasons"]],
        "",
        "| Configuration | Outcome | Attempts |",
        "| --- | --- | ---: |",
    ]
    for role, counts in result["counts"].items():
        lines.extend(f"| {role} | {name} | {count} |" for name, count in sorted(counts.items()))
    lines += [
        "",
        "Success difference uses equally weighted map means. Time ratio is the "
        "geometric mean of paired-success ratios, equally weighted by map.",
        "",
    ]
    for metric in ("success_delta", "time_ratio"):
        lines.append(f"- {metric}: {json.dumps(result[metric])}")
    lines += [
        "",
        result["statistical_scope"],
        "",
        "## Attempts",
        "",
        "| Scenario | Seed | Configuration | Outcome | Reason |",
        "| --- | ---: | --- | --- | --- |",
    ]
    for row in result["attempts"]:
        cells = [
            row["scenario_id"],
            row["seed"],
            row["configuration"],
            row["outcome"],
            row["reason"] or "",
        ]
        lines.append("| " + " | ".join(_markdown_cell(c) for c in cells) + " |")
    (output / "report.md").write_text("\n".join(lines) + "\n")
    return result
