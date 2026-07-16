from __future__ import annotations

import bisect
import json
import math
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import polars as pl

from ros_telemetry_analytics.config import DomainAnalyticsConfig
from ros_telemetry_analytics.domain import DOMAIN_RECORD_PATHS

METRIC_SCHEMA = {
    "bag_id": pl.Utf8,
    "domain": pl.Utf8,
    "topic": pl.Utf8,
    "metric": pl.Utf8,
    "value": pl.Float64,
    "unit": pl.Utf8,
    "status": pl.Utf8,
    "detail": pl.Utf8,
}

EVENT_SCHEMA = {
    "bag_id": pl.Utf8,
    "domain": pl.Utf8,
    "topic": pl.Utf8,
    "start_timestamp_ns": pl.Int64,
    "end_timestamp_ns": pl.Int64,
    "severity": pl.Utf8,
    "event_type": pl.Utf8,
    "observed_value": pl.Float64,
    "threshold": pl.Float64,
    "unit": pl.Utf8,
    "detail": pl.Utf8,
}

PREFERRED_DOMAIN_METRICS = frozenset(
    {
        "distance_traveled",
        "max_linear_speed",
        "stationary_fraction",
        "max_acceleration_magnitude",
        "max_angular_velocity",
        "p95_speed_tracking_error",
        "unresponsive_command_count",
        "frame_cycle_count",
        "translation_path_length",
        "max_translation_speed",
        "non_ok_count",
        "duplicate_frame_count",
        "mean_intensity",
        "minimum_sharpness",
        "mean_depth",
        "mean_valid_pixel_fraction",
        "deserialization_error_count",
    }
)


def _empty_frame(schema: dict[str, pl.DataType]) -> pl.DataFrame:
    return pl.DataFrame(schema=schema)


def _status_priority(status: str) -> tuple[bool, int]:
    return status == "ok", {"error": 0, "warn": 1}.get(status, 2)


def _select_metric_rows(metrics: pl.DataFrame, limit: int) -> list[dict[str, Any]]:
    rows = [
        row
        for row in metrics.iter_rows(named=True)
        if row["metric"] in PREFERRED_DOMAIN_METRICS or row["status"] != "ok"
    ]
    rows.sort(
        key=lambda row: (
            *_status_priority(row["status"]),
            row["domain"],
            row["topic"],
            row["metric"],
        )
    )
    return rows[:limit]


def _select_event_rows(events: pl.DataFrame, limit: int) -> list[dict[str, Any]]:
    rows = list(events.iter_rows(named=True))
    rows.sort(
        key=lambda row: (
            *_status_priority(row["severity"]),
            row["start_timestamp_ns"],
            row["domain"],
            row["topic"],
            row["event_type"],
        )
    )
    return rows[:limit]


def _read_records(output_dir: Path) -> dict[str, pl.DataFrame]:
    return {
        name: pl.read_parquet(output_dir / relative_path)
        for name, relative_path in DOMAIN_RECORD_PATHS.items()
    }


def _metric(
    rows: list[dict[str, Any]],
    bag_id: str,
    domain: str,
    topic: str,
    name: str,
    value: float | int,
    unit: str,
    *,
    status: str = "ok",
    detail: str = "",
) -> None:
    rows.append(
        {
            "bag_id": bag_id,
            "domain": domain,
            "topic": topic,
            "metric": name,
            "value": float(value),
            "unit": unit,
            "status": status,
            "detail": detail,
        }
    )


def _event(
    rows: list[dict[str, Any]],
    bag_id: str,
    domain: str,
    topic: str,
    start_timestamp_ns: int,
    end_timestamp_ns: int,
    severity: str,
    event_type: str,
    observed_value: float | int | None,
    threshold: float | int | None,
    unit: str,
    detail: str,
) -> None:
    rows.append(
        {
            "bag_id": bag_id,
            "domain": domain,
            "topic": topic,
            "start_timestamp_ns": int(start_timestamp_ns),
            "end_timestamp_ns": int(end_timestamp_ns),
            "severity": severity,
            "event_type": event_type,
            "observed_value": float(observed_value) if observed_value is not None else None,
            "threshold": float(threshold) if threshold is not None else None,
            "unit": unit,
            "detail": detail,
        }
    )


def _magnitude(x: float, y: float, z: float) -> float:
    return math.sqrt(x * x + y * y + z * z)


def _quantile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, math.ceil(percentile * len(ordered)) - 1)
    return ordered[index]


