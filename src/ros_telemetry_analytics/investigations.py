"""Versioned offline investigations. Generated evidence stays separate from annotations."""

from __future__ import annotations

import base64
import hashlib
import json
import math
import os
import struct
import time
import uuid
import zlib
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl
import yaml

from ros_telemetry_analytics.config import load_pipeline_config
from ros_telemetry_analytics.discovery import discover_bags
from ros_telemetry_analytics.domain import _image_statistics
from ros_telemetry_analytics.pipeline import run_pipeline
from ros_telemetry_analytics.reader import open_bag

MANIFEST = "configs/investigations.yaml"
# Only these numeric fields can be requested or rendered as evidence.
FIELDS = {
    "images": {
        "mean_intensity": "0–255",
        "sharpness_score": "score",
        "valid_pixel_fraction": "ratio",
        "mean_depth_m": "m",
    },
    "laser_scans": {"valid_range_fraction": "ratio", "mean_valid_range": "m"},
    "odometry": {"linear_x": "m/s", "linear_y": "m/s", "angular_z": "rad/s"},
    "commands": {"linear_x": "m/s", "linear_y": "m/s", "angular_z": "rad/s"},
    "imu": {"angular_velocity_z": "rad/s", "linear_acceleration_x": "m/s²"},
}


def clean(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: clean(v) for k, v in value.items()}
    if isinstance(value, list):
        return [clean(v) for v in value]
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_text(json.dumps(clean(value), indent=2, allow_nan=False) + "\n")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


@lru_cache(maxsize=16)
def checked_digest(path: str, size: int, mtime_ns: int, ctime_ns: int, inode: int) -> str:
    # Stat identity invalidates the cache, including edits that restore mtime.
    return sha256(Path(path))


def specs(root: Path) -> dict:
    return yaml.safe_load((root / MANIFEST).read_text())["datasets"]


