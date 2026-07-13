from __future__ import annotations

import sqlite3
import tempfile
from collections import Counter
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from urllib.parse import quote

import pyarrow as pa
import pyarrow.parquet as pq
import yaml
from mcap.reader import make_reader as make_mcap_reader
from rosbags.highlevel import AnyReader
from rosbags.typesys import Stores, get_typestore

from isaac_telemetry.models import BagSource

DEFAULT_TYPESTORE = get_typestore(Stores.ROS2_HUMBLE)
MESSAGE_INDEX_SCHEMA = pa.schema(
    [
        ("bag_id", pa.string()),
        ("sequence", pa.int64()),
        ("topic", pa.string()),
        ("message_type", pa.string()),
        ("timestamp_ns", pa.int64()),
    ]
)


def _topic_metadata(
    name: str,
    message_type: str,
    serialization_format: str,
    offered_qos_profiles: str,
    message_count: int,
) -> dict[str, Any]:
    return {
        "topic_metadata": {
            "name": name,
            "type": message_type,
            "serialization_format": serialization_format or "cdr",
            "offered_qos_profiles": offered_qos_profiles or "",
        },
        "message_count": message_count,
    }


def _metadata_document(
    source_path: Path,
    storage_identifier: str,
    topics: list[dict[str, Any]],
    message_count: int,
    start_time_ns: int,
    end_time_ns: int,
) -> dict[str, Any]:
    duration_ns = max(0, end_time_ns - start_time_ns)
    file_info = {
        "path": source_path.name,
        "starting_time": {"nanoseconds_since_epoch": start_time_ns},
        "duration": {"nanoseconds": duration_ns},
        "message_count": message_count,
    }
    return {
        "rosbag2_bagfile_information": {
            "version": 5,
            "storage_identifier": storage_identifier,
            "duration": {"nanoseconds": duration_ns},
            "starting_time": {"nanoseconds_since_epoch": start_time_ns},
            "message_count": message_count,
            "topics_with_message_count": topics,
            "compression_format": "",
            "compression_mode": "",
            "relative_file_paths": [source_path.name],
            "files": [file_info],
        }
    }


def _sqlite_metadata(source_path: Path) -> dict[str, Any]:
    uri = f"file:{quote(str(source_path))}?mode=ro"
    with sqlite3.connect(uri, uri=True) as connection:
        topic_columns = {
            row[1] for row in connection.execute("PRAGMA table_info(topics)").fetchall()
        }
        required = {"id", "name", "type", "serialization_format"}
        if not required.issubset(topic_columns):
            raise ValueError(f"{source_path} is not a recognized ROS2 SQLite bag")

        select_columns = ["id", "name", "type", "serialization_format"]
        if "offered_qos_profiles" in topic_columns:
            select_columns.append("offered_qos_profiles")
        topic_rows = connection.execute(
            f"SELECT {', '.join(select_columns)} FROM topics ORDER BY id"
        ).fetchall()
        counts = dict(
            connection.execute(
                "SELECT topic_id, COUNT(*) FROM messages GROUP BY topic_id"
            ).fetchall()
        )
        message_count, start_time, end_time = connection.execute(
            "SELECT COUNT(*), COALESCE(MIN(timestamp), 0), "
            "COALESCE(MAX(timestamp), 0) FROM messages"
        ).fetchone()

    topics = []
    for row in topic_rows:
        topic_id, name, message_type, serialization_format, *rest = row
        topics.append(
            _topic_metadata(
                name=name,
                message_type=message_type,
                serialization_format=serialization_format,
                offered_qos_profiles=rest[0] if rest else "",
                message_count=int(counts.get(topic_id, 0)),
            )
        )
    return _metadata_document(
        source_path,
        "sqlite3",
        topics,
        int(message_count),
        int(start_time),
        int(end_time),
    )


def _mcap_metadata(source_path: Path) -> dict[str, Any]:
    with source_path.open("rb") as input_file:
        reader = make_mcap_reader(input_file)
        summary = reader.get_summary()

        if summary and summary.statistics:
            channels = summary.channels
            schemas = summary.schemas
            statistics = summary.statistics
            channel_counts = statistics.channel_message_counts
            message_count = statistics.message_count
            start_time = statistics.message_start_time
            end_time = statistics.message_end_time
        else:
            channels = {}
            schemas = {}
            channel_counts: Counter[int] = Counter()
            message_count = 0
            start_time = 0
            end_time = 0
            for schema, channel, message in reader.iter_messages():
                channels[channel.id] = channel
                if schema is not None:
                    schemas[schema.id] = schema
                channel_counts[channel.id] += 1
                message_count += 1
                start_time = (
                    message.log_time if message_count == 1 else min(start_time, message.log_time)
                )
                end_time = max(end_time, message.log_time)

    topics = []
    for channel_id, channel in sorted(channels.items(), key=lambda item: item[1].topic):
        schema = schemas.get(channel.schema_id)
        topics.append(
            _topic_metadata(
                name=channel.topic,
                message_type=schema.name if schema else "unknown",
                serialization_format=channel.message_encoding or "cdr",
                offered_qos_profiles=channel.metadata.get("offered_qos_profiles", ""),
                message_count=int(channel_counts.get(channel_id, 0)),
            )
        )
    return _metadata_document(
        source_path,
        "mcap",
        topics,
        int(message_count),
        int(start_time),
        int(end_time),
    )