def _group_samples(
    samples: list[tuple[int, float]],
    merge_gap_ns: int,
) -> list[tuple[int, int, float, int]]:
    if not samples:
        return []
    ordered = sorted(samples)
    groups: list[tuple[int, int, float, int]] = []
    start, previous, maximum, count = ordered[0][0], ordered[0][0], ordered[0][1], 1
    for timestamp, value in ordered[1:]:
        if timestamp - previous <= merge_gap_ns:
            previous = timestamp
            maximum = max(maximum, value)
            count += 1
            continue
        groups.append((start, previous, maximum, count))
        start, previous, maximum, count = timestamp, timestamp, value, 1
    groups.append((start, previous, maximum, count))
    return groups


def _analyze_odometry(
    frame: pl.DataFrame,
    config: DomainAnalyticsConfig,
    metrics: list[dict[str, Any]],
    events: list[dict[str, Any]],
) -> None:
    for partition in frame.partition_by(["bag_id", "topic"], maintain_order=True):
        rows = sorted(partition.iter_rows(named=True), key=lambda row: row["timestamp_ns"])
        bag_id = rows[0]["bag_id"]
        topic = rows[0]["topic"]
        positions = [(row["position_x"], row["position_y"], row["position_z"]) for row in rows]
        speeds = [_magnitude(row["linear_x"], row["linear_y"], row["linear_z"]) for row in rows]
        jumps = [
            _magnitude(
                current[0] - previous[0],
                current[1] - previous[1],
                current[2] - previous[2],
            )
            for previous, current in zip(positions, positions[1:], strict=False)
        ]
        distance = sum(jumps)
        duration_s = (
            (rows[-1]["timestamp_ns"] - rows[0]["timestamp_ns"]) / 1_000_000_000
            if len(rows) > 1
            else 0.0
        )
        max_jump = max(jumps, default=0.0)
        stationary_fraction = sum(
            speed <= config.stationary_speed_threshold_mps for speed in speeds
        ) / len(speeds)
        _metric(metrics, bag_id, "odometry", topic, "message_count", len(rows), "messages")
        _metric(metrics, bag_id, "odometry", topic, "duration", duration_s, "s")
        _metric(metrics, bag_id, "odometry", topic, "distance_traveled", distance, "m")
        _metric(
            metrics,
            bag_id,
            "odometry",
            topic,
            "mean_linear_speed",
            sum(speeds) / len(speeds),
            "m/s",
        )
        _metric(metrics, bag_id, "odometry", topic, "max_linear_speed", max(speeds), "m/s")
        _metric(
            metrics, bag_id, "odometry", topic, "stationary_fraction", stationary_fraction, "ratio"
        )
        _metric(
            metrics,
            bag_id,
            "odometry",
            topic,
            "max_pose_jump",
            max_jump,
            "m",
            status="warn" if max_jump > config.odometry_pose_jump_warn_m else "ok",
            detail=f"warning threshold {config.odometry_pose_jump_warn_m:.3f} m",
        )
        for index, jump in enumerate(jumps, start=1):
            if jump <= config.odometry_pose_jump_warn_m:
                continue
            timestamp = rows[index]["timestamp_ns"]
            _event(
                events,
                bag_id,
                "odometry",
                topic,
                timestamp,
                timestamp,
                "warn",
                "pose_jump",
                jump,
                config.odometry_pose_jump_warn_m,
                "m",
                "Consecutive odometry positions exceeded the configured jump threshold.",
            )