def recipe_signature(root: Path, spec: dict) -> str:
    digest = hashlib.sha256(json.dumps(spec, sort_keys=True).encode())
    digest.update((root / spec["profile"]).read_bytes())
    # Include the analysis implementation, so old bundles never masquerade as new output.
    for path in sorted(Path(__file__).parent.glob("*.py")):
        digest.update(path.name.encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def rows(path: Path) -> list[dict]:
    return pl.read_parquet(path).to_dicts()


def png_preview(message: Any) -> str | None:
    """Bounded RGB/grayscale PNG, honoring row stride and channel order."""
    encoding = str(message.encoding).lower()
    channels = {"mono8": 1, "8uc1": 1, "rgb8": 3, "bgr8": 3, "rgba8": 4, "bgra8": 4}.get(encoding)
    pixel_bytes = {"mono16": 2, "16uc1": 2, "32fc1": 4}.get(encoding, channels)
    if pixel_bytes is None:
        return None
    h, w, step = int(message.height), int(message.width), int(message.step)
    if min(h, w) <= 0 or step < w * pixel_bytes:
        return None
    data = np.asarray(message.data, dtype=np.uint8)
    if data.size < h * step:
        return None
    active = np.ascontiguousarray(data[: h * step].reshape(h, step)[:, : w * pixel_bytes])
    if encoding in {"mono16", "16uc1", "32fc1"}:
        byte_order = ">" if int(getattr(message, "is_bigendian", 0)) else "<"
        dtype = byte_order + ("f4" if encoding == "32fc1" else "u2")
        values = np.frombuffer(active, dtype=dtype).reshape(h, w).astype(float)
        if encoding == "mono16":
            values /= 257
        else:
            # ROS depth: uint16 millimeters or float32 meters. Fixed 0–5 m scale.
            values *= 255 / (5 if encoding == "32fc1" else 5000)
        pixels = np.nan_to_num(values, nan=0, posinf=0, neginf=0).clip(0, 255).astype(np.uint8)
        pixels = pixels[:, :, None]
        channels = 1
    else:
        pixels = active.reshape(h, w, channels)
    stride = max(1, math.ceil(max(h, w) / 256))
    pixels = pixels[::stride, ::stride, : min(channels, 3)]
    if encoding in {"bgr8", "bgra8"}:
        pixels = pixels[:, :, ::-1]
    ph, pw, pc = pixels.shape
    raw = b"".join(b"\x00" + row.tobytes() for row in pixels)

    def chunk(kind: bytes, payload: bytes) -> bytes:
        return (
            struct.pack(">I", len(payload))
            + kind
            + payload
            + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF)
        )

    png = (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", pw, ph, 8, 0 if pc == 1 else 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )
    return "data:image/png;base64," + base64.b64encode(png).decode()


def previews(
    source: Any, directory: Path, origin: int, focus_times: tuple[float, ...] = ()
) -> list[dict]:
    selected: dict[int, dict] = {}
    for domain, metric in (("images", "sharpness_score"), ("laser_scans", "valid_range_fraction")):
        frame = pl.read_parquet(directory / f"domain_records/{domain}.parquet")
        for group in frame.partition_by("topic", maintain_order=True):
            metric = "sharpness_score" if domain == "images" else "valid_range_fraction"
            ordered = group.sort("timestamp_ns")
            # Actual evidence around the minimum, plus temporal controls.
            valid = ordered.filter(pl.col(metric).is_not_null() & pl.col(metric).is_finite())
            if not valid.height and domain == "images":
                valid = ordered.filter(pl.col("valid_pixel_fraction").is_not_null())
                metric = "valid_pixel_fraction"
            if not valid.height:
                continue
            worst = valid.sort(metric).row(0, named=True)
            nearest = (
                ordered.with_columns(
                    (pl.col("timestamp_ns") - worst["timestamp_ns"]).abs().alias("distance")
                )
                .sort("distance")
                .head(1)
                .row(0, named=True)
            )
            targets = [
                ordered.row(i, named=True) for i in {0, ordered.height // 2, ordered.height - 1}
            ]
            targets.append(nearest)
            for delta in (-1_000_000_000, 1_000_000_000):
                target = (
                    ordered.with_columns(
                        (pl.col("timestamp_ns") - worst["timestamp_ns"] - delta).abs().alias("d")
                    )
                    .sort("d")
                    .row(0, named=True)
                )
                targets.append(target)
            for focus in focus_times:
                for delta in (-1, 0, 1):
                    stamp = origin + round((focus + delta) * 1e9)
                    targets.append(
                        ordered.with_columns(
                            (pl.col("timestamp_ns") - stamp).abs().alias("distance")
                        )
                        .sort("distance")
                        .row(0, named=True)
                    )
            for row in targets:
                selected[row["sequence"]] = {"domain": domain, "record": row}
    result = []
    if not selected:
        return result
    with open_bag(source) as reader:
        for sequence, (connection, timestamp, raw) in enumerate(reader.messages()):
            if sequence > max(selected):
                break
            if sequence not in selected:
                continue
            selection = selected[sequence]
            record = selection["record"]
            item = {
                "id": str(sequence),
                "topic": connection.topic,
                "frame_id": record["frame_id"],
                "timestamp_ns": str(timestamp),
                "t": (timestamp - origin) / 1e9,
                "kind": selection["domain"],
            }
            try:
                message = reader.deserialize(raw, connection.msgtype)
                if selection["domain"] == "images":
                    item["image"] = png_preview(message)
                    item["encoding"] = message.encoding
                    item["preview_scale"] = (
                        "Depth: black 0 m/invalid, white ≥5 m"
                        if message.encoding.lower() in {"16uc1", "32fc1"}
                        else "8-bit display; mono16 divided by 257"
                    )
                    statistics = _image_statistics(message)
                    item["verified"] = statistics[-1] == record["content_hash"]
                    item["mean_intensity"] = statistics[1]
                    item["sharpness_score"] = statistics[2]
                    item["mean_depth_m"] = statistics[3]
                    item["valid_pixel_fraction"] = statistics[4]
                    # Compare every extracted feature, in addition to payload identity.
                    for name, value in zip(
                        (
                            "mean_intensity",
                            "sharpness_score",
                            "mean_depth_m",
                            "valid_pixel_fraction",
                        ),
                        statistics[1:5],
                        strict=True,
                    ):
                        item["verified"] &= value == record[name]
                    if item["image"] is None:
                        item["detail"] = "Preview encoding unsupported; scalar analysis retained."
                else:
                    ranges = np.asarray(message.ranges)
                    valid = (
                        np.isfinite(ranges)
                        & (ranges >= message.range_min)
                        & (ranges <= message.range_max)
                    )
                    item["verified"] = int(valid.sum()) == record["valid_range_count"]
                    item["valid_range_fraction"] = float(valid.mean()) if ranges.size else 0
                    stride = max(1, math.ceil(len(ranges) / 360))
                    item["points"] = [
                        [
                            float(
                                ranges[i]
                                * math.cos(message.angle_min + i * message.angle_increment)
                            ),
                            float(
                                ranges[i]
                                * math.sin(message.angle_min + i * message.angle_increment)
                            ),
                        ]
                        for i in range(0, len(ranges), stride)
                        if valid[i]
                    ]
                    item["range_max_m"] = float(message.range_max)
                    item["sample_stride"] = stride
            except Exception as exc:
                item["verified"] = False
                item["detail"] = f"Preview failed: {type(exc).__name__}: {exc}"
            result.append(item)
    return result


def temporal_profile(directory: Path, references: list[str]) -> list[dict]:
    index = pl.read_parquet(directory / "message_index.parquet")
    result = []
    for frame in index.partition_by("topic", maintain_order=True):
        stamps = frame.sort("sequence")["timestamp_ns"].to_numpy()
        differences = np.diff(stamps)
        positive = differences[differences > 0]
        result.append(
            {
                "topic": frame["topic"][0],
                "message_count": len(stamps),
                "reference_context": frame["topic"][0] in references,
                "repeated_log_stamps": int((differences == 0).sum()),
                "backward_log_stamps": int((differences < 0).sum()),
                "median_interval_ms": float(np.median(positive) / 1e6) if positive.size else None,
                "max_interval_ms": float(positive.max() / 1e6) if positive.size else None,
            }
        )
    return result


def header_profile(directory: Path, image_frame_semantics: str = "coordinate_frame") -> list[dict]:
    output = []
    for path in sorted((directory / "domain_records").glob("*.parquet")):
        frame = pl.read_parquet(path)
        if not frame.height or "source_timestamp_ns" not in frame.columns:
            continue
        keys = [key for key in ("topic", "frame_id", "child_frame_id") if key in frame.columns]
        if path.stem == "images" and image_frame_semantics == "exposure_ns":
            keys = ["topic"]
        for group in frame.partition_by(keys, maintain_order=True):
            stamps = group.sort("sequence")["source_timestamp_ns"].to_list()
            pairs = [
                (a, b)
                for a, b in zip(stamps, stamps[1:], strict=False)
                if a is not None and b is not None
            ]
            output.append(
                {
                    "domain": path.stem,
                    **{key: group[key][0] for key in keys},
                    "records": group.height,
                    "missing": sum(x is None for x in stamps),
                    "zero": sum(x == 0 for x in stamps),
                    "repeated": sum(a == b for a, b in pairs),
                    "backward": sum(b < a for a, b in pairs),
                }
            )
    return output


def build_bundle(root: Path, dataset_id: str, output: Path) -> dict:
    spec = specs(root)[dataset_id]
    source_path = root / spec["input"]
    if not source_path.exists():
        return {"dataset_id": dataset_id, "name": spec["name"], "status": "not_installed"}
    started = time.monotonic()
    recipe = recipe_signature(root, spec)
    (source,) = discover_bags([source_path])
    digest = sha256(source.path)
    if spec.get("recorded_sha256") and spec["recorded_sha256"] != digest:
        raise ValueError(f"Recorded checksum mismatch for {dataset_id}")
    if spec.get("bytes") and spec["bytes"] != source.size_bytes:
        raise ValueError(f"Expected size mismatch for {dataset_id}")
    analysis_id = uuid.uuid4().hex
    destination = output / dataset_id / analysis_id
    destination.mkdir(parents=True, exist_ok=False)
    config = load_pipeline_config(
        root / spec["profile"], input_roots=[source.path], output_root=destination / "analysis"
    )
    result = run_pipeline(config, force=True)
    if result["failed_count"] or result["discovered_count"] != 1:
        raise ValueError(f"Analysis failed: {result['results']}")
    directory = Path(result["results"][0]["output_path"])
    index = pl.read_parquet(directory / "message_index.parquet")
    origin = int(index["timestamp_ns"].min())
    end = int(index["timestamp_ns"].max())
    coverage = rows(directory / "analysis_coverage.parquet")
    preview = previews(source, directory, origin, tuple(spec.get("preview_focus_s", [])))
    # Ensure results correspond to a stable source snapshot.
    (current,) = discover_bags([source_path])
    if current.fingerprint != source.fingerprint:
        raise ValueError("Source changed during analysis; no bundle published")
    if recipe != recipe_signature(root, spec):
        raise ValueError("Analysis code changed during preparation; rerun this recording")
    extraction_errors = sum(row["extraction_error_count"] for row in coverage)
    if sum(row["message_count"] for row in coverage) != index.height:
        raise ValueError("Coverage message counts do not reconcile with the message index")
    metadata = {
        "schema_version": 1,
        "dataset_id": dataset_id,
        "name": spec["name"],
        "analysis_id": analysis_id,
        "role": spec["role"],
        "purpose": spec["purpose"],
        "source": spec["source"],
        "license": spec["license"],
        "source_input": spec["input"],
        "source_bytes": source.size_bytes,
        "source_sha256": digest,
        "source_fingerprint": source.fingerprint,
        "integrity": "local_baseline_match" if spec.get("recorded_sha256") else "local_digest_only",
        "recipe_signature": recipe,
        "created_at": datetime.now(UTC).isoformat(),
        "status": "limited"
        if extraction_errors or any(not p["verified"] for p in preview)
        else "ready",
        "analysis_path": str(directory.relative_to(destination)),
        "origin_ns": str(origin),
        "end_ns": str(end),
        "duration_s": (end - origin) / 1e9,
        "message_count": index.height,
        "coverage": coverage,
        "reference_topics": spec.get("reference_topics", []),
        "temporal_profile": temporal_profile(directory, spec.get("reference_topics", [])),
        "image_frame_semantics": spec.get("image_frame_semantics", "coordinate_frame"),
        "header_profile": header_profile(
            directory, spec.get("image_frame_semantics", "coordinate_frame")
        ),
        "topic_health": rows(directory / "topic_health.parquet"),
        "relationships": rows(directory / "relationship_health.parquet"),
        "preview_count": len(preview),
        "verified_previews": sum(p["verified"] for p in preview),
        "extraction_errors": extraction_errors,
        "elapsed_s": time.monotonic() - started,
        "interpretation": (
            "Recorded observations and configured warnings; not confirmed physical failures."
        ),
    }
    write_json(destination / "previews.json", preview)
    write_json(destination / "metadata.json", metadata)
    # A dataset pointer publishes only after all of its artifacts are available.
    write_json(output / dataset_id / "latest.json", {"analysis_id": analysis_id})
    return metadata


def load_bundle(
    root: Path, output: Path, dataset_id: str, analysis_id: str | None = None
) -> tuple[Path, dict]:
    spec = specs(root).get(dataset_id)
    if spec is None:
        raise KeyError("Unknown investigation dataset")
    pointer = json.loads((output / dataset_id / "latest.json").read_text())
    current_id = pointer["analysis_id"]
    if analysis_id is not None and analysis_id != current_id:
        raise ValueError("Analysis changed; reopen the recording")
    if len(current_id) != 32 or any(c not in "0123456789abcdef" for c in current_id):
        raise ValueError("Invalid analysis identity")
    directory = output / dataset_id / current_id
    metadata = json.loads((directory / "metadata.json").read_text())
    if metadata.get("dataset_id") != dataset_id or metadata.get("analysis_id") != current_id:
        raise ValueError("Evidence identity mismatch")
    analysis = (directory / metadata["analysis_path"]).resolve()
    if not analysis.is_relative_to(directory.resolve()):
        raise ValueError("Invalid evidence location")
    sources = discover_bags([root / spec["input"]])
    if (
        len(sources) != 1
        or metadata["source_fingerprint"] != sources[0].fingerprint
        or metadata["recipe_signature"] != recipe_signature(root, spec)
    ):
        raise ValueError("Evidence is stale; prepare this recording again")
    stat = sources[0].path.stat()
    if (
        checked_digest(
            str(sources[0].path), stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns, stat.st_ino
        )
        != metadata["source_sha256"]
    ):
        raise ValueError("Source bytes changed; prepare this recording again")
    return directory, metadata


def collection(root: Path, output: Path) -> dict:
    records = []
    for dataset_id, spec in specs(root).items():
        row = {
            "dataset_id": dataset_id,
            "name": spec["name"],
            "role": spec["role"],
            "purpose": spec["purpose"],
        }
        try:
            _, metadata = load_bundle(root, output, dataset_id)
            row.update(
                {
                    key: metadata[key]
                    for key in ("status", "analysis_id", "duration_s", "integrity", "preview_count")
                }
            )
        except FileNotFoundError:
            row["status"] = "not_analyzed" if (root / spec["input"]).exists() else "not_installed"
        except (OSError, ValueError, KeyError):
            row["status"] = "stale"
        records.append(row)
    return {"datasets": records}


def event_records(directory: Path, metadata: dict) -> list[dict]:
    analysis = directory / metadata["analysis_path"]
    events = rows(analysis / "anomaly_events.parquet")
    index = pl.read_parquet(analysis / "message_index.parquet")
    for health in metadata.get("topic_health", []):
        threshold = health["gap_threshold_s"]
        if threshold is None or health["gap_event_count"] == 0:
            continue
        stamps = index.filter(pl.col("topic") == health["topic"])["timestamp_ns"].sort().to_list()
        for a, b in zip(stamps, stamps[1:], strict=False):
            if (b - a) / 1e9 > threshold:
                reference = health["topic"] in metadata["reference_topics"]
                events.append(
                    {
                        "topic": health["topic"],
                        "domain": "timing",
                        "severity": "warn",
                        "start_timestamp_ns": a,
                        "end_timestamp_ns": b,
                        "event_type": "reference_gap" if reference else "recorded_gap",
                        "observed_value": (b - a) / 1e6,
                        "threshold": threshold * 1000,
                        "unit": "ms",
                        "detail": "Recorded interval exceeds configured rate-based threshold. "
                        + (
                            "Reference coverage limitation."
                            if reference
                            else "Cause not established."
                        ),
                    }
                )
    events.sort(key=lambda e: e["start_timestamp_ns"])
    for event in events:
        for key in ("start_timestamp_ns", "end_timestamp_ns"):
            event[key] = str(event[key])
        event["start_s"] = (int(event["start_timestamp_ns"]) - int(metadata["origin_ns"])) / 1e9
        event["end_s"] = (int(event["end_timestamp_ns"]) - int(metadata["origin_ns"])) / 1e9
    return events


def public_metadata(directory: Path, metadata: dict) -> dict:
    analysis = directory / metadata["analysis_path"]
    events = event_records(directory, metadata)
    annotations_path = directory / "annotations.json"
    annotations = json.loads(annotations_path.read_text()) if annotations_path.exists() else {}
    cases = (
        annotations.get("cases", [])
        if annotations.get("analysis_id") == metadata["analysis_id"]
        else []
    )
    metrics = rows(analysis / "domain_metrics.parquet")
    metadata = dict(metadata)
    metadata["topic_health"] = [
        {k: str(v) if k.endswith("timestamp_ns") and v is not None else v for k, v in row.items()}
        for row in metadata.get("topic_health", [])
    ]
    return {
        **{k: v for k, v in metadata.items() if k not in {"analysis_path", "source_input"}},
        "events": events[:200],
        "event_count": len(events),
        "events_truncated": len(events) > 200,
        "metrics": metrics[:200],
        "metric_count": len(metrics),
        "cases": cases,
    }


def bounded_points(
    times: list[int],
    values: list[float | None],
    origin: int,
    start_s: float,
    end_s: float,
    limit: int = 240,
) -> list[dict]:
    """Time buckets preserve extrema and empty buckets; never imply raw point fidelity."""
    if not times:
        return []
    width = max((end_s - start_s) / limit, 1e-9)
    bins: dict[int, list[float]] = {}
    for stamp, value in zip(times, values, strict=True):
        t = (stamp - origin) / 1e9
        if start_s <= t <= end_s and value is not None and math.isfinite(value):
            bucket = min(limit - 1, int((t - start_s) / width))
            bins.setdefault(bucket, []).append(float(value))
    return [
        {
            "t": start_s + i * width,
            "end_s": start_s + (i + 1) * width,
            "min": min(bins[i]) if i in bins else None,
            "max": max(bins[i]) if i in bins else None,
            "value": sum(bins[i]) / len(bins[i]) if i in bins else None,
            "count": len(bins.get(i, [])),
        }
        for i in range(limit)
    ]


def interval(
    directory: Path, metadata: dict, start_s: float, end_s: float, topic: str | None = None
) -> dict:
    duration = metadata["duration_s"]
    if not (
        math.isfinite(start_s)
        and math.isfinite(end_s)
        and 0 <= start_s < end_s
        and start_s <= duration
        and end_s <= duration + 0.001
    ):
        raise ValueError("Interval must be inside this recording")
    origin = int(metadata["origin_ns"])
    lo, hi = origin + round(start_s * 1e9), origin + round(end_s * 1e9)
    analysis = directory / metadata["analysis_path"]
    topics = {row["topic"] for row in metadata["coverage"]}
    if topic is not None and topic not in topics:
        raise ValueError("Unknown topic")
    series = []
    for domain, fields in FIELDS.items():
        frame = pl.read_parquet(analysis / f"domain_records/{domain}.parquet")
        frame = frame.filter(pl.col("timestamp_ns").is_between(lo, hi))
        if topic is not None:
            frame = frame.filter(pl.col("topic") == topic)
        exposure = domain == "images" and metadata.get("image_frame_semantics") == "exposure_ns"
        keys = ["topic"] if exposure else ["topic", "frame_id"]
        if domain == "odometry":
            keys.append("child_frame_id")
        for group in frame.partition_by(keys, maintain_order=True):
            group = group.sort("timestamp_ns")
            for field, unit in fields.items():
                if group[field].drop_nulls().len() == 0:
                    continue
                series.append(
                    {
                        "topic": group["topic"][0],
                        "frame": "header.frame_id is exposure (ns)"
                        if exposure
                        else (
                            group["child_frame_id"][0]
                            if domain == "odometry"
                            else group["frame_id"][0]
                        ),
                        "field": field,
                        "unit": unit,
                        "domain": domain,
                        "points": bounded_points(
                            group["timestamp_ns"].to_list(),
                            group[field].to_list(),
                            origin,
                            start_s,
                            end_s,
                        ),
                    }
                )
    index = pl.read_parquet(analysis / "message_index.parquet")
    if topic is not None:
        index = index.filter(pl.col("topic") == topic)
    for group in index.partition_by("topic", maintain_order=True):
        times = group.sort("timestamp_ns")["timestamp_ns"].to_list()
        values = [(b - a) / 1e6 for a, b in zip(times, times[1:], strict=False)]
        series.append(
            {
                "topic": group["topic"][0],
                "frame": "recorded receive time",
                "field": "inter_message_gap_ms",
                "unit": "ms",
                "domain": "timing",
                "points": bounded_points(times[1:], values, origin, start_s, end_s),
            }
        )
    events = [
        e
        for e in event_records(directory, metadata)
        if e["end_s"] >= start_s
        and e["start_s"] <= end_s
        and (topic is None or e["topic"] == topic)
    ]
    preview = json.loads((directory / "previews.json").read_text())
    return {
        "analysis_id": metadata["analysis_id"],
        "start_s": start_s,
        "end_s": end_s,
        "events": events[:200],
        "event_count": len(events),
        "events_truncated": len(events) > 200,
        "series": clean(series[:60]),
        "series_count": len(series),
        "series_truncated": len(series) > 60,
        "sampling": "240 time buckets per series; min/max and mean; empty buckets are gaps",
        "previews": [
            p
            for p in preview
            if start_s <= p["t"] <= end_s and (topic is None or p["topic"] == topic)
        ],
        "preview_policy": (
            "Fixed source samples around feature minima and temporal controls; not every frame."
        ),
    }
