from __future__ import annotations

import json
from dataclasses import asdict

import polars as pl
import pytest

from ros_telemetry_analytics.localization_eval import (
    SAMPLE_SCHEMA,
    LocalizationEvalConfig,
    apply_localization_detector,
)
from ros_telemetry_analytics.localization_study import (
    aggregate_runs,
    localization_diagnostics,
    render_study_report,
    run_localization_study,
    select_candidate,
    validate_study_manifest,
)


def samples(times, spreads, labels, *, segments=None, run="rec_20250101_000000"):
    count = len(times)
    values = {
        name: [
            False
            if dtype == pl.Boolean
            else 0.0
            if dtype == pl.Float64
            else 0
            if dtype == pl.Int64
            else "source"
        ]
        * count
        for name, dtype in SAMPLE_SCHEMA.items()
    }
    values.update(
        {
            "run_id": [run] * count,
            "timestamp_ns": [int(t * 1e6) for t in times],
            "particle_position_spread_m": spreads,
            "label_failure": labels,
            "segment_id": segments or [0] * count,
        }
    )
    return pl.DataFrame(values, schema=SAMPLE_SCHEMA)


def test_hold_is_causal_time_based_and_resets_at_segment_boundaries():
    source = samples(
        [0, 100, 200, 350, 400], [0.1, 0.5, 0.1, 0.1, 0.1], [False] * 5, segments=[0, 0, 0, 0, 1]
    )
    config = LocalizationEvalConfig(recovery_hold_ms=250)
    result = apply_localization_detector(source, config)
    assert result["detector_failure"].to_list() == [False, True, True, True, False]
    assert apply_localization_detector(source.head(3), config)["detector_failure"].to_list() == (
        result.head(3)["detector_failure"].to_list()
    )
    assert apply_localization_detector(source, LocalizationEvalConfig())[
        "detector_failure"
    ].to_list() == [False, True, False, False, False]


def test_detector_does_not_read_ground_truth_labels_or_errors():
    source = samples([0, 100, 200], [0.1, 0.5, 0.2], [False, True, True])
    changed = source.with_columns(
        (~pl.col("label_failure")).alias("label_failure"),
        pl.lit(10000.0).alias("ground_truth_x"),
        pl.lit(10000.0).alias("position_error_m"),
        pl.lit(10000.0).alias("heading_error_rad"),
    )
    config = LocalizationEvalConfig(recovery_hold_ms=250)
    columns = ["detector_score", "detector_failure"]
    assert (
        apply_localization_detector(source, config)
        .select(columns)
        .equals(apply_localization_detector(changed, config).select(columns))
    )
    # The detector can run with evaluation-only fields physically absent.
    observable = source.select(
        "run_id",
        "source_file",
        "segment_id",
        "timestamp_ns",
        "particle_position_spread_m",
        "estimated_pose_jump_m",
    )
    assert (
        apply_localization_detector(observable, config)
        .select(columns)
        .equals(apply_localization_detector(source, config).select(columns))
    )


def test_backwards_time_is_rejected_and_nonfinite_hold_is_rejected():
    source = samples([100, 0], [0.5, 0.1], [True, False])
    with pytest.raises(ValueError, match="nondecreasing"):
        apply_localization_detector(source, LocalizationEvalConfig(recovery_hold_ms=250))
    for invalid in [-1, float("nan"), float("inf")]:
        with pytest.raises(ValueError):
            LocalizationEvalConfig(recovery_hold_ms=invalid)


def test_duration_metrics_exclude_conflicting_labels_without_changing_record_scores():
    source = samples([0, 0, 1000, 2000, 3000], [0.5] * 5, [False, True, True, False, False])
    config = LocalizationEvalConfig()
    result = localization_diagnostics(apply_localization_detector(source, config), config)
    assert result["sample_count"] == 5
    assert result["sample_metrics"]["precision"] == pytest.approx(2 / 5)
    assert result["data_quality"]["duplicate_timestamp_extra_records"] == 1
    assert result["data_quality"]["conflicting_label_timestamp_groups"] == 1
    time = result["time_metrics"]
    assert time["observed_duration_s"] == 3
    assert time["excluded_ambiguous_duration_s"] == 1
    assert time["unambiguous_duration_s"] == 2
    assert time["failure_duration_s"] == 1
    assert time["covered_failure_duration_s"] == 1
    assert time["false_alert_duration_s"] == 1


def test_unmatched_event_with_coverage_is_distinguished_from_no_alert():
    source = samples(
        [0, 1000, 2000, 3000, 4000, 5000, 6000],
        [0.5, 0.5, 0.5, 0.5, 0.1, 0.1, 0.1],
        [True, False, True, False, False, True, False],
    )
    config = LocalizationEvalConfig()
    result = localization_diagnostics(apply_localization_detector(source, config), config)
    assert result["event_metrics"]["matched_event_count"] == 1
    assert [r["classification"] for r in result["failure_details"]] == [
        "matched",
        "unmatched_with_alert_coverage",
        "no_alert_coverage",
    ]
    assert result["failure_details"][1]["sample_coverage"] == 1
    assert result["time_metrics"]["p95_detection_delay_ms"] == 0


def test_zero_recall_has_zero_f1_and_misses_do_not_get_zero_detection_delay():
    source = samples([0, 1000], [0.1, 0.1], [True, True])
    config = LocalizationEvalConfig()
    result = localization_diagnostics(apply_localization_detector(source, config), config)
    assert result["sample_metrics"]["f1"] == 0
    assert result["time_metrics"]["p95_detection_delay_ms"] is None