def _analyze_imu(
    frame: pl.DataFrame,
    config: DomainAnalyticsConfig,
    metrics: list[dict[str, Any]],
    events: list[dict[str, Any]],
) -> None:
    for partition in frame.partition_by(["bag_id", "topic"], maintain_order=True):
        rows = sorted(partition.iter_rows(named=True), key=lambda row: row["timestamp_ns"])
        bag_id = rows[0]["bag_id"]
        topic = rows[0]["topic"]
        accelerations = [
            _magnitude(
                row["linear_acceleration_x"],
                row["linear_acceleration_y"],
                row["linear_acceleration_z"],
            )
            for row in rows
        ]
        angular_velocities = [
            _magnitude(
                row["angular_velocity_x"],
                row["angular_velocity_y"],
                row["angular_velocity_z"],
            )
            for row in rows
        ]
        max_acceleration = max(accelerations)
        max_angular_velocity = max(angular_velocities)
        _metric(metrics, bag_id, "imu", topic, "message_count", len(rows), "messages")
        _metric(
            metrics,
            bag_id,
            "imu",
            topic,
            "mean_acceleration_magnitude",
            sum(accelerations) / len(accelerations),
            "m/s^2",
        )
        _metric(
            metrics,
            bag_id,
            "imu",
            topic,
            "max_acceleration_magnitude",
            max_acceleration,
            "m/s^2",
            status="warn" if max_acceleration > config.imu_acceleration_warn_mps2 else "ok",
        )
        _metric(
            metrics,
            bag_id,
            "imu",
            topic,
            "max_angular_velocity",
            max_angular_velocity,
            "rad/s",
            status=(
                "warn" if max_angular_velocity > config.imu_angular_velocity_warn_rad_s else "ok"
            ),
        )
        acceleration_samples = [
            (row["timestamp_ns"], value)
            for row, value in zip(rows, accelerations, strict=True)
            if value > config.imu_acceleration_warn_mps2
        ]
        for start, end, maximum, count in _group_samples(
            acceleration_samples, config.event_merge_gap_ns
        ):
            _event(
                events,
                bag_id,
                "imu",
                topic,
                start,
                end,
                "warn",
                "high_acceleration",
                maximum,
                config.imu_acceleration_warn_mps2,
                "m/s^2",
                f"{count} IMU samples exceeded the acceleration threshold.",
            )
        angular_samples = [
            (row["timestamp_ns"], value)
            for row, value in zip(rows, angular_velocities, strict=True)
            if value > config.imu_angular_velocity_warn_rad_s
        ]
        for start, end, maximum, count in _group_samples(
            angular_samples, config.event_merge_gap_ns
        ):
            _event(
                events,
                bag_id,
                "imu",
                topic,
                start,
                end,
                "warn",
                "high_angular_velocity",
                maximum,
                config.imu_angular_velocity_warn_rad_s,
                "rad/s",
                f"{count} IMU samples exceeded the angular velocity threshold.",
            )


def _analyze_commands(
    commands: pl.DataFrame,
    odometry: pl.DataFrame,
    config: DomainAnalyticsConfig,
    metrics: list[dict[str, Any]],
    events: list[dict[str, Any]],
) -> None:
    odometry_partitions = odometry.partition_by("topic", maintain_order=True)
    reference_odometry = max(odometry_partitions, key=lambda frame: frame.height, default=None)
    odometry_rows = (
        sorted(reference_odometry.iter_rows(named=True), key=lambda row: row["timestamp_ns"])
        if reference_odometry is not None
        else []
    )
    odometry_times = [row["timestamp_ns"] for row in odometry_rows]
    odometry_speeds = [
        _magnitude(row["linear_x"], row["linear_y"], row["linear_z"]) for row in odometry_rows
    ]

    for partition in commands.partition_by(["bag_id", "topic"], maintain_order=True):
        rows = sorted(partition.iter_rows(named=True), key=lambda row: row["timestamp_ns"])
        bag_id = rows[0]["bag_id"]
        topic = rows[0]["topic"]
        command_speeds = [
            _magnitude(row["linear_x"], row["linear_y"], row["linear_z"]) for row in rows
        ]
        _metric(metrics, bag_id, "command", topic, "message_count", len(rows), "messages")
        _metric(
            metrics, bag_id, "command", topic, "max_commanded_speed", max(command_speeds), "m/s"
        )
        if not odometry_rows:
            _metric(
                metrics,
                bag_id,
                "command",
                topic,
                "matched_odometry_count",
                0,
                "messages",
                status="warn",
                detail="No odometry records were available for command comparison.",
            )
            _event(
                events,
                bag_id,
                "command",
                topic,
                rows[0]["timestamp_ns"],
                rows[-1]["timestamp_ns"],
                "warn",
                "missing_odometry",
                0,
                None,
                "messages",
                "Velocity commands were present without odometry for response analysis.",
            )
            continue

        tracking_errors: list[float] = []
        unresponsive_samples: list[tuple[int, float]] = []
        for row, commanded_speed in zip(rows, command_speeds, strict=True):
            index = bisect.bisect_left(odometry_times, row["timestamp_ns"])
            candidates = [
                candidate
                for candidate in (index - 1, index)
                if 0 <= candidate < len(odometry_times)
            ]
            if not candidates:
                continue
            match = min(
                candidates,
                key=lambda candidate: abs(odometry_times[candidate] - row["timestamp_ns"]),
            )
            if abs(odometry_times[match] - row["timestamp_ns"]) > config.command_response_window_ns:
                continue
            observed_speed = odometry_speeds[match]
            error = abs(commanded_speed - observed_speed)
            tracking_errors.append(error)
            if (
                commanded_speed >= config.command_motion_threshold_mps
                and observed_speed <= config.stationary_speed_threshold_mps
            ):
                unresponsive_samples.append((row["timestamp_ns"], commanded_speed))

        p95_error = _quantile(tracking_errors, 0.95)
        _metric(
            metrics,
            bag_id,
            "command",
            topic,
            "matched_odometry_count",
            len(tracking_errors),
            "messages",
            status="warn" if not tracking_errors else "ok",
        )
        if tracking_errors:
            _metric(
                metrics,
                bag_id,
                "command",
                topic,
                "mean_speed_tracking_error",
                sum(tracking_errors) / len(tracking_errors),
                "m/s",
            )
            _metric(
                metrics,
                bag_id,
                "command",
                topic,
                "p95_speed_tracking_error",
                p95_error or 0.0,
                "m/s",
                status=(
                    "warn"
                    if p95_error is not None and p95_error > config.command_tracking_error_warn_mps
                    else "ok"
                ),
            )
        _metric(
            metrics,
            bag_id,
            "command",
            topic,
            "unresponsive_command_count",
            len(unresponsive_samples),
            "messages",
            status="warn" if unresponsive_samples else "ok",
        )
        for start, end, maximum, count in _group_samples(
            unresponsive_samples, config.event_merge_gap_ns
        ):
            _event(
                events,
                bag_id,
                "command",
                topic,
                start,
                end,
                "warn",
                "command_without_motion",
                maximum,
                config.command_motion_threshold_mps,
                "m/s",
                f"{count} motion commands matched stationary odometry.",
            )


