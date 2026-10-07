from __future__ import annotations

import copy
import hashlib
import json
import math

import pytest

from ros_telemetry_analytics.cli import main
from ros_telemetry_analytics.navigation_regression import (
    DEFAULT_POLICY,
    evaluate_navigation_file,
    evaluate_suite,
    score_attempt,
)


def digest(value):
    return hashlib.sha256(str(value).encode()).hexdigest()


def suite(maps=2, seeds=1, kind="synthetic"):
    document = {
        "schema_version": 1,
        "suite_id": "test-suite",
        "evidence_kind": kind,
        "runtime_sha256": digest("runtime"),
        "configurations": {
            role: {"config_sha256": digest(role), "git_revision": "test-revision"}
            for role in ("baseline", "candidate")
        },
        "policy": {"min_maps": 2, "bootstrap_samples": 100},
        "scenarios": [],
        "attempts": [],
    }
    for map_id in range(maps):
        for seed in range(seeds):
            scenario = {
                "scenario_id": f"map-{map_id}",
                "seed": seed,
                "map_sha256": digest(map_id),
                "scenario_sha256": digest((map_id, seed)),
                "start": [0, 0, 0],
                "goal": [1, 0, 0],
            }
            document["scenarios"].append(scenario)
            for role, config in document["configurations"].items():
                document["attempts"].append(
                    {
                        "run_id": f"{map_id}-{seed}-{role}",
                        "scenario_id": scenario["scenario_id"],
                        "seed": seed,
                        "configuration": role,
                        **config,
                        "runtime_sha256": document["runtime_sha256"],
                        "scenario_sha256": scenario["scenario_sha256"],
                        "elapsed_s": 3,
                        "termination": "finished",
                        "ground_truth": [
                            {"t": i / 4, "pose": [min(i / 8, 1), 0, 0]} for i in range(13)
                        ],
                        "contact_heartbeat_s": [i / 4 for i in range(13)],
                        "obstacle_contacts": [],
                    }
                )
    return document


def score(document):
    return score_attempt(
        document["attempts"][0], document["scenarios"][0], DEFAULT_POLICY | document["policy"]
    )


def test_independent_goal_hold_and_path_length():
    result = score(suite())
    assert result["outcome"] == "success"
    assert result["completion_s"] == 2.5
    assert result["path_length_m"] == 1


def test_contact_after_arrival_still_fails():
    data = suite()
    data["attempts"][0]["obstacle_contacts"] = [{"t": 2.75, "obstacle": "wall"}]
    assert score(data)["outcome"] == "collision"


@pytest.mark.parametrize("field", ["ground_truth", "contact_heartbeat_s", "obstacle_contacts"])
def test_missing_evidence_is_not_zero(field):
    data = suite()
    del data["attempts"][0][field]
    assert score(data)["outcome"] == "invalid"


@pytest.mark.parametrize("times", [[0, 0.25], [0, 0, 3], [0, 3], [0.25, 3], [0, float("nan")]])
def test_incomplete_or_invalid_monitor(times):
    data = suite()
    data["attempts"][0]["contact_heartbeat_s"] = times
    assert score(data)["outcome"] == "invalid"


def test_brief_goal_visit_does_not_count():
    data = suite()
    data["attempts"][0]["ground_truth"][8]["pose"] = [0, 0, 0]
    assert score(data)["outcome"] == "goal_not_verified"


def test_wrong_heading_and_wrapped_heading():
    data = suite()
    data["scenarios"][0]["goal"][2] = math.pi
    assert score(data)["outcome"] == "goal_not_verified"
    for sample in data["attempts"][0]["ground_truth"][1:]:
        sample["pose"][2] = -math.pi
    assert score(data)["outcome"] == "success"


def test_false_action_success_not_trusted():
    data = suite()
    for sample in data["attempts"][0]["ground_truth"]:
        sample["pose"] = [0, 0, 0]
    assert score(data)["outcome"] == "goal_not_verified"
    data["policy"]["timeout_s"] = 3
    assert score(data)["outcome"] == "timeout"


def test_premature_timeout_is_invalid():
    data = suite()
    data["attempts"][0]["termination"] = "timeout"
    for sample in data["attempts"][0]["ground_truth"]:
        sample["pose"] = [0, 0, 0]
    assert score(data)["outcome"] == "invalid"