def test_duration_does_not_bridge_resets_or_extrapolate_final_samples():
    source = samples([0, 1000, 100000, 101000], [0.5] * 4, [True] * 4, segments=[0, 0, 1, 1])
    config = LocalizationEvalConfig()
    result = localization_diagnostics(apply_localization_detector(source, config), config)
    assert result["time_metrics"]["observed_duration_s"] == 2
    assert result["time_metrics"]["failure_duration_s"] == 2


def test_candidate_selection_enforces_precision_and_event_recall_guardrails():
    def candidate(f1, precision, recall, hold=0):
        return {
            "config": asdict(LocalizationEvalConfig(recovery_hold_ms=hold)),
            "development": {
                "macro_sample_f1": f1,
                "macro_sample_precision": precision,
                "macro_event_recall": recall,
            },
        }

    baseline = candidate(0.6, 0.85, 0.6)
    wanted = candidate(0.65, 0.81, 0.61, 250)
    selected = select_candidate(
        [baseline, wanted, candidate(0.8, 0.7, 0.9), candidate(0.9, 0.9, 0.5)],
        baseline["development"],
    )
    assert selected == wanted


def manifest(tmp_path):
    runs = []
    for i, role in enumerate(["development", "evaluation"]):
        run = f"rec_2025010{i + 1}_000000"
        name = run + "_id_01.processed.parquet"
        (tmp_path / name).write_bytes(b"synthetic input")
        runs.append(
            {
                "run_id": run,
                "environment": f"map-{i}",
                "role": role,
                "sample_count": 3,
                "failure_sample_count": 1,
                "members": [name],
            }
        )
    return {
        "schema_version": 1,
        "runs": runs,
        "candidate_spread_thresholds_m": [0.3, 0.4],
        "candidate_recovery_holds_ms": [0],
    }


def test_manifest_rejects_split_leakage_and_missing_members(tmp_path):
    spec = manifest(tmp_path)
    validate_study_manifest(spec, tmp_path)
    spec["runs"][1]["environment"] = spec["runs"][0]["environment"]
    with pytest.raises(ValueError, match="disjoint"):
        validate_study_manifest(spec, tmp_path)
    spec = manifest(tmp_path)
    spec["runs"].append(spec["runs"][0])
    with pytest.raises(ValueError, match="exactly once"):
        validate_study_manifest(spec, tmp_path)
    spec = manifest(tmp_path)
    (tmp_path / spec["runs"][0]["members"][0]).unlink()
    with pytest.raises(ValueError, match="Missing"):
        validate_study_manifest(spec, tmp_path)


def test_study_freezes_selection_before_loading_evaluation_data(tmp_path, monkeypatch):
    spec = manifest(tmp_path)
    path = tmp_path / "split.json"
    path.write_text(json.dumps(spec))
    output = tmp_path / "output"

    def load(source, config, *, segment_offset):
        run = next(r for r in spec["runs"] if source.name in r["members"])
        if run["role"] == "evaluation":
            assert (output / "selection.json").is_file()
        return apply_localization_detector(
            samples([0, 1000, 2000], [0.1, 0.5, 0.1], [False, True, False], run=run["run_id"]),
            config,
        )

    monkeypatch.setattr(
        "ros_telemetry_analytics.localization_study.load_tuhh_processed_parquet", load
    )
    result = run_localization_study(tmp_path, output, path)
    assert result["aggregates"]["evaluation"]["baseline"]["run_count"] == 1
    assert result["selected_config"]["particle_spread_warn_m"] == 0.4
    assert (output / "study.md").is_file()
    assert json.loads((output / "study.json").read_text())["source_sha256"]
    assert aggregate_runs([result["runs"][0]["baseline"]])["macro_sample_recall"] == 1


def test_report_includes_every_unmatched_event_for_both_detectors():
    from pathlib import Path

    study = json.loads(
        (Path(__file__).parents[1] / "examples/localization_study_results.json").read_text()
    )["localization-refined-study"]
    for index, run in enumerate(study["runs"]):
        for name in ("baseline", "selected"):
            run[name]["failure_details"] = [
                {
                    "detected": False,
                    "expected_event_id": f"missing-{index}",
                    "classification": "no_alert_coverage",
                    "alerted_failure_records": 0,
                    "failure_records": 3,
                    "max_particle_spread_m": 0.1,
                    "max_pose_jump_m": 0.0,
                }
            ]
    report = render_study_report(study)
    expected = 0
    for run in study["runs"]:
        for name in ("baseline", "selected"):
            for event in run[name]["failure_details"]:
                if not event["detected"]:
                    expected += 1
                    prefix = (
                        f"| {run['run_id']} | {run['role']} | {name} | "
                        f"{event['expected_event_id']} |"
                    )
                    assert report.count(prefix) == 1
    assert expected > 0
    assert "then heading disabled" in report


def test_candidate_ties_prefer_heading_disabled_regardless_of_manifest_order():
    metrics = {"macro_sample_f1": 0.7, "macro_sample_precision": 0.8, "macro_event_recall": 0.6}
    disabled = {"config": asdict(LocalizationEvalConfig()), "development": metrics}
    enabled = {
        "config": asdict(LocalizationEvalConfig(heading_spread_warn_rad=0.5)),
        "development": metrics,
    }
    for choices in ([enabled, disabled], [disabled, enabled]):
        assert select_candidate(choices, metrics) == disabled


def test_threshold_validation_distinguishes_disabled_heading_and_zero_hold():
    assert LocalizationEvalConfig(recovery_hold_ms=0).recovery_hold_ms == 0
    with pytest.raises(
        ValueError, match="heading_spread_warn_rad must be finite and greater than zero"
    ):
        LocalizationEvalConfig(heading_spread_warn_rad=0)
    with pytest.raises(ValueError, match="greater than or equal to zero"):
        LocalizationEvalConfig(recovery_hold_ms=-1)
