from __future__ import annotations

from pathlib import Path

import pytest

from isaac_telemetry.config import (
    AnalyticsConfig,
    RateRule,
    analytics_fingerprint,
    load_pipeline_config,
)


def test_load_config_applies_paths_and_rate_rules(tmp_path: Path) -> None:
    input_root = tmp_path / "input"
    input_root.mkdir()
    config_path = tmp_path / "pipeline.yaml"
    config_path.write_text(
        f"""
pipeline:
  input_roots: [{input_root}]
  output_root: {tmp_path / "output"}
  parquet_batch_size: 10
analytics:
  expected_rates:
    - pattern: /camera
      expected_rate_hz: 15
""",
        encoding="utf-8",
    )

    config = load_pipeline_config(config_path)

    assert config.input_roots == (input_root.resolve(),)
    assert config.analytics.expected_rate("/camera/image") == 15.0
    assert config.parquet_batch_size == 10


def test_load_config_rejects_invalid_threshold(tmp_path: Path) -> None:
    config_path = tmp_path / "pipeline.yaml"
    config_path.write_text(
        "analytics:\n  gap_threshold_multiplier: 0\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="gap_threshold_multiplier"):
        load_pipeline_config(config_path)


def test_analytics_fingerprint_is_stable_and_covers_thresholds() -> None:
    baseline = AnalyticsConfig(rate_rules=(RateRule("/camera", 30.0),))
    equivalent = AnalyticsConfig(rate_rules=(RateRule("/camera", 30.0),))
    changed = AnalyticsConfig(
        rate_rules=(RateRule("/camera", 30.0),),
        stereo_skew_warn_ns=10_000_000,
    )

    assert analytics_fingerprint(baseline) == analytics_fingerprint(equivalent)
    assert analytics_fingerprint(baseline) != analytics_fingerprint(changed)