def test_crash_and_rejected_goal_are_failures():
    data = suite()
    data["attempts"][0]["termination"] = "crash"
    assert score(data)["outcome"] == "crash"
    data["attempts"][0].update(
        termination="rejected",
        elapsed_s=0,
        ground_truth=[],
        contact_heartbeat_s=[],
        obstacle_contacts=[],
    )
    assert score(data)["outcome"] == "rejected"


def test_wrong_start_and_nonfinite_pose_are_invalid():
    data = suite()
    data["attempts"][0]["ground_truth"][0]["pose"][0] = 1
    assert score(data)["outcome"] == "invalid"
    data["attempts"][0]["ground_truth"][0]["pose"][0] = float("inf")
    assert score(data)["outcome"] == "invalid"


def test_missing_scheduled_attempt_invalidates_whole_comparison():
    data = suite()
    data["attempts"].pop()
    result = evaluate_suite(data)
    assert result["status"] == "INVALID"
    assert result["counts"]["candidate"]["invalid"] == 1
    assert len(result["attempts"]) == 4


def test_duplicate_and_unpaired_inputs_rejected():
    data = suite()
    data["attempts"].append(copy.deepcopy(data["attempts"][0]))
    with pytest.raises(ValueError, match="Duplicate"):
        evaluate_suite(data)
    data = suite()
    data["attempts"][0]["scenario_id"] = "unknown"
    with pytest.raises(ValueError, match="Unscheduled"):
        evaluate_suite(data)


@pytest.mark.parametrize(
    "field", ["config_sha256", "runtime_sha256", "scenario_sha256", "git_revision"]
)
def test_provenance_mismatch_rejected(field):
    data = suite()
    data["attempts"][0][field] = digest("other")
    with pytest.raises(ValueError, match="provenance"):
        evaluate_suite(data)


def test_new_collision_regression_even_in_small_pilot():
    data = suite(maps=1)
    data["attempts"][1]["obstacle_contacts"] = [{"t": 1, "obstacle": "wall"}]
    result = evaluate_suite(data)
    assert result["status"] == "REGRESSION"
    assert result["new_collision_pairs"] == [{"scenario_id": "map-0", "seed": 0}]


@pytest.mark.parametrize("maps", [1, 26])
def test_candidate_collision_after_baseline_rejection_is_regression(maps):
    data = suite(maps=maps, kind="simulator")
    data["policy"]["min_maps"] = 20
    data["attempts"][0].update(
        termination="rejected",
        elapsed_s=0,
        ground_truth=[],
        contact_heartbeat_s=[],
        obstacle_contacts=[],
    )
    data["attempts"][1]["obstacle_contacts"] = [{"t": 1, "obstacle": "wall"}]
    result = evaluate_suite(data)
    assert result["status"] == "REGRESSION"
    assert result["new_collision_pairs"] == [{"scenario_id": "map-0", "seed": 0}]
    assert result["success_delta"]["estimate"] == 0


def test_collisions_in_both_configurations_are_not_new_collisions():
    data = suite(maps=1)
    for attempt in data["attempts"]:
        attempt["obstacle_contacts"] = [{"t": 1, "obstacle": "wall"}]
    result = evaluate_suite(data)
    assert result["new_collision_pairs"] == []
    assert result["status"] == "INCONCLUSIVE"


@pytest.mark.parametrize(
    "scope,field,context",
    [
        ("suite", "evidence_kind", "Suite"),
        ("configuration", "config_sha256", "Configuration baseline"),
        ("scenario", "scenario_id", "Scenario[0]"),
        ("attempt", "scenario_id", "Attempt[0] run_id='0-0-baseline'"),
        ("attempt", "config_sha256", "Attempt[0] run_id='0-0-baseline'"),
        ("attempt", "run_id", "Attempt[0]"),
    ],
)
def test_missing_manifest_fields_name_record_and_field(tmp_path, caplog, scope, field, context):
    data = suite()
    record = {
        "suite": data,
        "configuration": data["configurations"]["baseline"],
        "scenario": data["scenarios"][0],
        "attempt": data["attempts"][0],
    }[scope]
    del record[field]
    path = tmp_path / "suite.json"
    path.write_text(json.dumps(data))
    output = tmp_path / "out"
    assert main(["evaluate-navigation", "--input", str(path), "--output", str(output)]) == 2
    assert f"{context}: missing required field(s): {field}" in caplog.text
    assert not output.exists()