def _graph_cycle_count(edges: set[tuple[str, str]]) -> int:
    adjacency: dict[str, set[str]] = defaultdict(set)
    for parent, child in edges:
        adjacency[parent].add(child)
    visiting: set[str] = set()
    visited: set[str] = set()
    cycle_edges = 0

    def visit(node: str) -> None:
        nonlocal cycle_edges
        if node in visited:
            return
        visiting.add(node)
        for child in adjacency[node]:
            if child in visiting:
                cycle_edges += 1
            else:
                visit(child)
        visiting.remove(node)
        visited.add(node)

    for node in list(adjacency):
        visit(node)
    return cycle_edges


def _graph_component_count(edges: set[tuple[str, str]]) -> int:
    adjacency: dict[str, set[str]] = defaultdict(set)
    for parent, child in edges:
        adjacency[parent].add(child)
        adjacency[child].add(parent)
    remaining = set(adjacency)
    count = 0
    while remaining:
        count += 1
        stack = [remaining.pop()]
        while stack:
            node = stack.pop()
            neighbors = adjacency[node].intersection(remaining)
            remaining.difference_update(neighbors)
            stack.extend(neighbors)
    return count


def _analyze_transforms(
    frame: pl.DataFrame,
    config: DomainAnalyticsConfig,
    metrics: list[dict[str, Any]],
    events: list[dict[str, Any]],
) -> None:
    for bag_partition in frame.partition_by("bag_id", maintain_order=True):
        bag_id = bag_partition.item(0, "bag_id")
        edges = {
            (row["frame_id"], row["child_frame_id"])
            for row in bag_partition.iter_rows(named=True)
            if row["frame_id"] and row["child_frame_id"]
        }
        empty_frames = bag_partition.filter(
            (pl.col("frame_id") == "") | (pl.col("child_frame_id") == "")
        ).height
        self_transforms = sum(parent == child for parent, child in edges)
        cycle_count = _graph_cycle_count(edges)
        component_count = _graph_component_count(edges)
        _metric(metrics, bag_id, "tf", "*", "transform_count", bag_partition.height, "transforms")
        _metric(metrics, bag_id, "tf", "*", "frame_pair_count", len(edges), "pairs")
        _metric(metrics, bag_id, "tf", "*", "frame_component_count", component_count, "components")
        _metric(
            metrics,
            bag_id,
            "tf",
            "*",
            "empty_frame_count",
            empty_frames,
            "transforms",
            status="warn" if empty_frames else "ok",
        )
        _metric(
            metrics,
            bag_id,
            "tf",
            "*",
            "self_transform_count",
            self_transforms,
            "pairs",
            status="error" if self_transforms else "ok",
        )
        _metric(
            metrics,
            bag_id,
            "tf",
            "*",
            "frame_cycle_count",
            cycle_count,
            "cycles",
            status="error" if cycle_count else "ok",
        )
        if cycle_count:
            timestamps = bag_partition.get_column("timestamp_ns")
            _event(
                events,
                bag_id,
                "tf",
                "*",
                int(timestamps.min()),
                int(timestamps.max()),
                "error",
                "frame_cycle",
                cycle_count,
                0,
                "cycles",
                "The observed transform graph contains a directed cycle.",
            )

        for partition in bag_partition.partition_by(
            ["topic", "frame_id", "child_frame_id"], maintain_order=True
        ):
            rows = sorted(partition.iter_rows(named=True), key=lambda row: row["timestamp_ns"])
            jumps = [
                _magnitude(
                    current["translation_x"] - previous["translation_x"],
                    current["translation_y"] - previous["translation_y"],
                    current["translation_z"] - previous["translation_z"],
                )
                for previous, current in zip(rows, rows[1:], strict=False)
            ]
            if not jumps:
                continue
            max_jump = max(jumps)
            path_length = sum(jumps)
            translation_speeds = [
                jump * 1_000_000_000 / (current["timestamp_ns"] - previous["timestamp_ns"])
                for jump, previous, current in zip(jumps, rows[:-1], rows[1:], strict=True)
                if current["timestamp_ns"] > previous["timestamp_ns"]
            ]
            pair = f"{rows[0]['frame_id']}->{rows[0]['child_frame_id']}"
            _metric(
                metrics,
                bag_id,
                "tf",
                pair,
                "translation_path_length",
                path_length,
                "m",
            )
            if translation_speeds:
                _metric(
                    metrics,
                    bag_id,
                    "tf",
                    pair,
                    "max_translation_speed",
                    max(translation_speeds),
                    "m/s",
                )
            _metric(
                metrics,
                bag_id,
                "tf",
                pair,
                "max_translation_jump",
                max_jump,
                "m",
                status="warn" if max_jump > config.tf_translation_jump_warn_m else "ok",
            )
            for index, jump in enumerate(jumps, start=1):
                if jump <= config.tf_translation_jump_warn_m:
                    continue
                timestamp = rows[index]["timestamp_ns"]
                _event(
                    events,
                    bag_id,
                    "tf",
                    pair,
                    timestamp,
                    timestamp,
                    "warn",
                    "translation_jump",
                    jump,
                    config.tf_translation_jump_warn_m,
                    "m",
                    "Consecutive transforms exceeded the translation jump threshold.",
                )