@contextmanager
def _reader_path(source: BagSource) -> Iterator[Path]:
    if source.path.is_dir() or source.path.suffix.lower() == ".bag":
        yield source.path
        return

    if source.path.suffix.lower() not in {".db3", ".mcap"}:
        raise ValueError(f"Unsupported bag source: {source.path}")

    metadata = (
        _sqlite_metadata(source.path)
        if source.path.suffix.lower() == ".db3"
        else _mcap_metadata(source.path)
    )
    with tempfile.TemporaryDirectory(prefix="isaac-telemetry-reader-") as temp_dir:
        wrapper_dir = Path(temp_dir)
        wrapped_file = wrapper_dir / source.path.name
        try:
            wrapped_file.symlink_to(source.path)
        except OSError as exc:
            raise RuntimeError(
                "Standalone ROS2 files require symbolic-link support; "
                "provide the original bag directory instead"
            ) from exc
        (wrapper_dir / "metadata.yaml").write_text(
            yaml.safe_dump(metadata, sort_keys=False),
            encoding="utf-8",
        )
        yield wrapper_dir


@contextmanager
def open_bag(source: BagSource) -> Iterator[AnyReader]:
    """Open any supported bag source, synthesizing ROS2 metadata when necessary."""
    with _reader_path(source) as reader_path:
        typestore = None if source.format == "rosbag1" else DEFAULT_TYPESTORE
        with AnyReader([reader_path], default_typestore=typestore) as reader:
            yield reader


def _write_batch(writer: pq.ParquetWriter, rows: list[dict[str, Any]]) -> None:
    writer.write_table(pa.Table.from_pylist(rows, schema=MESSAGE_INDEX_SCHEMA))


def scan_bag(source: BagSource, output_dir: Path, batch_size: int) -> dict[str, Any]:
    """Scan a bag once, streaming its message index and topic manifest to Parquet."""
    output_dir.mkdir(parents=True, exist_ok=True)
    index_path = output_dir / "message_index.parquet"
    manifest_path = output_dir / "topic_manifest.parquet"
    topic_counts: Counter[tuple[str, str]] = Counter()
    topic_bounds: dict[tuple[str, str], list[int]] = {}
    rows: list[dict[str, Any]] = []
    message_count = 0
    writer = pq.ParquetWriter(index_path, MESSAGE_INDEX_SCHEMA, compression="zstd")

    try:
        with open_bag(source) as reader:
            for sequence, (connection, timestamp, _rawdata) in enumerate(reader.messages()):
                key = (connection.topic, connection.msgtype)
                topic_counts[key] += 1
                if key not in topic_bounds:
                    topic_bounds[key] = [timestamp, timestamp]
                else:
                    topic_bounds[key][0] = min(topic_bounds[key][0], timestamp)
                    topic_bounds[key][1] = max(topic_bounds[key][1], timestamp)
                rows.append(
                    {
                        "bag_id": source.bag_id,
                        "sequence": sequence,
                        "topic": connection.topic,
                        "message_type": connection.msgtype,
                        "timestamp_ns": timestamp,
                    }
                )
                message_count += 1
                if len(rows) >= batch_size:
                    _write_batch(writer, rows)
                    rows.clear()
            if rows:
                _write_batch(writer, rows)
    finally:
        writer.close()

    manifest_rows = []
    for (topic, message_type), count in sorted(topic_counts.items()):
        first_timestamp, last_timestamp = topic_bounds[(topic, message_type)]
        manifest_rows.append(
            {
                "bag_id": source.bag_id,
                "topic": topic,
                "message_type": message_type,
                "message_count": count,
                "first_timestamp_ns": first_timestamp,
                "last_timestamp_ns": last_timestamp,
            }
        )
    manifest_schema = pa.schema(
        [
            ("bag_id", pa.string()),
            ("topic", pa.string()),
            ("message_type", pa.string()),
            ("message_count", pa.int64()),
            ("first_timestamp_ns", pa.int64()),
            ("last_timestamp_ns", pa.int64()),
        ]
    )
    pq.write_table(
        pa.Table.from_pylist(manifest_rows, schema=manifest_schema),
        manifest_path,
        compression="zstd",
    )
    return {"message_count": message_count, "topic_count": len(manifest_rows)}
