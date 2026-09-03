from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

EXPECTED_TOPICS = {"/camera/image_raw", "/imu/data", "/odom", "/diagnostics"}
ROOT = Path(__file__).resolve().parents[2]
METRIC_VALIDATOR = Draft202012Validator(
    json.loads((ROOT / "schemas/telemetry-metric-v1.schema.json").read_text(encoding="utf-8"))
)


class ProjectionStore:
    def __init__(self, database_path: Path, output_root: Path) -> None:
        self.database_path = database_path
        self.output_root = output_root
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS messages (
                    stream_kind TEXT NOT NULL,
                    message_id TEXT NOT NULL,
                    revision INTEGER NOT NULL,
                    run_id TEXT NOT NULL,
                    stream_timestamp_ms INTEGER NOT NULL,
                    payload_json TEXT NOT NULL,
                    PRIMARY KEY (stream_kind, message_id, revision)
                );
                CREATE INDEX IF NOT EXISTS messages_run_time
                    ON messages(run_id, stream_timestamp_ms);
                CREATE TABLE IF NOT EXISTS current_messages (
                    stream_kind TEXT NOT NULL,
                    message_id TEXT NOT NULL,
                    revision INTEGER NOT NULL,
                    run_id TEXT NOT NULL,
                    stream_timestamp_ms INTEGER NOT NULL,
                    payload_json TEXT NOT NULL,
                    PRIMARY KEY (stream_kind, message_id)
                );
                CREATE TABLE IF NOT EXISTS current_entities (
                    stream_kind TEXT NOT NULL,
                    logical_key TEXT NOT NULL,
                    message_id TEXT NOT NULL,
                    revision INTEGER NOT NULL,
                    run_id TEXT NOT NULL,
                    stream_timestamp_ms INTEGER NOT NULL,
                    arrival_order INTEGER NOT NULL DEFAULT 0,
                    payload_json TEXT NOT NULL,
                    PRIMARY KEY (stream_kind, logical_key)
                );
                CREATE INDEX IF NOT EXISTS current_entities_run_time
                    ON current_entities(run_id, stream_timestamp_ms);
                CREATE TABLE IF NOT EXISTS consumer_offsets (
                    kafka_topic TEXT NOT NULL,
                    kafka_partition INTEGER NOT NULL,
                    next_offset INTEGER NOT NULL,
                    updated_at_ms INTEGER NOT NULL,
                    PRIMARY KEY (kafka_topic, kafka_partition)
                );
                CREATE TABLE IF NOT EXISTS completed_runs (
                    run_id TEXT PRIMARY KEY,
                    state TEXT NOT NULL,
                    verified_at_ms INTEGER NOT NULL,
                    manifest_json TEXT NOT NULL
                );
                """
            )
            columns = {
                str(row["name"])
                for row in connection.execute("PRAGMA table_info(current_entities)").fetchall()
            }
            if "arrival_order" not in columns:
                connection.execute(
                    "ALTER TABLE current_entities "
                    "ADD COLUMN arrival_order INTEGER NOT NULL DEFAULT 0"
                )

    def project(
        self,
        *,
        stream_kind: str,
        payload: dict[str, Any],
        kafka_topic: str,
        kafka_partition: int,
        kafka_offset: int,
    ) -> bool:
        if stream_kind not in {"metric", "anomaly"}:
            raise ValueError(f"Unsupported stream kind: {stream_kind}")
        id_field = "metric_id" if stream_kind == "metric" else "anomaly_id"
        message_id = str(payload[id_field])
        revision = int(payload["revision"])
        run_id = str(payload["run_id"])
        timestamp = int(payload.get("stream_timestamp_ms", payload.get("detected_stream_ms", 0)))
        logical_key = self._logical_key(stream_kind, payload)
        is_run_status = stream_kind == "metric" and payload.get("metric_type") == "run_status"
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        with self._lock, self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT OR IGNORE INTO messages
                    (stream_kind, message_id, revision, run_id, stream_timestamp_ms, payload_json)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (stream_kind, message_id, revision, run_id, timestamp, encoded),
            )
            message_row = connection.execute(
                """
                SELECT rowid FROM messages
                WHERE stream_kind = ? AND message_id = ? AND revision = ?
                """,
                (stream_kind, message_id, revision),
            ).fetchone()
            arrival_order = int(message_row["rowid"])
            connection.execute(
                """
                INSERT INTO current_entities
                    (stream_kind, logical_key, message_id, revision, run_id,
                     stream_timestamp_ms, arrival_order, payload_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(stream_kind, logical_key) DO UPDATE SET
                    message_id = excluded.message_id,
                    revision = excluded.revision,
                    run_id = excluded.run_id,
                    stream_timestamp_ms = excluded.stream_timestamp_ms,
                    arrival_order = excluded.arrival_order,
                    payload_json = excluded.payload_json
                WHERE excluded.stream_timestamp_ms > current_entities.stream_timestamp_ms
                   OR (excluded.stream_timestamp_ms = current_entities.stream_timestamp_ms
                       AND ((? = 1 AND excluded.arrival_order >= current_entities.arrival_order)
                            OR (? = 0 AND excluded.revision >= current_entities.revision)))
                """,
                (
                    stream_kind,
                    logical_key,
                    message_id,
                    revision,
                    run_id,
                    timestamp,
                    arrival_order,
                    encoded,
                    int(is_run_status),
                    int(is_run_status),
                ),
            )
            connection.execute(
                """
                INSERT INTO consumer_offsets
                    (kafka_topic, kafka_partition, next_offset, updated_at_ms)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(kafka_topic, kafka_partition) DO UPDATE SET
                    next_offset = MAX(consumer_offsets.next_offset, excluded.next_offset),
                    updated_at_ms = excluded.updated_at_ms
                """,
                (kafka_topic, kafka_partition, kafka_offset + 1, int(time.time() * 1_000)),
            )
            self._prune(connection)
            return cursor.rowcount > 0

    @staticmethod
    def _logical_key(stream_kind: str, payload: dict[str, Any]) -> str:
        if stream_kind == "anomaly":
            return str(payload["anomaly_id"])
        lifecycle_status = (
            payload.get("payload", {}).get("status")
            if payload.get("metric_type") == "run_status"
            else None
        )
        values = (
            payload.get("run_id"),
            payload.get("robot_id"),
            payload.get("topic"),
            payload.get("metric_type"),
            payload.get("window_start_ms"),
            payload.get("window_end_ms"),
            lifecycle_status,
        )
        return hashlib.sha256(
            "\x1f".join("null" if item is None else str(item) for item in values).encode()
        ).hexdigest()

    @staticmethod
    def _prune(connection: sqlite3.Connection) -> None:
        newest = connection.execute(
            "SELECT run_id FROM current_entities ORDER BY stream_timestamp_ms DESC LIMIT 1"
        ).fetchone()
        if newest is not None:
            connection.execute(
                "DELETE FROM current_entities WHERE run_id <> ?", (str(newest["run_id"]),)
            )
            connection.execute("DELETE FROM messages WHERE run_id <> ?", (str(newest["run_id"]),))
            connection.execute(
                "DELETE FROM completed_runs WHERE run_id <> ?", (str(newest["run_id"]),)
            )
        connection.execute(
            """
            DELETE FROM messages
            WHERE stream_kind = 'metric'
              AND message_id NOT IN (
                  SELECT message_id FROM current_entities WHERE stream_kind = 'metric'
              )
            """
        )
        connection.execute(
            """
            DELETE FROM messages
            WHERE stream_kind = 'anomaly' AND rowid NOT IN (
                SELECT rowid FROM messages
                WHERE stream_kind = 'anomaly'
                ORDER BY stream_timestamp_ms DESC, revision DESC LIMIT 100
            )
            """
        )

    def offsets(self) -> dict[tuple[str, int], int]:
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                "SELECT kafka_topic, kafka_partition, next_offset FROM consumer_offsets"
            ).fetchall()
        return {
            (str(row["kafka_topic"]), int(row["kafka_partition"])): int(row["next_offset"])
            for row in rows
        }

    def snapshot(self, run_id: str | None = None) -> dict[str, Any]:
        selected_run = run_id or self._latest_run_id()
        if selected_run is None:
            return self._empty_snapshot()
        with self._lock, self._connect() as connection:
            current = connection.execute(
                """
                SELECT stream_kind, arrival_order, payload_json
                FROM current_entities
                WHERE run_id = ?
                ORDER BY stream_timestamp_ms, arrival_order, revision
                """,
                (selected_run,),
            ).fetchall()
            history = connection.execute(
                """
                SELECT stream_kind, payload_json
                FROM messages
                WHERE run_id = ? AND stream_kind = 'anomaly'
                ORDER BY stream_timestamp_ms, revision
                """,
                (selected_run,),
            ).fetchall()
        messages = [
            (
                row["stream_kind"],
                json.loads(row["payload_json"]),
                int(row["arrival_order"]),
            )
            for row in current
        ]
        metrics = [payload for kind, payload, _arrival in messages if kind == "metric"]
        anomalies = [payload for kind, payload, _arrival in messages if kind == "anomaly"]
        metric_arrival_orders = {
            (str(payload["metric_id"]), int(payload.get("revision", 0))): arrival
            for kind, payload, arrival in messages
            if kind == "metric"
        }
        run_status = self._latest_metric(
            metrics, "run_status", arrival_orders=metric_arrival_orders
        )
        robot_health = self._latest_metric(metrics, "robot_health")
        topic_metrics = self._latest_topics(metrics)
        mission_summaries = {
            payload["topic"]: payload
            for payload in metrics
            if payload.get("metric_type") == "mission_summary" and payload.get("topic")
        }
        run_metadata = run_status.get("payload", {}) if run_status else {}
        summary_ready = (
            run_status is not None
            and run_status.get("payload", {}).get("status") == "summary_ready"
        )
        completion = self.completion(
            selected_run,
            allow_verify=summary_ready,
            expected_topic_count=int(run_metadata.get("expected_topic_count", 4)),
        )
        mission_duration_ms = int(run_metadata.get("mission_duration_ms", 90_000))
        run_start_ms = min(
            (
                int(payload.get("stream_timestamp_ms", 0))
                for payload in metrics
                if payload.get("metric_type") == "run_status"
            ),
            default=None,
        )
        latest_stream_ms = max(
            (int(payload.get("stream_timestamp_ms", 0)) for payload in metrics),
            default=None,
        )
        return {
            "run_id": selected_run,
            "source": "recorded_replay",
            "run": run_status,
            "run_start_stream_ms": run_start_ms,
            "latest_stream_ms": latest_stream_ms,
            "mission_progress_ms": (
                min(mission_duration_ms, max(0, latest_stream_ms - run_start_ms))
                if run_start_ms is not None and latest_stream_ms is not None
                else 0
            ),
            "dataset_id": run_metadata.get("dataset_id", "warehouse_run_17"),
            "dataset_name": run_metadata.get("dataset_name", "Warehouse Run 17"),
            "source_format": run_metadata.get("source_format", "rosbag2_mcap"),
            "mission_duration_ms": mission_duration_ms,
            "topic_count": int(run_metadata.get("expected_topic_count", 4)),
            "robot_health": robot_health,
            "topics": topic_metrics,
            "anomalies": anomalies,
            "incident_history": [json.loads(row["payload_json"]) for row in history],
            "mission_summaries": mission_summaries,
            "completion": completion,
            "consumer_offsets": [
                {"topic": topic, "partition": partition, "next_offset": offset}
                for (topic, partition), offset in sorted(self.offsets().items())
            ],
        }

    def verify_completion(self, run_id: str) -> dict[str, Any]:
        directory = self.output_root / run_id / "topic_health"
        summaries: list[dict[str, Any]] = []
        errors: list[str] = []
        if directory.exists():
            temporary = [
                path
                for path in directory.rglob("*")
                if path.name.startswith(".") or "inprogress" in path.name
            ]
            if temporary:
                errors.append("temporary summary files remain")
            for part in directory.glob("**/part-*"):
                try:
                    lines = part.read_text(encoding="utf-8").splitlines()
                except OSError as exc:
                    errors.append(f"unreadable summary file {part.name}: {exc}")
                    continue
                for line in lines:
                    try:
                        payload = json.loads(line)
                    except json.JSONDecodeError:
                        errors.append(f"invalid JSON in {part.name}")
                        continue
                    schema_errors = list(METRIC_VALIDATOR.iter_errors(payload))
                    if schema_errors:
                        errors.append(f"schema-invalid summary in {part.name}")
                        continue
                    if (
                        payload.get("run_id") == run_id
                        and payload.get("metric_type") == "mission_summary"
                        and payload.get("topic")
                    ):
                        summaries.append(payload)
                    else:
                        errors.append(f"mismatched summary in {part.name}")
        topics = [str(payload["topic"]) for payload in summaries]
        if len(topics) != len(set(topics)):
            errors.append("duplicate topic summaries")
        expected_counts = {
            int(payload.get("payload", {}).get("expected_topic_count"))
            for payload in summaries
            if payload.get("payload", {}).get("expected_topic_count") is not None
        }
        if len(expected_counts) > 1:
            errors.append("inconsistent expected topic counts")
        expected_topic_count = next(iter(expected_counts), len(EXPECTED_TOPICS))
        if expected_topic_count <= 0:
            errors.append("invalid expected topic count")
        legacy_topics_valid = bool(expected_counts) or set(topics) == EXPECTED_TOPICS
        verified = len(summaries) == expected_topic_count and legacy_topics_valid and not errors
        result = {
            "verified": verified,
            "state": "completed" if verified else "pending",
            "summary_file_count": len(summaries),
            "expected_topic_count": expected_topic_count,
            "path": str(directory),
            "topics": sorted(topics),
            "errors": errors,
        }
        if verified:
            with self._lock, self._connect() as connection:
                newest = connection.execute(
                    "SELECT run_id FROM current_entities ORDER BY stream_timestamp_ms DESC LIMIT 1"
                ).fetchone()
                if newest is None or str(newest["run_id"]) == run_id:
                    connection.execute(
                        """
                        INSERT INTO completed_runs (run_id, state, verified_at_ms, manifest_json)
                        VALUES (?, 'completed', ?, ?)
                        ON CONFLICT(run_id) DO UPDATE SET
                            state = excluded.state,
                            verified_at_ms = excluded.verified_at_ms,
                            manifest_json = excluded.manifest_json
                        """,
                        (run_id, int(time.time() * 1_000), json.dumps(result, sort_keys=True)),
                    )
        return result

    def completion(
        self,
        run_id: str,
        *,
        allow_verify: bool = False,
        expected_topic_count: int = 4,
    ) -> dict[str, Any]:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT state, verified_at_ms, manifest_json FROM completed_runs WHERE run_id = ?",
                (run_id,),
            ).fetchone()
        if row is None:
            if allow_verify:
                return self.verify_completion(run_id)
            return {
                "verified": False,
                "state": "pending",
                "summary_file_count": 0,
                "expected_topic_count": expected_topic_count,
                "path": str(self.output_root / run_id / "topic_health"),
                "topics": [],
                "errors": ["waiting for committed summary_ready"],
            }
        result = json.loads(row["manifest_json"])
        result["state"] = str(row["state"])
        result["verified_at_ms"] = int(row["verified_at_ms"])
        return result

    def _latest_run_id(self) -> str | None:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                """
                SELECT run_id FROM current_entities
                ORDER BY stream_timestamp_ms DESC LIMIT 1
                """
            ).fetchone()
        return str(row["run_id"]) if row else None

    @staticmethod
    def _latest_metric(
        metrics: list[dict[str, Any]],
        metric_type: str,
        *,
        arrival_orders: dict[tuple[str, int], int] | None = None,
    ) -> dict[str, Any] | None:
        candidates = [item for item in metrics if item.get("metric_type") == metric_type]
        lifecycle_phase = {
            "starting": 0,
            "running": 0,
            "paused": 0,
            "finalizing": 1,
            "aborted": 2,
            "failed": 2,
            "summary_ready": 2,
        }

        def order(item: dict[str, Any]) -> tuple[int, int, int, int]:
            phase = (
                lifecycle_phase.get(str(item.get("payload", {}).get("status")), -1)
                if metric_type == "run_status"
                else 0
            )
            arrival_order = (arrival_orders or {}).get(
                (str(item.get("metric_id", "")), int(item.get("revision", 0))),
                0,
            )
            return (
                phase,
                int(item.get("stream_timestamp_ms", 0)),
                arrival_order,
                int(item.get("revision", 0)),
            )

        return max(candidates, key=order, default=None)

    @staticmethod
    def _latest_topics(metrics: list[dict[str, Any]]) -> list[dict[str, Any]]:
        selected: dict[str, dict[str, Any]] = {}
        for metric in metrics:
            if metric.get("metric_type") != "topic_window" or not metric.get("topic"):
                continue
            topic = str(metric["topic"])
            candidate_order = (
                int(metric.get("stream_timestamp_ms", 0)),
                int(metric.get("window_end_ms", 0)),
                int(metric.get("revision", 0)),
            )
            current = selected.get(topic)
            current_order = (
                (
                    int(current.get("stream_timestamp_ms", -1)),
                    int(current.get("window_end_ms", -1)),
                    int(current.get("revision", -1)),
                )
                if current
                else (-1, -1, -1)
            )
            if candidate_order >= current_order:
                selected[topic] = metric
        return [selected[topic] for topic in sorted(selected)]

    @staticmethod
    def _empty_snapshot() -> dict[str, Any]:
        return {
            "run_id": None,
            "source": "recorded_replay",
            "run": None,
            "run_start_stream_ms": None,
            "latest_stream_ms": None,
            "mission_progress_ms": 0,
            "dataset_id": "warehouse_run_17",
            "dataset_name": "Warehouse Run 17",
            "source_format": "rosbag2_mcap",
            "mission_duration_ms": 90_000,
            "topic_count": 4,
            "robot_health": None,
            "topics": [],
            "anomalies": [],
            "incident_history": [],
            "mission_summaries": {},
            "completion": {
                "verified": False,
                "summary_file_count": 0,
                "expected_topic_count": 4,
                "path": None,
            },
            "consumer_offsets": [],
        }