def _analyze_diagnostics(
    frame: pl.DataFrame,
    config: DomainAnalyticsConfig,
    metrics: list[dict[str, Any]],
    events: list[dict[str, Any]],
) -> None:
    for partition in frame.partition_by(["bag_id", "topic"], maintain_order=True):
        rows = sorted(partition.iter_rows(named=True), key=lambda row: row["timestamp_ns"])
        bag_id = rows[0]["bag_id"]
        topic = rows[0]["topic"]
        levels = Counter(row["level"] for row in rows)
        severity_count = levels[1] + levels[2] + levels[3]
        _metric(metrics, bag_id, "diagnostics", topic, "status_count", len(rows), "statuses")
        for level, name in (
            (0, "ok_count"),
            (1, "warn_count"),
            (2, "error_count"),
            (3, "stale_count"),
        ):
            status = (
                "error"
                if level in {2, 3} and levels[level]
                else "warn"
                if level == 1 and levels[level]
                else "ok"
            )
            _metric(
                metrics,
                bag_id,
                "diagnostics",
                topic,
                name,
                levels[level],
                "statuses",
                status=status,
            )
        _metric(
            metrics,
            bag_id,
            "diagnostics",
            topic,
            "non_ok_count",
            severity_count,
            "statuses",
            status="warn" if severity_count else "ok",
        )
        grouped: dict[tuple[str, int, str], list[tuple[int, float]]] = defaultdict(list)
        for row in rows:
            if row["level"] <= 0:
                continue
            grouped[(row["name"], row["level"], row["message"])].append(
                (row["timestamp_ns"], float(row["level"]))
            )
        for (name, level, message), samples in grouped.items():
            severity = "error" if level in {2, 3} else "warn"
            for start, end, _maximum, count in _group_samples(samples, config.event_merge_gap_ns):
                _event(
                    events,
                    bag_id,
                    "diagnostics",
                    topic,
                    start,
                    end,
                    severity,
                    "diagnostic_status",
                    level,
                    0,
                    "level",
                    f"{name}: {message or 'non-OK diagnostic'} ({count} records)",
                )


