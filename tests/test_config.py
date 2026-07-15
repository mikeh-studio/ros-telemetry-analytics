from __future__ import annotations

from pathlib import Path

import pytest

from ros_telemetry_analytics.config import (
    AnalyticsConfig,
    RateRule,
    TopicRelationshipRule,
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
  topic_relationships:
    - name: front_stereo
      type: stereo_sync
      topic_a: /cam0/image_raw
      topic_b: /cam1/image_raw
      pairing_window_ms: 10
      skew_warn_ms: 2
""",
        encoding="utf-8",
    )

    config = load_pipeline_config(config_path)

    assert config.input_roots == (input_root.resolve(),)
    assert config.analytics.expected_rate("/camera/image") == 15.0
    relationship = config.analytics.topic_relationships[0]
    assert relationship.name == "front_stereo"
    assert relationship.relationship_type == "stereo_sync"
    assert relationship.pairing_window_ns == 10_000_000
    assert relationship.skew_warn_ns == 2_000_000
    assert config.parquet_batch_size == 10


@pytest.mark.parametrize("value", [0, -1, ".nan", ".inf"])
def test_load_config_rejects_invalid_threshold(tmp_path: Path, value: object) -> None:
    config_path = tmp_path / "pipeline.yaml"
    config_path.write_text(
        f"analytics:\n  gap_threshold_multiplier: {value}\n",
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

    relationship_change = AnalyticsConfig(
        rate_rules=(RateRule("/camera", 30.0),),
        topic_relationships=(
            TopicRelationshipRule(
                name="front_stereo",
                relationship_type="stereo_sync",
                topic_a="/cam0/image_raw",
                topic_b="/cam1/image_raw",
            ),
        ),
    )
    assert analytics_fingerprint(baseline) != analytics_fingerprint(relationship_change)


@pytest.mark.parametrize(
    ("relationship_yaml", "message"),
    [
        ("type: unsupported\n      topic_a: /a\n      topic_b: /b", "unsupported type"),
        ("topic_a: /same\n      topic_b: /same", "distinct topics"),
        ("topic_a: /a\n      topic_b: /b\n      required: sometimes", "required must be"),
    ],
)
def test_load_config_rejects_invalid_topic_relationship(
    tmp_path: Path,
    relationship_yaml: str,
    message: str,
) -> None:
    config_path = tmp_path / "pipeline.yaml"
    config_path.write_text(
        f"analytics:\n  topic_relationships:\n    - name: invalid\n      {relationship_yaml}\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match=message):
        load_pipeline_config(config_path)