def test_missing_evidence_field_is_contextual_invalid_attempt():
    data = suite()
    del data["attempts"][0]["elapsed_s"]
    result = evaluate_suite(data)
    assert result["status"] == "INVALID"
    assert result["attempts"][0]["reason"] == (
        "Attempt run_id='0-0-baseline': missing required evidence field: elapsed_s"
    )


def test_synthetic_success_never_approves_navigation_change():
    result = evaluate_suite(suite())
    assert result["status"] == "INCONCLUSIVE"
    assert result["success_delta"]["estimate"] == 0
    assert result["time_ratio"]["estimate"] == 1
    assert "Synthetic" in result["reasons"][0]


def test_simulator_suite_can_pass_and_order_does_not_change_bootstrap():
    data = suite(kind="simulator")
    first = evaluate_suite(data)
    assert first["status"] == "PASS"
    data["attempts"].reverse()
    data["scenarios"].reverse()
    second = evaluate_suite(data)
    assert first["success_delta"] == second["success_delta"]
    assert first["time_ratio"] == second["time_ratio"]


def test_many_seeds_on_one_map_do_not_create_independent_maps():
    data = suite(maps=1, seeds=10, kind="simulator")
    assert evaluate_suite(data)["status"] == "INCONCLUSIVE"


def test_map_aliases_are_one_cluster():
    data = suite(kind="simulator")
    data["scenarios"][1]["map_sha256"] = data["scenarios"][0]["map_sha256"]
    result = evaluate_suite(data)
    assert result["status"] == "INCONCLUSIVE"
    assert result["independent_maps"] == 1


def test_time_regression_with_equal_success():
    data = suite(kind="simulator")
    for attempt in data["attempts"]:
        if attempt["configuration"] == "candidate":
            # Both arrive, but candidate takes one second longer to reach the goal region.
            attempt["elapsed_s"] = 4
            attempt["ground_truth"] = [
                {"t": i / 4, "pose": [min(max(i / 4 - 1, 0) / 2, 1), 0, 0]} for i in range(17)
            ]
            attempt["contact_heartbeat_s"] = [i / 4 for i in range(17)]
    result = evaluate_suite(data)
    assert result["status"] == "REGRESSION"
    assert result["time_ratio"]["estimate"] == pytest.approx(1.4)


def test_output_preserves_exact_input_and_refuses_overwrite(tmp_path):
    path = tmp_path / "suite.json"
    raw = json.dumps(suite()).encode()
    path.write_bytes(raw)
    output = tmp_path / "results"
    result = evaluate_navigation_file(path, output)
    assert result["input_sha256"] == hashlib.sha256(raw).hexdigest()
    assert (output / "input.json").read_bytes() == raw
    assert "synthetic" in (output / "report.md").read_text()
    with pytest.raises(FileExistsError):
        evaluate_navigation_file(path, output)


def test_cli_exit_codes_and_nonfinite_json(tmp_path):
    path = tmp_path / "suite.json"
    path.write_text(json.dumps(suite()))
    assert main(["evaluate-navigation", "--input", str(path), "--output", str(tmp_path / "a")]) == 3
    path.write_text('{"schema_version": NaN}')
    assert main(["evaluate-navigation", "--input", str(path), "--output", str(tmp_path / "b")]) == 2
    assert not (tmp_path / "b").exists()


def test_all_candidate_failures_are_regression_without_paired_successes():
    data = suite(kind="simulator")
    for attempt in data["attempts"]:
        if attempt["configuration"] == "candidate":
            attempt["termination"] = "crash"
    result = evaluate_suite(data)
    assert result["status"] == "REGRESSION"
    assert result["time_ratio"] is None
    assert result["success_delta"]["estimate"] == -1


def test_map_variation_can_make_success_comparison_inconclusive():
    data = suite(maps=3, kind="simulator")
    data["attempts"][1]["termination"] = "crash"
    result = evaluate_suite(data)
    assert result["status"] == "INCONCLUSIVE"
    assert result["success_delta"]["ci95"][0] < -0.02
    assert result["success_delta"]["ci95"][1] > -0.02


@pytest.mark.parametrize(
    "policy",
    [
        {"hold_s": 0},
        {"timeout_s": -1},
        {"success_margin": 1},
        {"time_ratio_limit": 0.9},
        {"min_maps": 1},
        {"min_maps": True},
        {"bootstrap_samples": 10},
        {"typo": 1},
        {"max_evidence_gap_s": 2},
    ],
)
def test_invalid_policy_is_rejected(policy):
    data = suite()
    data["policy"].update(policy)
    with pytest.raises(ValueError):
        evaluate_suite(data)


