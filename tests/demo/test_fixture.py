from __future__ import annotations

from collections import Counter
from pathlib import Path

import pytest

from demo.common.config import load_streaming_config
from demo.replayer.generate_fixture import generate_fixture
from ros_telemetry_analytics.discovery import discover_bags
from ros_telemetry_analytics.reader import open_bag

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.demo_integration
def test_generated_fixture_is_a_valid_recorded_mission(tmp_path: Path) -> None:
    config = load_streaming_config(ROOT / "configs/streaming_demo.yaml")
    fixture = generate_fixture(tmp_path / "warehouse_run_17.mcap", config)
    bags = discover_bags([fixture])

    assert len(bags) == 1
    with open_bag(bags[0]) as reader:
        counts = Counter(connection.topic for connection, _timestamp, _raw in reader.messages())

    assert counts == {
        topic.topic: int(config.demo.duration_s * topic.expected_rate_hz)
        for topic in config.analytics.expected_topics
    }
