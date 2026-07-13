from __future__ import annotations

import json
from pathlib import Path

import pytest

from ros_telemetry_analytics import cli
from ros_telemetry_analytics.config import AnalyticsConfig, PipelineConfig


def _config(tmp_path: Path) -> PipelineConfig:
    return PipelineConfig(
        input_roots=(tmp_path,),
        output_root=tmp_path / "output",
        excluded_directory_names=frozenset(),
        parquet_batch_size=10,
        analytics=AnalyticsConfig(rate_rules=()),
    )


def test_cli_discover_prints_json(tmp_path: Path, monkeypatch, capsys) -> None:
    bag = tmp_path / "sample.mcap"
    bag.write_bytes(b"placeholder")
    monkeypatch.setattr(cli, "load_pipeline_config", lambda *_args, **_kwargs: _config(tmp_path))

    assert cli.main(["discover"]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload[0]["format"] == "rosbag2_mcap"


def test_cli_analyze_returns_nonzero_for_failures(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.setattr(cli, "load_pipeline_config", lambda *_args, **_kwargs: _config(tmp_path))
    monkeypatch.setattr(
        cli,
        "run_pipeline",
        lambda *_args, **_kwargs: {"failed_count": 1, "results": []},
    )

    assert cli.main(["--verbose", "analyze", "--force", "--fail-fast"]) == 1
    assert json.loads(capsys.readouterr().out)["failed_count"] == 1

    monkeypatch.setattr(
        cli,
        "run_pipeline",
        lambda *_args, **_kwargs: {"failed_count": 0, "discovered_count": 0},
    )
    assert cli.main(["analyze"]) == 1


def test_cli_download_selects_assets(tmp_path: Path, monkeypatch, capsys) -> None:
    downloaded = []
    monkeypatch.setattr(cli, "load_asset_config", lambda: {"one": {}, "two": {}})
    monkeypatch.setattr(
        cli,
        "download_asset",
        lambda name, _specification: downloaded.append(name) or tmp_path / name,
    )

    assert cli.main(["download", "--all"]) == 0
    assert downloaded == ["one", "two"]
    assert "one:" in capsys.readouterr().out

    with pytest.raises(SystemExit, match="Unknown asset"):
        cli.main(["download", "--asset", "missing"])