def _analyze_images(
    frame: pl.DataFrame,
    config: DomainAnalyticsConfig,
    metrics: list[dict[str, Any]],
    events: list[dict[str, Any]],
) -> None:
    for partition in frame.partition_by(["bag_id", "topic"], maintain_order=True):
        rows = sorted(partition.iter_rows(named=True), key=lambda row: row["timestamp_ns"])
        bag_id = rows[0]["bag_id"]
        topic = rows[0]["topic"]
        dimensions = {(row["width"], row["height"], row["encoding"]) for row in rows}
        duplicate_samples = [
            (current["timestamp_ns"], 1.0)
            for previous, current in zip(rows, rows[1:], strict=False)
            if current["content_hash"] == previous["content_hash"]
        ]
        intensities = [row["mean_intensity"] for row in rows if row["mean_intensity"] is not None]
        sharpness_values = [
            row["sharpness_score"] for row in rows if row["sharpness_score"] is not None
        ]
        depth_values = [row["mean_depth_m"] for row in rows if row["mean_depth_m"] is not None]
        valid_pixel_fractions = [
            row["valid_pixel_fraction"] for row in rows if row["valid_pixel_fraction"] is not None
        ]
        _metric(metrics, bag_id, "image", topic, "frame_count", len(rows), "frames")
        _metric(
            metrics,
            bag_id,
            "image",
            topic,
            "format_variant_count",
            len(dimensions),
            "variants",
            status="warn" if len(dimensions) > 1 else "ok",
        )
        _metric(
            metrics,
            bag_id,
            "image",
            topic,
            "duplicate_frame_count",
            len(duplicate_samples),
            "frames",
            status="warn" if duplicate_samples else "ok",
        )
        if intensities:
            mean_intensity = sum(intensities) / len(intensities)
            minimum_intensity = min(intensities)
            maximum_intensity = max(intensities)
            _metric(metrics, bag_id, "image", topic, "mean_intensity", mean_intensity, "level")
            _metric(
                metrics,
                bag_id,
                "image",
                topic,
                "minimum_intensity",
                minimum_intensity,
                "level",
                status="warn" if minimum_intensity < config.image_dark_warn_mean else "ok",
            )
            _metric(
                metrics,
                bag_id,
                "image",
                topic,
                "maximum_intensity",
                maximum_intensity,
                "level",
                status="warn" if maximum_intensity > config.image_bright_warn_mean else "ok",
            )
            dark_samples = [
                (row["timestamp_ns"], row["mean_intensity"])
                for row in rows
                if row["mean_intensity"] is not None
                and row["mean_intensity"] < config.image_dark_warn_mean
            ]
            for start, end, maximum_deficit, count in _group_samples(
                [
                    (timestamp, config.image_dark_warn_mean - value)
                    for timestamp, value in dark_samples
                ],
                config.event_merge_gap_ns,
            ):
                _event(
                    events,
                    bag_id,
                    "image",
                    topic,
                    start,
                    end,
                    "warn",
                    "dark_frames",
                    config.image_dark_warn_mean - maximum_deficit,
                    config.image_dark_warn_mean,
                    "mean intensity",
                    f"{count} frames were below the configured mean-intensity threshold.",
                )
            bright_samples = [
                (row["timestamp_ns"], row["mean_intensity"])
                for row in rows
                if row["mean_intensity"] is not None
                and row["mean_intensity"] > config.image_bright_warn_mean
            ]
            for start, end, maximum, count in _group_samples(
                bright_samples, config.event_merge_gap_ns
            ):
                _event(
                    events,
                    bag_id,
                    "image",
                    topic,
                    start,
                    end,
                    "warn",
                    "bright_frames",
                    maximum,
                    config.image_bright_warn_mean,
                    "mean intensity",
                    f"{count} frames exceeded the configured mean-intensity threshold.",
                )
        if sharpness_values:
            minimum_sharpness = min(sharpness_values)
            _metric(
                metrics,
                bag_id,
                "image",
                topic,
                "minimum_sharpness",
                minimum_sharpness,
                "score",
                status="warn" if minimum_sharpness < config.image_sharpness_warn else "ok",
            )
            blurry_samples = [
                (row["timestamp_ns"], config.image_sharpness_warn - row["sharpness_score"])
                for row in rows
                if row["sharpness_score"] is not None
                and row["sharpness_score"] < config.image_sharpness_warn
            ]
            for start, end, maximum_deficit, count in _group_samples(
                blurry_samples, config.event_merge_gap_ns
            ):
                _event(
                    events,
                    bag_id,
                    "image",
                    topic,
                    start,
                    end,
                    "warn",
                    "low_sharpness",
                    config.image_sharpness_warn - maximum_deficit,
                    config.image_sharpness_warn,
                    "score",
                    f"{count} frames were below the configured sharpness threshold.",
                )
        if depth_values:
            _metric(
                metrics,
                bag_id,
                "image",
                topic,
                "mean_depth",
                sum(depth_values) / len(depth_values),
                "m",
            )
        if valid_pixel_fractions:
            _metric(
                metrics,
                bag_id,
                "image",
                topic,
                "mean_valid_pixel_fraction",
                sum(valid_pixel_fractions) / len(valid_pixel_fractions),
                "ratio",
            )
        for start, end, _maximum, count in _group_samples(
            duplicate_samples, config.event_merge_gap_ns
        ):
            _event(
                events,
                bag_id,
                "image",
                topic,
                start,
                end,
                "warn",
                "duplicate_frames",
                count,
                0,
                "frames",
                f"{count} consecutive frames repeated the previous payload hash.",
            )


