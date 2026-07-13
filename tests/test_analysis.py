from __future__ import annotations

import polars as pl

from isaac_telemetry.analysis import (
    build_analysis_summary,
    compute_topic_health,
    compute_vslam_quality,
    pair_timestamps,
)


def _index(rows: list[tuple[str, int]]) -> pl.DataFrame:
    return pl.DataFrame(
        [
            {
                "bag_id": "bag",
                "sequence": sequence,
                "topic": topic,
                "timestamp_ns": timestamp,
            }
            for sequence, (topic, timestamp) in enumerate(rows)
        ]
    )


def test_topic_health_reports_rate_gaps_and_drops(analytics_config) -> None:
    topic = "/camera/left/image_raw"
    frame = _index([(topic, 0), (topic, 33_000_000), (topic, 100_000_000)])

    row = compute_topic_health(frame, analytics_config).row(0, named=True)

    assert row["expected_rate_hz"] == 30.0
    assert row["gap_event_count"] == 1
    assert row["estimated_dropped_messages"] == 1
    assert row["status"] == "warn"


def test_stereo_pairing_recovers_after_middle_frame_drop(analytics_config) -> None:
    millisecond = 1_000_000
    rows = [
        *(("/stereo/left/image_raw", value * millisecond) for value in (0, 33, 66, 99)),
        *(("/stereo/right/image_raw", value * millisecond) for value in (1, 67, 100)),
    ]

    quality = compute_vslam_quality(_index(rows), analytics_config)
    row = quality.filter(pl.col("check_type") == "stereo_sync").row(0, named=True)

    assert row["paired_message_count"] == 3
    assert row["unmatched_left_count"] == 1
    assert row["unmatched_right_count"] == 0
    assert row["max_abs_sync_skew_ns"] == millisecond
    assert row["status"] == "warn"


def test_pair_timestamps_uses_closest_unused_neighbor() -> None:
    skews, unmatched_left, unmatched_right = pair_timestamps(
        [10_000_000],
        [1_000_000, 11_000_000],
        20_000_000,
    )
    assert skews == [1_000_000]
    assert unmatched_left == 0
    assert unmatched_right == 1

    burst_skews, _, burst_unmatched_right = pair_timestamps(
        [100_000_000],
        [81_000_000, 82_000_000, 100_000_000],
        20_000_000,
    )
    assert burst_skews == [0]
    assert burst_unmatched_right == 2


def test_missing_right_camera_and_root_left_topic_are_errors(analytics_config) -> None:
    frame = _index([("/left/image_raw", 0), ("/left/image_raw", 33_000_000)])
    row = compute_vslam_quality(frame, analytics_config).row(0, named=True)

    assert row["topic_right"] == "/right/image_raw"
    assert row["right_message_count"] == 0
    assert row["status"] == "error"


def test_empty_frozen_and_single_message_topics_are_not_healthy(analytics_config) -> None:
    frozen = compute_topic_health(
        _index([("/camera/image_raw", 10), ("/camera/image_raw", 10)]),
        analytics_config,
    ).row(0, named=True)
    single = compute_topic_health(_index([("/camera/image_raw", 10)]), analytics_config).row(
        0, named=True
    )
    empty_summary = build_analysis_summary(
        pl.DataFrame(schema={"status": pl.Utf8}),
        pl.DataFrame(schema={"status": pl.Utf8}),
    )

    assert frozen["status"] == "error"
    assert single["status"] == "warn"
    assert empty_summary["health_status"] == "error"


def test_rate_far_above_expected_is_a_warning(analytics_config) -> None:
    topic = "/camera/image_raw"
    row = compute_topic_health(
        _index([(topic, 0), (topic, 10_000_000), (topic, 20_000_000)]),
        analytics_config,
    ).row(0, named=True)

    assert row["rate_ratio"] > analytics_config.maximum_rate_ratio
    assert row["status"] == "warn"


def test_continuity_and_summary_surface_warning(analytics_config) -> None:
    frame = _index([("/tf", 0), ("/tf", 1), ("/tf", 2), ("/tf", 3), ("/tf", 100)])
    quality = compute_vslam_quality(frame, analytics_config)
    summary = build_analysis_summary(compute_topic_health(frame, analytics_config), quality)

    assert quality.row(0, named=True)["status"] == "warn"
    assert summary["health_status"] == "warn"
    assert summary["warning_count"] == 1


def test_empty_analysis_has_stable_schema(analytics_config) -> None:
    empty = pl.DataFrame(
        schema={
            "bag_id": pl.Utf8,
            "sequence": pl.Int64,
            "topic": pl.Utf8,
            "timestamp_ns": pl.Int64,
        }
    )
    assert compute_topic_health(empty, analytics_config).is_empty()
    assert compute_vslam_quality(empty, analytics_config).is_empty()


def test_analysis_rejects_missing_columns(analytics_config) -> None:
    try:
        compute_topic_health(pl.DataFrame({"topic": ["/tf"]}), analytics_config)
    except ValueError as exc:
        assert "required columns" in str(exc)
    else:
        raise AssertionError("missing message-index columns were accepted")
