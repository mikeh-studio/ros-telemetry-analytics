from __future__ import annotations

import fcntl
import json
import sqlite3
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any


class OutboxFull(RuntimeError):
    """Control evidence cannot fit; stop ingestion rather than lose the lifecycle."""


class DurableOutbox:
    """One process owns a bounded SQLite queue and crash-stable sequence allocation.

    A dequeue only happens after an acknowledged send. An uncertain send is retried
    with the persisted JSON, preserving both envelope and event IDs. Payload capacity
    excludes SQLite overhead; the separate database ceiling bounds page allocation.
    DELETE journaling avoids an unbounded WAL; budget for a rollback journal as well.
    """

    def __init__(
        self,
        path: Path,
        *,
        max_bytes: int = 8_000_000,
        max_records: int = 10000,
        max_database_bytes: int = 32_000_000,
        control_reserve_bytes: int = 65536,
        control_reserve_records: int = 32,
    ):
        if min(max_bytes, max_records, control_reserve_bytes, control_reserve_records) <= 0:
            raise ValueError("Outbox capacities must be positive")
        if max_database_bytes < max_bytes + control_reserve_bytes + 131072:
            raise ValueError("Database ceiling must include queue and metadata overhead")
        self.path = path
        self.max_bytes = max_bytes
        self.max_records = max_records
        self.reserve_bytes = control_reserve_bytes
        self.reserve_records = control_reserve_records
        path.parent.mkdir(parents=True, exist_ok=True)
        self._owner = path.with_suffix(path.suffix + ".lock").open("a+")
        try:
            fcntl.flock(self._owner, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self._owner.close()
            raise RuntimeError("Gateway outbox already has an owner") from None
        self._lock = threading.RLock()
        try:
            self._db = sqlite3.connect(path, check_same_thread=False)
            self._db.row_factory = sqlite3.Row
            self._db.execute("PRAGMA journal_mode=DELETE")
            self._db.execute("PRAGMA synchronous=FULL")
            page_size = self._db.execute("PRAGMA page_size").fetchone()[0]
            self._db.execute(f"PRAGMA max_page_count={max_database_bytes // page_size}")
            self._db.executescript("""
                CREATE TABLE IF NOT EXISTS state (
                    id INTEGER PRIMARY KEY CHECK(id=1), next_sequence INTEGER NOT NULL,
                    received INTEGER NOT NULL, acknowledged INTEGER NOT NULL,
                    rejected INTEGER NOT NULL, pending_bytes INTEGER NOT NULL,
                    pending_records INTEGER NOT NULL, last_receipt_ns INTEGER NOT NULL, session TEXT
                );
                INSERT OR IGNORE INTO state VALUES (1, 0, 0, 0, 0, 0, 0, 0, NULL);
                CREATE TABLE IF NOT EXISTS outbox (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, partition_key TEXT NOT NULL,
                    payload TEXT NOT NULL, size_bytes INTEGER NOT NULL,
                    is_telemetry INTEGER NOT NULL
                );
            """)
            self._db.commit()
            if self.stats()["pending_bytes"] > max_bytes + control_reserve_bytes:
                raise ValueError("Existing outbox exceeds the requested capacity")
            if self.stats()["database_bytes"] > max_database_bytes:
                raise ValueError("Existing database exceeds the requested ceiling")
        except BaseException:
            if hasattr(self, "_db"):
                self._db.close()
            self._owner.close()
            raise

    def close(self) -> None:
        with self._lock:
            self._db.close()
            self._owner.close()

    def stats(self) -> dict[str, Any]:
        with self._lock:
            row = dict(self._db.execute("SELECT * FROM state WHERE id=1").fetchone())
            row.pop("id")
            row.pop("session")
            row["database_bytes"] = self.path.stat().st_size
            return row

    def session(self) -> dict[str, Any] | None:
        with self._lock:
            value = self._db.execute("SELECT session FROM state WHERE id=1").fetchone()[0]
            return json.loads(value) if value is not None else None

    def begin_session(self, session: dict[str, Any], controls: list[tuple[str, dict]]) -> None:
        """Atomically establish identity and registrations before any telemetry."""
        with self._lock, self._db:
            self._db.execute("BEGIN IMMEDIATE")
            if self.session() is not None:
                raise RuntimeError("A gateway session is already established")
            for key, payload in controls:
                if not self._insert(key, payload, telemetry=False):
                    raise OutboxFull("Run registration does not fit the outbox")
            self._db.execute(
                "UPDATE state SET session=? WHERE id=1",
                (json.dumps(session, sort_keys=True, allow_nan=False),),
            )

    def reset_completed_session(self) -> None:
        with self._lock, self._db:
            self._db.execute("BEGIN IMMEDIATE")
            session = self.session()
            if session is None:
                return
            if not session.get("closed") or self.stats()["pending_records"]:
                raise RuntimeError("Cannot reset a session until closed and fully acknowledged")
            self._db.execute("""UPDATE state SET next_sequence=0, received=0, acknowledged=0,
                rejected=0, session=NULL WHERE id=1""")

    def end_session(self, controls: list[tuple[str, dict]]) -> None:
        """Queue terminal controls and persist closed status in the same transaction."""
        with self._lock, self._db:
            self._db.execute("BEGIN IMMEDIATE")
            session = self.session()
            if session is None or session.get("closed"):
                return
            for key, payload in controls:
                if not self._insert(key, payload, telemetry=False):
                    raise OutboxFull("Run termination does not fit the outbox")
            session["closed"] = True
            if controls:
                session["ended_stream_ms"] = controls[0][1].get("stream_timestamp_ms")
            self._db.execute(
                "UPDATE state SET session=? WHERE id=1", (json.dumps(session, sort_keys=True),)
            )

    def enqueue(self, factory: Callable[[int], tuple[str, dict]]) -> bool:
        """Count every observation, including overflow; rejected sequences remain gaps."""
        with self._lock, self._db:
            self._db.execute("BEGIN IMMEDIATE")
            session = self.session()
            if session is None or session.get("closed"):
                raise RuntimeError("No open gateway session")
            sequence = self._db.execute("SELECT next_sequence FROM state WHERE id=1").fetchone()[0]
            key, payload = factory(sequence)
            accepted = self._insert(key, payload, telemetry=True)
            self._db.execute(
                """UPDATE state SET next_sequence=next_sequence+1,
                received=received+1, rejected=rejected+? WHERE id=1""",
                (int(not accepted),),
            )
            return accepted

    def _insert(self, key: str, value: dict, *, telemetry: bool) -> bool:
        payload = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
        size = len(payload.encode("utf-8"))
        state = self.stats()
        byte_limit = self.max_bytes + (0 if telemetry else self.reserve_bytes)
        record_limit = self.max_records + (0 if telemetry else self.reserve_records)
        if state["pending_bytes"] + size > byte_limit or state["pending_records"] >= record_limit:
            return False
        self._db.execute(
            """INSERT INTO outbox(partition_key,payload,size_bytes,is_telemetry)
                            VALUES (?,?,?,?)""",
            (key, payload, size, int(telemetry)),
        )
        self._db.execute(
            """UPDATE state SET pending_bytes=pending_bytes+?,
                            pending_records=pending_records+1 WHERE id=1""",
            (size,),
        )
        if telemetry:
            self._db.execute(
                "UPDATE state SET last_receipt_ns=MAX(last_receipt_ns,?) WHERE id=1",
                (int(value.get("event_timestamp_ns", 0)),),
            )
        return True

    def peek(self) -> dict[str, Any] | None:
        with self._lock:
            row = self._db.execute("SELECT * FROM outbox ORDER BY id LIMIT 1").fetchone()
            return {**dict(row), "payload": json.loads(row["payload"])} if row else None

    def acknowledge(self, record_id: int) -> None:
        with self._lock, self._db:
            self._db.execute("BEGIN IMMEDIATE")
            row = self._db.execute("SELECT * FROM outbox ORDER BY id LIMIT 1").fetchone()
            if row is None or row["id"] != record_id:
                raise ValueError("Acknowledgment must match the head of the outbox")
            self._db.execute("DELETE FROM outbox WHERE id=?", (record_id,))
            self._db.execute(
                """UPDATE state SET pending_bytes=pending_bytes-?,
                pending_records=pending_records-1, acknowledged=acknowledged+? WHERE id=1""",
                (row["size_bytes"], row["is_telemetry"]),
            )