def _analyze_extraction_errors(
    frame: pl.DataFrame,
    metrics: list[dict[str, Any]],
    events: list[dict[str, Any]],
) -> None:
    for partition in frame.partition_by(["bag_id", "topic"], maintain_order=True):
        rows = sorted(partition.iter_rows(named=True), key=lambda row: row["timestamp_ns"])
        bag_id = rows[0]["bag_id"]
        topic = rows[0]["topic"]
        _metric(
            metrics,
            bag_id,
            "extraction",
            topic,
            "deserialization_error_count",
            len(rows),
            "messages",
            status="warn",
            detail="Supported payloads could not be deserialized; timing analysis still completed.",
        )
        _event(
            events,
            bag_id,
            "extraction",
            topic,
            rows[0]["timestamp_ns"],
            rows[-1]["timestamp_ns"],
            "warn",
            "payload_deserialization_failed",
            len(rows),
            0,
            "messages",
            f"{len(rows)} supported messages could not be deserialized. First error: "
            f"{rows[0]['error_type']}: {rows[0]['error_message']}",
        )


def build_domain_summary(
    enabled: bool,
    metrics: pl.DataFrame,
    events: pl.DataFrame,
    record_counts: dict[str, int],
) -> dict[str, Any]:
    payload_error_count = record_counts.get("extraction_errors", 0)
    normalized_record_counts = {
        name: record_counts.get(name, 0)
        for name in ("odometry", "imu", "commands", "transforms", "diagnostics", "images")
    }
    if not enabled:
        return {
            "enabled": False,
            "status": "disabled",
            "domains_present": [],
            "record_counts": normalized_record_counts,
            "payload_extraction_error_count": payload_error_count,
            "metric_count": 0,
            "event_count": 0,
            "warning_count": 0,
            "error_count": 0,
            "metric_warning_count": 0,
            "metric_error_count": 0,
            "metric_status_counts": {},
            "key_metrics": [],
        }
    domains = sorted(metrics.get_column("domain").unique().to_list()) if metrics.height else []
    event_severities = (
        Counter(events.get_column("severity").to_list()) if events.height else Counter()
    )
    metric_statuses = (
        Counter(metrics.get_column("status").to_list()) if metrics.height else Counter()
    )
    error_count = event_severities["error"]
    warning_count = event_severities["warn"]
    status = (
        "error"
        if error_count or metric_statuses["error"]
        else "warn"
        if warning_count or metric_statuses["warn"]
        else "ok"
        if metrics.height
        else "unavailable"
    )
    key_rows = _select_metric_rows(metrics, 30)
    key_metrics = [
        {
            "domain": row["domain"],
            "topic": row["topic"],
            "metric": row["metric"],
            "value": row["value"],
            "unit": row["unit"],
            "status": row["status"],
        }
        for row in key_rows
    ]
    return {
        "enabled": True,
        "status": status,
        "domains_present": domains,
        "record_counts": normalized_record_counts,
        "payload_extraction_error_count": payload_error_count,
        "metric_count": metrics.height,
        "event_count": events.height,
        "warning_count": warning_count,
        "error_count": error_count,
        "metric_warning_count": metric_statuses["warn"],
        "metric_error_count": metric_statuses["error"],
        "metric_status_counts": dict(metric_statuses),
        "key_metrics": key_metrics,
    }


