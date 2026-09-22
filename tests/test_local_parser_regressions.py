"""Optional real reader regressions; tiny public fixtures remain local and unredistributed."""

from pathlib import Path

import pytest
from rosbags.highlevel import AnyReaderError

from ros_telemetry_analytics.discovery import discover_bags
from ros_telemetry_analytics.reader import open_bag

ROOT = Path(__file__).resolve().parents[1] / "data/raw/public_datasets/ros_fixtures"


@pytest.mark.parametrize(
    ("name", "error", "message"),
    [
        ("chatter_50hz.bag", AssertionError, ""),
        ("test_future_version_2.1.bag", AnyReaderError, "not supported"),
        ("test_indexed_1.2.bag", AnyReaderError, "magic is invalid"),
    ],
)
def test_documented_parser_rejection(name, error, message):
    path = ROOT / name
    if not path.exists():
        pytest.skip("Optional public parser fixture not downloaded")
    (source,) = discover_bags([path])
    with pytest.raises(error, match=message), open_bag(source):
        pass


def test_clock_fixture_has_readable_index():
    path = ROOT / "clock_alive.bag"
    if not path.exists():
        pytest.skip("Optional public parser fixture not downloaded")
    (source,) = discover_bags([path])
    with open_bag(source) as reader:
        assert reader.message_count > 0
        assert reader.connections
