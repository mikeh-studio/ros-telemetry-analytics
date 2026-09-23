from copy import deepcopy

import pytest

from ros_telemetry_analytics.incident_grouping import group_events, normalize_events


def event(start, end, kind="dark_frames", topic="/camera", robot=None):
    return {
        "bag_id": "bag",
        "domain": "image",
        "topic": topic,
        "robot_id": robot,
        "start_timestamp_ns": str(start),
        "end_timestamp_ns": str(end),
        "event_type": kind,
        "observed_value": 1.0,
        "threshold": 20.0,
        "unit": "intensity",
        "severity": "warn",
        "detail": "display text",
    }


def test_seed_overlap_prevents_transitive_chains_and_preserves_every_event():
    source = [event(0, 2), event(1, 4, "low_sharpness"), event(3, 5)]
    normalized = normalize_events(source, "source")
    groups = group_events(normalized)
    assert [len(g) for g in groups] == [2, 1]
    assert group_events(normalize_events(source[::-1], "source")) == groups
    assert normalize_events(source, "another-source")[0]["event_id"] != normalized[0]["event_id"]


def test_scopes_families_point_events_and_long_episodes():
    source = [
        event(1, 1),
        event(1, 1, "low_sharpness"),
        event(1, 1, topic="/other"),
        event(1, 1, robot="other"),
        event(1, 1, kind="reference_gap"),
    ]
    assert sorted(map(len, group_events(normalize_events(source, "s")))) == [1, 1, 1, 2]
    source = [event(0, 11_000_000_000), event(1, 2)]
    assert len(group_events(normalize_events(source, "s"))) == 2
    with pytest.raises(ValueError, match="ends before"):
        group_events(normalize_events([event(2, 1)], "s"))


def test_duplicate_multiplicity_and_prose_independence():
    first = [event(0, 1), event(0, 1)]
    second = deepcopy(first)
    second[0]["detail"] = "new explanation"
    a = normalize_events(first, "s")
    b = normalize_events(second, "s")
    assert {e["event_id"] for e in a} == {e["event_id"] for e in b}
    assert len({e["event_id"] for e in a}) == 2
