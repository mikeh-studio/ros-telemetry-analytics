from __future__ import annotations

from pathlib import Path

import yaml

from ros_telemetry_analytics.public_suite import run_public_robotics_suite


def _write_profile(path: Path, input_path: Path, output_path: Path) -> None:
    path.write_text(
        yaml.safe_dump(
            {
                "pipeline": {
                    "project_root": str(path.parent),
                    "input_roots": [str(input_path)],
                    "output_root": str(output_path),
                    "excluded_directory_names": [],
                },
                "analytics": {"domain_analyzers": {"enabled": True}},
            }
        ),
        encoding="utf-8",
    )


def test_public_suite_runs_installed_and_reports_missing_datasets(
    tmp_path: Path,
    write_bag,
) -> None:
    installed_input = tmp_path / "installed"
    write_bag(installed_input / "mission", [("/custom", "std_msgs/msg/String", 0)])
    installed_profile = tmp_path / "installed.yaml"
    missing_profile = tmp_path / "missing.yaml"
    _write_profile(installed_profile, installed_input, tmp_path / "installed-output")
    _write_profile(missing_profile, tmp_path / "missing", tmp_path / "missing-output")
    manifest_path = tmp_path / "datasets.yaml"
    manifest_path.write_text(
        yaml.safe_dump(
            {
                "datasets": {
                    "installed": {
                        "public_robotics_suite": True,
                        "workflow": "coverage",
                        "local_input": str(installed_input),
                        "pipeline_config": str(installed_profile),
                    },
                    "missing": {
                        "public_robotics_suite": True,
                        "workflow": "sync",
                        "local_input": str(tmp_path / "missing"),
                        "pipeline_config": str(missing_profile),
                    },
                    "not_selected": {"public_robotics_suite": False},
                }
            }
        ),
        encoding="utf-8",
    )
    output_path = tmp_path / "suite.json"

    summary = run_public_robotics_suite(manifest_path, output_path=output_path)

    assert summary["dataset_count"] == 2
    assert summary["passed_count"] == 1
    assert summary["not_installed_count"] == 1
    assert summary["failed_count"] == 0
    assert {row["dataset"]: row["status"] for row in summary["results"]} == {
        "installed": "passed",
        "missing": "not_installed",
    }
    assert output_path.is_file()