def run_domain_analysis(
    output_dir: Path,
    config: DomainAnalyticsConfig,
) -> tuple[pl.DataFrame, pl.DataFrame, dict[str, Any]]:
    records = _read_records(output_dir)
    metric_rows: list[dict[str, Any]] = []
    event_rows: list[dict[str, Any]] = []
    if config.enabled:
        if records["odometry"].height:
            _analyze_odometry(records["odometry"], config, metric_rows, event_rows)
        if records["imu"].height:
            _analyze_imu(records["imu"], config, metric_rows, event_rows)
        if records["commands"].height:
            _analyze_commands(
                records["commands"], records["odometry"], config, metric_rows, event_rows
            )
        if records["transforms"].height:
            _analyze_transforms(records["transforms"], config, metric_rows, event_rows)
        if records["diagnostics"].height:
            _analyze_diagnostics(records["diagnostics"], config, metric_rows, event_rows)
        if records["images"].height:
            _analyze_images(records["images"], config, metric_rows, event_rows)
        if records["extraction_errors"].height:
            _analyze_extraction_errors(records["extraction_errors"], metric_rows, event_rows)

    metrics = (
        pl.DataFrame(metric_rows, schema=METRIC_SCHEMA).sort(["domain", "topic", "metric"])
        if metric_rows
        else _empty_frame(METRIC_SCHEMA)
    )
    events = (
        pl.DataFrame(event_rows, schema=EVENT_SCHEMA).sort(
            ["start_timestamp_ns", "domain", "topic", "event_type"]
        )
        if event_rows
        else _empty_frame(EVENT_SCHEMA)
    )
    metrics.write_parquet(output_dir / "domain_metrics.parquet", compression="zstd")
    events.write_parquet(output_dir / "anomaly_events.parquet", compression="zstd")
    record_counts = {name: frame.height for name, frame in records.items()}
    summary = build_domain_summary(config.enabled, metrics, events, record_counts)
    (output_dir / "domain_summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return metrics, events, summary


def _markdown_text(value: Any) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")


def render_bag_report(
    summary: dict[str, Any],
    metrics: pl.DataFrame,
    events: pl.DataFrame,
) -> str:
    domain = summary["domain_analysis"]
    lines = [
        "# Robot Bag Analysis",
        "",
        f"Bag: `{summary['bag_id']}`  ",
        f"Analyzed: `{summary['analyzed_at']}`  ",
        f"Messages: **{summary['message_count']}** across **{summary['topic_count']}** topics",
        "",
        "## Status",
        "",
        f"- Data health: **{summary['health_status']}**",
        f"- Domain analysis: **{domain['status']}**",
        f"- Domain metric checks: **{domain['metric_warning_count']} warnings**, "
        f"**{domain['metric_error_count']} errors**",
        f"- Domain events: **{domain['event_count']}** "
        f"({domain['warning_count']} warnings, {domain['error_count']} errors)",
        "",
        "## Data Health Findings",
        "",
    ]
    health_findings = summary.get("health_findings", [])
    if not health_findings:
        lines.append("No data-health warnings or errors were detected.")
    else:
        lines.extend(
            [
                "| Status | Source | Topic | Check | Detail |",
                "| --- | --- | --- | --- | --- |",
            ]
        )
        for finding in health_findings:
            lines.append(
                f"| {finding['status']} | {_markdown_text(finding['source'])} | "
                f"`{_markdown_text(finding['topic'])}` | "
                f"{_markdown_text(finding['check'])} | "
                f"{_markdown_text(finding['detail'])} |"
            )
    lines.extend(
        [
            "",
            "## Analysis Coverage",
            "",
            "- Normalized payload records: "
            + ", ".join(f"{name} **{count}**" for name, count in domain["record_counts"].items()),
            f"- Payload extraction errors: **{domain['payload_extraction_error_count']}**",
            "",
            "## Key Metrics",
            "",
        ]
    )
    if not metrics.height:
        lines.append("No supported payload records were available for domain metrics.")
    else:
        lines.extend(
            [
                "| Domain | Topic | Metric | Value | Unit | Status |",
                "| --- | --- | --- | ---: | --- | --- |",
            ]
        )
        for row in _select_metric_rows(metrics, 40):
            lines.append(
                f"| {_markdown_text(row['domain'])} | `{_markdown_text(row['topic'])}` | "
                f"{_markdown_text(row['metric'])} | {row['value']:.4g} | "
                f"{_markdown_text(row['unit'])} | {row['status']} |"
            )
    lines.extend(["", "## Significant Events", ""])
    if not events.height:
        lines.append("No domain anomaly events were detected.")
    else:
        lines.extend(
            [
                "| Severity | Domain | Topic | Event | Start (ns) | End (ns) | Detail |",
                "| --- | --- | --- | --- | ---: | ---: | --- |",
            ]
        )
        for row in _select_event_rows(events, 50):
            lines.append(
                f"| {row['severity']} | {_markdown_text(row['domain'])} | "
                f"`{_markdown_text(row['topic'])}` | {_markdown_text(row['event_type'])} | "
                f"{row['start_timestamp_ns']} | {row['end_timestamp_ns']} | "
                f"{_markdown_text(row['detail'])} |"
            )
    lines.extend(
        [
            "",
            "## Interpretation Boundary",
            "",
            "Metrics are deterministic features derived from supported ROS payloads. "
            "They are engineering triage signals, not safety certification or proof of root cause.",
            "",
        ]
    )
    return "\n".join(lines)