def test_harness_failure_and_out_of_range_contact_are_invalid():
    data = suite()
    data["attempts"][0]["termination"] = "harness_error"
    assert score(data)["outcome"] == "invalid"
    data["attempts"][0]["termination"] = "finished"
    data["attempts"][0]["obstacle_contacts"] = [{"t": 4, "obstacle": "wall"}]
    assert score(data)["outcome"] == "invalid"


def test_duplicate_scenario_and_empty_schedule_rejected():
    data = suite()
    data["scenarios"].append(copy.deepcopy(data["scenarios"][0]))
    with pytest.raises(ValueError, match="Duplicate"):
        evaluate_suite(data)
    data["scenarios"] = []
    with pytest.raises(ValueError, match="Empty"):
        evaluate_suite(data)


def test_cli_regression_and_invalid_evidence_codes(tmp_path):
    data = suite()
    data["attempts"][1]["obstacle_contacts"] = [{"t": 1, "obstacle": "wall"}]
    path = tmp_path / "suite.json"
    path.write_text(json.dumps(data))
    assert main(["evaluate-navigation", "--input", str(path), "--output", str(tmp_path / "a")]) == 1
    data["attempts"].pop()
    path.write_text(json.dumps(data))
    assert main(["evaluate-navigation", "--input", str(path), "--output", str(tmp_path / "b")]) == 2


def test_pass_exit_code_uses_only_declared_simulator_evidence(tmp_path):
    # This tests the code path, not the authenticity of simulator provenance.
    path = tmp_path / "suite.json"
    path.write_text(json.dumps(suite(kind="simulator")))
    assert main(["evaluate-navigation", "--input", str(path), "--output", str(tmp_path / "a")]) == 0


@pytest.mark.parametrize("value", [None, ["baseline", "candidate"], "baseline"])
def test_malformed_configurations_fail_cleanly(tmp_path, value):
    data = suite()
    data["configurations"] = value
    path = tmp_path / "suite.json"
    path.write_text(json.dumps(data))
    assert (
        main(["evaluate-navigation", "--input", str(path), "--output", str(tmp_path / "out")]) == 2
    )
    assert not (tmp_path / "out").exists()


def test_duplicate_json_keys_rejected(tmp_path):
    source = tmp_path / "suite.json"
    source.write_text('{"schema_version": 1, "schema_version": 2}')
    with pytest.raises(ValueError, match="Duplicate JSON key"):
        evaluate_navigation_file(source, tmp_path / "out")


def test_huge_integer_is_invalid_evidence_instead_of_overflow():
    data = suite()
    data["attempts"][0]["elapsed_s"] = 10**1000
    assert score(data)["outcome"] == "invalid"


def test_rejected_goal_cannot_hide_observed_collision():
    data = suite()
    data["attempts"][0].update(
        termination="rejected",
        elapsed_s=0,
        ground_truth=[],
        contact_heartbeat_s=[],
        obstacle_contacts=[{"t": 0, "obstacle": "wall"}],
    )
    assert score(data)["outcome"] == "invalid"


def test_report_escapes_untrusted_identifiers(tmp_path):
    data = suite()
    malicious = "<img src=x onerror=alert(1)>[click](https://example.com)\n|next"
    data["scenarios"][0]["scenario_id"] = malicious
    for attempt in data["attempts"][:2]:
        attempt["scenario_id"] = malicious
    source = tmp_path / "suite.json"
    source.write_text(json.dumps(data))
    evaluate_navigation_file(source, tmp_path / "out")
    report = (tmp_path / "out" / "report.md").read_text()
    assert "<img" not in report
    assert "[click](" not in report
    assert "&lt;img" in report


def test_input_size_and_bootstrap_work_are_bounded(tmp_path, monkeypatch):
    import ros_telemetry_analytics.navigation_regression as navigation

    source = tmp_path / "suite.json"
    source.write_bytes(b" " * 32)
    monkeypatch.setattr(navigation, "MAX_INPUT_BYTES", 16)
    with pytest.raises(ValueError, match="exceeds"):
        evaluate_navigation_file(source, tmp_path / "out")
    monkeypatch.setattr(navigation, "MAX_BOOTSTRAP_WORK", 100)
    with pytest.raises(ValueError, match="work limit"):
        evaluate_suite(suite())
