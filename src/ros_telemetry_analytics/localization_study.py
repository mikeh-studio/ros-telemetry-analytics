"""Run-separated detector comparison and inspectable failure diagnostics.

The study keeps the original record-level and one-to-one event metrics. Additional
time metrics use unique timestamps; conflicting labels do not get silently resolved.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from itertools import product
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl

from ros_telemetry_analytics.localization_eval import (
    LocalizationEvalConfig,
    apply_localization_detector,
    build_localization_events,
    load_tuhh_processed_parquet,
    score_localization,
)


def localization_diagnostics(
    samples: pl.DataFrame, config: LocalizationEvalConfig
) -> dict[str, Any]:
    """Explain unmatched events and measure labeled time without duplicate weighting."""
    events = build_localization_events(samples, config)
    summary, matches = score_localization(samples, events, config)
    exposure_ns = known_ns = failure_ns = covered_ns = false_alert_ns = 0
    duplicate_rows = conflicting_groups = missing_signal_rows = 0
    for part in samples.partition_by(["run_id", "source_file", "segment_id"], maintain_order=True):
        times = part["timestamp_ns"].to_numpy()
        if np.any(np.diff(times) < 0):
            raise ValueError("Localization timestamps must be nondecreasing within each segment")
        missing_signal_rows += part.select(
            (
                ~pl.col("particle_position_spread_m").is_finite().fill_null(False)
                & ~pl.col("estimated_pose_jump_m").is_finite().fill_null(False)
            ).sum()
        ).item()
        ticks = part.group_by("timestamp_ns", maintain_order=True).agg(
            pl.len().alias("records"),
            pl.col("label_failure").n_unique().alias("label_count"),
            pl.col("label_failure").first().alias("label"),
            pl.col("detector_failure").last().alias("alert"),
        )
        duplicate_rows += part.height - ticks.height
        conflicting_groups += ticks.filter(pl.col("label_count") > 1).height
        # The last state at a timestamp applies until the next timestamp. No
        # extrapolation after a segment ends, across resets, or across file boundaries.
        dt = np.diff(ticks["timestamp_ns"].to_numpy())
        known = ticks["label_count"].to_numpy()[:-1] == 1
        labels = ticks["label"].to_numpy()[:-1]
        alerts = ticks["alert"].to_numpy()[:-1]
        exposure_ns += int(dt.sum())
        known_ns += int(dt[known].sum())
        failure_ns += int(dt[known & labels].sum())
        covered_ns += int(dt[known & labels & alerts].sum())
        false_alert_ns += int(dt[known & ~labels & alerts].sum())

    details = []
    for row in matches.iter_rows(named=True):
        window = samples.filter(
            (pl.col("run_id") == row["run_id"])
            & (pl.col("source_file") == row["source_file"])
            & (pl.col("segment_id") == row["segment_id"])
            & pl.col("timestamp_ns").is_between(
                row["expected_start_timestamp_ns"], row["expected_end_timestamp_ns"]
            )
            & pl.col("label_failure")
        )
        covered = window.filter(pl.col("detector_failure")).height
        details.append(
            {
                **row,
                "classification": (
                    "matched"
                    if row["detected"]
                    else "unmatched_with_alert_coverage"
                    if covered
                    else "no_alert_coverage"
                ),
                "failure_records": window.height,
                "alerted_failure_records": covered,
                "sample_coverage": covered / window.height if window.height else None,
                "max_particle_spread_m": window["particle_position_spread_m"].max(),
                "max_pose_jump_m": window["estimated_pose_jump_m"].max(),
                "max_particle_heading_spread_rad": (
                    window["particle_heading_spread_rad"].max()
                    if "particle_heading_spread_rad" in window.columns
                    else None
                ),
                "max_position_error_m": window["position_error_m"].max(),
                "max_heading_error_rad": window["heading_error_rad"].max(),
            }
        )
    delays = [max(0.0, row["onset_lag_ms"]) for row in details if row["detected"]]
    summary.update(
        {
            "time_metrics": {
                "observed_duration_s": exposure_ns / 1e9,
                "unambiguous_duration_s": known_ns / 1e9,
                "excluded_ambiguous_duration_s": (exposure_ns - known_ns) / 1e9,
                "failure_duration_s": failure_ns / 1e9,
                "covered_failure_duration_s": covered_ns / 1e9,
                "failure_duration_coverage": covered_ns / failure_ns if failure_ns else None,
                "false_alert_duration_s": false_alert_ns / 1e9,
                "false_alarm_events_per_hour": (
                    summary["event_metrics"]["false_alarm_event_count"] * 3.6e12 / exposure_ns
                    if exposure_ns
                    else None
                ),
                "p50_detection_delay_ms": float(np.median(delays)) if delays else None,
                "p95_detection_delay_ms": float(np.percentile(delays, 95)) if delays else None,
            },
            "data_quality": {
                "duplicate_timestamp_extra_records": duplicate_rows,
                "conflicting_label_timestamp_groups": conflicting_groups,
                "missing_both_signal_records": missing_signal_rows,
            },
            "failure_details": details,
        }
    )
    return summary


def aggregate_runs(results: list[dict[str, Any]]) -> dict[str, Any]:
    """Macro metrics give each run equal weight; time rates pool their denominators."""
    if not results:
        raise ValueError("At least one run is required")

    def mean(section: str, metric: str) -> float | None:
        values = [r[section][metric] for r in results if r[section][metric] is not None]
        return float(np.mean(values)) if values else None

    duration = sum(r["time_metrics"]["observed_duration_s"] for r in results)
    failures = sum(r["time_metrics"]["failure_duration_s"] for r in results)
    covered = sum(r["time_metrics"]["covered_failure_duration_s"] for r in results)
    false_alarms = sum(r["event_metrics"]["false_alarm_event_count"] for r in results)
    return {
        "run_count": len(results),
        "sample_count": sum(r["sample_count"] for r in results),
        "macro_sample_precision": mean("sample_metrics", "precision"),
        "macro_sample_recall": mean("sample_metrics", "recall"),
        "macro_sample_f1": mean("sample_metrics", "f1"),
        "macro_event_recall": mean("event_metrics", "recall"),
        "macro_event_precision": mean("event_metrics", "precision"),
        "failure_duration_coverage": covered / failures if failures else None,
        "false_alarm_events_per_hour": false_alarms * 3600 / duration if duration else None,
        "observed_duration_s": duration,
    }


def select_candidate(candidates: list[dict[str, Any]], baseline: dict[str, Any]) -> dict[str, Any]:
    """Select on development data only under the predeclared precision/recall guardrails."""
    precision_floor = (baseline["macro_sample_precision"] or 0.0) - 0.05
    recall_floor = baseline["macro_event_recall"] or 0.0
    eligible = [
        c
        for c in candidates
        if c["development"]["macro_sample_precision"] is not None
        and c["development"]["macro_sample_precision"] >= precision_floor
        and c["development"]["macro_event_recall"] is not None
        and c["development"]["macro_event_recall"] >= recall_floor
        and c["development"]["macro_sample_f1"] is not None
    ]
    if not eligible:
        raise ValueError("No candidate has defined metrics satisfying development guardrails")
    return max(
        eligible,
        key=lambda c: (
            c["development"]["macro_sample_f1"],
            -c["config"]["recovery_hold_ms"],
            c["config"]["particle_spread_warn_m"],
            c["config"].get("heading_spread_warn_rad") is None,
        ),
    )


def validate_study_manifest(manifest: dict[str, Any], input_dir: Path) -> None:
    if manifest.get("schema_version") != 1:
        raise ValueError("Unsupported localization study manifest version")
    runs = manifest["runs"]
    if len({r["run_id"] for r in runs}) != len(runs):
        raise ValueError("Each run must occur exactly once in the study split")
    roles = {r["role"] for r in runs}
    if roles != {"development", "evaluation"}:
        raise ValueError("The study requires development and evaluation runs")
    dev_env = {r["environment"] for r in runs if r["role"] == "development"}
    test_env = {r["environment"] for r in runs if r["role"] == "evaluation"}
    if dev_env & test_env:
        raise ValueError("Development and evaluation environments must be disjoint")
    members = []
    for run in runs:
        if not run["members"]:
            raise ValueError("Each run needs its complete source member list")
        for name in run["members"]:
            if Path(name).name != name or not name.startswith(run["run_id"] + "_id_"):
                raise ValueError("Source members must be plain filenames belonging to their run")
            if not (input_dir / name).is_file():
                raise ValueError(f"Missing localization input: {name}")
            members.append(name)
    if len(set(members)) != len(members):
        raise ValueError("Source members cannot be reused across runs")
    candidate_configs(manifest)


def candidate_configs(manifest: dict[str, Any]) -> list[LocalizationEvalConfig]:
    return [
        LocalizationEvalConfig(
            particle_spread_warn_m=threshold, recovery_hold_ms=hold, heading_spread_warn_rad=heading
        )
        for threshold, hold, heading in product(
            manifest["candidate_spread_thresholds_m"],
            manifest["candidate_recovery_holds_ms"],
            manifest.get("candidate_heading_spread_thresholds_rad", [None]),
        )
    ]


def _write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n")


def render_study_report(study: dict[str, Any]) -> str:
    selected = study["selected_config"]
    lines = [
        "# Localization detector study",
        "",
        "Published TUHH simulation data; a fixed split by environment. "
        "The evaluation environments were excluded from candidate selection.",
        "",
        f"Selected spread threshold: **{selected['particle_spread_warn_m']:g} m**; "
        f"recovery hold: **{selected['recovery_hold_ms']:g} ms**. "
        "AMCL pose-jump threshold remains 0.5 m.",
        "Particle heading-spread threshold: "
        f"{selected.get('heading_spread_warn_rad') or 'disabled'}.",
        study["manifest"].get("experiment_note", ""),
        "",
        "## Baseline versus selected detector",
        "",
        "Precision, recall, F1, and event recall below are macro averages across runs. "
        "Duration coverage and false alarms/hour pool time across runs.",
        "",
        "| Split | Detector | Runs | Precision | Recall | F1 | Event recall | "
        "Failure time covered | False alarms/h |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]

    def fmt(value: float | None) -> str:
        return "—" if value is None else f"{value:.3f}"

    for role in ("development", "evaluation"):
        for name in ("baseline", "selected"):
            r = study["aggregates"][role][name]
            lines.append(
                f"| {role} | {name} | {r['run_count']} | "
                + " | ".join(
                    fmt(r[k])
                    for k in (
                        "macro_sample_precision",
                        "macro_sample_recall",
                        "macro_sample_f1",
                        "macro_event_recall",
                        "failure_duration_coverage",
                        "false_alarm_events_per_hour",
                    )
                )
                + " |"
            )
    lines.extend(
        [
            "",
            "## Development candidates",
            "",
            "Eligibility uses the fixed precision and event-recall guardrails, "
            "before ranking by F1.",
            "",
            "| Spread (m) | Hold (ms) | Heading (rad) | Precision | Recall | F1 | "
            "Event recall | Eligible |",
            "| ---: | ---: | --- | ---: | ---: | ---: | ---: | --- |",
        ]
    )
    reference = study["aggregates"]["development"]["baseline"]
    for candidate in study["candidates"]:
        config = candidate["config"]
        values = candidate["development"]
        eligible = (
            values["macro_sample_precision"] is not None
            and values["macro_event_recall"] is not None
            and values["macro_sample_precision"] >= reference["macro_sample_precision"] - 0.05
            and values["macro_event_recall"] >= reference["macro_event_recall"]
        )
        lines.append(
            f"| {config['particle_spread_warn_m']:g} | {config['recovery_hold_ms']:g} | "
            f"{config.get('heading_spread_warn_rad') or 'off'} | "
            + " | ".join(
                fmt(values[key])
                for key in (
                    "macro_sample_precision",
                    "macro_sample_recall",
                    "macro_sample_f1",
                    "macro_event_recall",
                )
            )
            + f" | {'yes' if eligible else 'no'} |"
        )
    lines.extend(
        [
            "",
            "## Per-run results",
            "",
            "| Run | Environment | Split | Detector | Precision | Recall | Event recall | "
            "False alarms | P95 delay (ms) |",
            "| --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for run in study["runs"]:
        for name in ("baseline", "selected"):
            r = run[name]
            lines.append(
                f"| {run['run_id']} | {run['environment']} | {run['role']} | {name} | "
                f"{fmt(r['sample_metrics']['precision'])} | {fmt(r['sample_metrics']['recall'])} | "
                f"{fmt(r['event_metrics']['recall'])} | "
                f"{r['event_metrics']['false_alarm_event_count']} | "
                f"{fmt(r['time_metrics']['p95_detection_delay_ms'])} |"
            )
    lines.extend(
        [
            "",
            "## Original warehouse baseline: unmatched events",
            "",
            "One-to-one event matching is unchanged. An unmatched event can still have alert "
            "coverage when a long alert has already been assigned to another event.",
            "",
            "| Event | Classification | Failure samples alerted | Max spread (m) | Max jump (m) |",
            "| --- | --- | ---: | ---: | ---: |",
        ]
    )
    for run in study["runs"]:
        if run["run_id"] == "rec_20250821_104113":
            for row in run["baseline"]["failure_details"]:
                if not row["detected"]:
                    lines.append(
                        f"| {row['expected_event_id']} | {row['classification']} | "
                        f"{row['alerted_failure_records']}/{row['failure_records']} | "
                        f"{fmt(row['max_particle_spread_m'])} | {fmt(row['max_pose_jump_m'])} |"
                    )
    lines.extend(
        [
            "",
            "## Methodology and limits",
            "",
            "- Selection maximizes development macro sample F1 with precision at least "
            "baseline minus 0.05 and event recall at least baseline. Only the baseline and "
            "selected configuration are evaluated on the held-out environments.",
            "- Original record-level scores retain repeated timestamps. Duration metrics use "
            "the final alert at each unique timestamp until the next timestamp within that "
            "source segment. Intervals with conflicting labels are excluded from labeled "
            "duration metrics; their duration and counts are reported in JSON.",
            "- Detection-delay percentiles include matched events only; already-active alerts "
            "have zero delay. Misses are reported separately, not assigned zero delay.",
            "- False alarms/hour uses observed segment time, including failure time. These "
            "short, failure-rich simulation runs do not establish a real-world alarm rate.",
            "- Source segments end at upstream localization resets. The detector resets its "
            "hold at those boundaries and source-file boundaries; continuous-operation "
            "generalization requires a separate live evaluation.",
            "- No ground-truth pose, error, or label is used in detector decisions. This "
            "experiment calibrates existing observable signals; it does not establish "
            "causes of failures or production readiness.",
            "- See study.json for per-event evidence, data-quality counts, source hashes, "
            "the complete development candidate table, and the frozen split.",
            "",
            "Source: https://doi.org/10.15480/882.15836 (CC BY 4.0).",
            "",
        ]
    )
    quality = {
        key: sum(run["baseline"]["data_quality"][key] for run in study["runs"])
        for key in (
            "duplicate_timestamp_extra_records",
            "conflicting_label_timestamp_groups",
            "missing_both_signal_records",
        )
    }
    differences = [
        run
        for run in study["runs"]
        if run.get("source_count_check", {}).get("failure_sample_delta")
    ]
    lines.extend(
        [
            "## Source quality checks",
            "",
            "Repeated-timestamp extra records: "
            f"**{quality['duplicate_timestamp_extra_records']}**. "
            "Conflicting-label timestamp groups: "
            f"**{quality['conflicting_label_timestamp_groups']}**. "
            f"Records missing both baseline signals: **{quality['missing_both_signal_records']}**.",
            "",
            "All source sample totals must match the manifest. Failure-label count differences "
            "below compare published Parquet labels with the upstream info.csv; Parquet labels "
            "are used for scoring.",
            "",
            "| Run | CSV failure samples | Parquet failure samples | Difference |",
            "| --- | ---: | ---: | ---: |",
        ]
    )
    for run in differences:
        check = run["source_count_check"]
        lines.append(
            f"| {run['run_id']} | {check['declared_failure_samples']} | "
            f"{check['observed_failure_samples']} | {check['failure_sample_delta']:+d} |"
        )
    lines.append("")
    return "\n".join(lines)


def run_localization_study(
    input_dir: Path, output_dir: Path, manifest_path: Path
) -> dict[str, Any]:
    manifest = json.loads(manifest_path.read_text())
    validate_study_manifest(manifest, input_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    baseline_config = LocalizationEvalConfig()
    frames: dict[str, pl.DataFrame] = {}
    hashes = {}

    def load_run(run: dict[str, Any]) -> pl.DataFrame:
        parts = []
        offset = 0
        for name in run["members"]:
            path = input_dir / name
            with path.open("rb") as source:
                hashes[name] = hashlib.file_digest(source, "sha256").hexdigest()
            part = load_tuhh_processed_parquet(path, baseline_config, segment_offset=offset)
            if part.is_empty():
                raise ValueError(f"Empty source member: {name}")
            offset = int(part["segment_id"].max()) + 1
            parts.append(part)
        samples = pl.concat(parts)
        if samples["run_id"].unique().to_list() != [run["run_id"]]:
            raise ValueError("Loaded run identity does not match manifest")
        if samples.height != run["sample_count"]:
            raise ValueError(f"Source counts differ from manifest for {run['run_id']}")
        samples.write_parquet(output_dir / f"{run['run_id']}.samples.parquet", compression="zstd")
        return samples

    development = [r for r in manifest["runs"] if r["role"] == "development"]
    baseline_results = []
    for run in development:
        print(f"Loading development run {run['run_id']}", flush=True)
        frames[run["run_id"]] = load_run(run)
        baseline_results.append(localization_diagnostics(frames[run["run_id"]], baseline_config))
    baseline_aggregate = aggregate_runs(baseline_results)
    candidates = [{"config": asdict(baseline_config), "development": baseline_aggregate}]
    for config in candidate_configs(manifest):
        if config == baseline_config:
            continue
        print(f"Development candidate {asdict(config)}", flush=True)
        results = [
            localization_diagnostics(apply_localization_detector(frame, config), config)
            for frame in frames.values()
        ]
        candidates.append({"config": asdict(config), "development": aggregate_runs(results)})
    selected = select_candidate(candidates, baseline_aggregate)
    selected_config = LocalizationEvalConfig(**selected["config"])
    # Persist the decision BEFORE loading/scoring evaluation runs.
    _write_json(
        output_dir / "selection.json",
        {
            "manifest": manifest,
            "candidates": candidates,
            "selected_config": asdict(selected_config),
        },
    )
    print(f"Frozen selected configuration: {asdict(selected_config)}", flush=True)
    run_results = []
    for run in manifest["runs"]:
        frame = frames.get(run["run_id"])
        if frame is None:
            print(f"Loading held-out run {run['run_id']}", flush=True)
            frame = load_run(run)
        run_results.append(
            {
                "run_id": run["run_id"],
                "environment": run["environment"],
                "role": run["role"],
                "source_count_check": {
                    "declared_samples": run["sample_count"],
                    "observed_samples": frame.height,
                    "declared_failure_samples": run["failure_sample_count"],
                    "observed_failure_samples": int(frame["label_failure"].sum()),
                    "failure_sample_delta": int(frame["label_failure"].sum())
                    - run["failure_sample_count"],
                },
                "baseline": localization_diagnostics(frame, baseline_config),
                "selected": localization_diagnostics(
                    apply_localization_detector(frame, selected_config), selected_config
                ),
            }
        )
    study = {
        "schema_version": 1,
        "manifest": manifest,
        "source_sha256": hashes,
        "selected_config": asdict(selected_config),
        "candidates": candidates,
        "runs": run_results,
        "aggregates": {
            role: {
                name: aggregate_runs([r[name] for r in run_results if r["role"] == role])
                for name in ("baseline", "selected")
            }
            for role in ("development", "evaluation")
        },
    }
    _write_json(output_dir / "study.json", study)
    (output_dir / "study.md").write_text(render_study_report(study))
    return study
