"""Durable storage for public runtime event envelopes.

The ledger stores redacted public ``RuntimeEvent`` records for replay and
runtime observability. It is intentionally not the conversation transcript or a
private diagnostics store.
"""

from __future__ import annotations

import json
import hashlib
import math
import os
import queue
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

from penguin.config import WORKSPACE_PATH
from penguin.system.runtime_diagnostics import record_runtime_duration
from penguin.system.runtime_events import (
    RUNTIME_EVENT_SCHEMA_VERSION,
    redact_runtime_payload,
)

DEFAULT_LEDGER_MAX_EVENTS = 100_000
DEFAULT_LEDGER_MAX_AGE_DAYS = 14
DEFAULT_LEDGER_MAX_BYTES = 256 * 1024 * 1024
DEFAULT_LEDGER_CLEANUP_INTERVAL_SECONDS = 60.0
DEFAULT_LEDGER_WRITER_QUEUE_MAX_EVENTS = 2048
DEFAULT_LEDGER_WRITER_BATCH_MAX_EVENTS = 100
DEFAULT_LEDGER_WRITER_BATCH_MAX_DELAY_SECONDS = 0.05
DEFAULT_LEDGER_WRITER_SHUTDOWN_TIMEOUT_SECONDS = 2.0
_RUNTIME_EVENT_LEDGER_ATTR = "_runtime_event_ledger_v1"


@dataclass(frozen=True)
class RuntimeEventLedgerPolicy:
    """Retention and cleanup policy for the runtime event ledger.

    Attributes:
        max_events: Maximum retained event rows before oldest-row cleanup.
        max_age_seconds: Optional event-age retention window in seconds.
        max_bytes: Optional soft on-disk size limit for the SQLite database and
            WAL sidecar.
        cleanup_interval_seconds: Minimum seconds between automatic cleanups.
    """

    max_events: int = DEFAULT_LEDGER_MAX_EVENTS
    max_age_seconds: int | None = DEFAULT_LEDGER_MAX_AGE_DAYS * 24 * 60 * 60
    max_bytes: int | None = DEFAULT_LEDGER_MAX_BYTES
    cleanup_interval_seconds: float = DEFAULT_LEDGER_CLEANUP_INTERVAL_SECONDS
    writer_queue_max_events: int = DEFAULT_LEDGER_WRITER_QUEUE_MAX_EVENTS
    writer_batch_max_events: int = DEFAULT_LEDGER_WRITER_BATCH_MAX_EVENTS
    writer_batch_max_delay_seconds: float = (
        DEFAULT_LEDGER_WRITER_BATCH_MAX_DELAY_SECONDS
    )
    writer_shutdown_timeout_seconds: float = (
        DEFAULT_LEDGER_WRITER_SHUTDOWN_TIMEOUT_SECONDS
    )


@dataclass(frozen=True)
class ReplayResult:
    """Ledger replay lookup result.

    Attributes:
        found: Whether the replay cursor was present in retained ledger rows.
        events: RuntimeEvent envelopes retained after the replay cursor.
        oldest_event_id: Oldest currently retained RuntimeEvent id, if any.
        newest_event_id: Newest currently retained RuntimeEvent id, if any.
    """

    found: bool
    events: list[dict[str, Any]]
    oldest_event_id: str | None = None
    newest_event_id: str | None = None


@dataclass(frozen=True)
class _LedgerQueueItem:
    """One event or durability barrier owned by the ledger writer."""

    event: Mapping[str, Any] | None = None
    barrier: threading.Event | None = None


def default_ledger_path() -> Path:
    """Return the default on-disk SQLite path for runtime events.

    Returns:
        Configured ledger path from ``PENGUIN_RUNTIME_EVENT_LEDGER_PATH`` or
        the default path under ``WORKSPACE_PATH/runtime_events``.
    """
    override = os.getenv("PENGUIN_RUNTIME_EVENT_LEDGER_PATH")
    if override:
        return Path(override).expanduser()
    return Path(WORKSPACE_PATH).expanduser() / "runtime_events" / "runtime_events.db"


def policy_from_env() -> RuntimeEventLedgerPolicy:
    """Build a ledger policy from environment variables.

    Returns:
        RuntimeEventLedgerPolicy populated from ``PENGUIN_RUNTIME_EVENT_*``
        settings, with defaults for missing or malformed values.
    """
    return RuntimeEventLedgerPolicy(
        max_events=_env_int(
            "PENGUIN_RUNTIME_EVENT_LEDGER_MAX_EVENTS",
            DEFAULT_LEDGER_MAX_EVENTS,
        ),
        max_age_seconds=_env_age_seconds(
            "PENGUIN_RUNTIME_EVENT_LEDGER_MAX_AGE_DAYS",
            DEFAULT_LEDGER_MAX_AGE_DAYS,
        ),
        max_bytes=_env_optional_int(
            "PENGUIN_RUNTIME_EVENT_LEDGER_MAX_BYTES",
            DEFAULT_LEDGER_MAX_BYTES,
        ),
        cleanup_interval_seconds=_env_cleanup_interval_seconds(
            "PENGUIN_RUNTIME_EVENT_LEDGER_CLEANUP_INTERVAL_SECONDS",
            DEFAULT_LEDGER_CLEANUP_INTERVAL_SECONDS,
        ),
        writer_queue_max_events=max(
            1,
            _env_int(
                "PENGUIN_RUNTIME_EVENT_LEDGER_WRITER_QUEUE_MAX_EVENTS",
                DEFAULT_LEDGER_WRITER_QUEUE_MAX_EVENTS,
            ),
        ),
        writer_batch_max_events=max(
            1,
            _env_int(
                "PENGUIN_RUNTIME_EVENT_LEDGER_WRITER_BATCH_MAX_EVENTS",
                DEFAULT_LEDGER_WRITER_BATCH_MAX_EVENTS,
            ),
        ),
        writer_batch_max_delay_seconds=max(
            0.001,
            _env_float(
                "PENGUIN_RUNTIME_EVENT_LEDGER_WRITER_BATCH_MAX_DELAY_SECONDS",
                DEFAULT_LEDGER_WRITER_BATCH_MAX_DELAY_SECONDS,
            ),
        ),
        writer_shutdown_timeout_seconds=max(
            0.1,
            _env_float(
                "PENGUIN_RUNTIME_EVENT_LEDGER_WRITER_SHUTDOWN_TIMEOUT_SECONDS",
                DEFAULT_LEDGER_WRITER_SHUTDOWN_TIMEOUT_SECONDS,
            ),
        ),
    )


def get_runtime_event_ledger(core: Any | None = None) -> RuntimeEventLedger:
    """Return the shared runtime event ledger.

    Args:
        core: Optional Penguin core object that should own an isolated ledger
            instance for this process.

    Returns:
        RuntimeEventLedger attached to ``core`` when provided, otherwise the
        process-level ledger.
    """
    if core is not None:
        existing = getattr(core, _RUNTIME_EVENT_LEDGER_ATTR, None)
        if isinstance(existing, RuntimeEventLedger):
            return existing
        ledger = RuntimeEventLedger(default_ledger_path(), policy=policy_from_env())
        setattr(core, _RUNTIME_EVENT_LEDGER_ATTR, ledger)
        return ledger

    global _PROCESS_LEDGER
    if _PROCESS_LEDGER is None:
        _PROCESS_LEDGER = RuntimeEventLedger(
            default_ledger_path(),
            policy=policy_from_env(),
        )
    return _PROCESS_LEDGER


class RuntimeEventLedger:
    """SQLite-backed append-only ledger for public runtime events.

    The ledger stores only already-redacted public RuntimeEvent envelopes. It
    provides durable replay and bounded retention for SSE/client reconnects; it
    is not the private transcript or diagnostics store.
    """

    def __init__(
        self,
        path: str | Path,
        *,
        policy: RuntimeEventLedgerPolicy | None = None,
    ) -> None:
        self.path = Path(path).expanduser()
        self.policy = policy or RuntimeEventLedgerPolicy()
        self._lock = threading.RLock()
        self._local = threading.local()
        self._last_cleanup = 0.0
        self._initialized = False

        self._writer_queue: queue.Queue[_LedgerQueueItem] = queue.Queue(
            maxsize=max(1, int(self.policy.writer_queue_max_events))
        )
        self._writer_state_lock = threading.RLock()
        self._writer_thread: threading.Thread | None = None
        self._writer_stop_requested = False
        self._writer_error: BaseException | None = None
        self._writer_failed_events = 0
        self._ledger_id: str | None = None

    def enqueue(self, event: Mapping[str, Any]) -> bool:
        """Admit an event without waiting on SQLite or filesystem work.

        ``True`` means accepted in memory, not durable. Call :meth:`flush` for
        a bounded durability barrier. A full queue returns ``False`` so live
        event delivery cannot turn into an unbounded disk wait.
        """

        prepared = _prepare_event(event)
        if prepared is None:
            return False
        with self._writer_state_lock:
            if self._writer_stop_requested:
                return False
            self._ensure_writer_started_locked()
            try:
                self._writer_queue.put_nowait(_LedgerQueueItem(event=prepared))
            except queue.Full:
                return False
        return True

    def flush(self, timeout_seconds: float | None = None) -> bool:
        """Wait for all events admitted before this call to be committed."""

        with self._writer_state_lock:
            if self._writer_thread is None:
                return self._writer_error is None
            timeout = (
                timeout_seconds
                if timeout_seconds is not None
                else self.policy.writer_shutdown_timeout_seconds
            )
        deadline = time.monotonic() + max(0.0, timeout)
        barrier = threading.Event()
        while True:
            with self._writer_state_lock:
                try:
                    self._writer_queue.put_nowait(_LedgerQueueItem(barrier=barrier))
                    break
                except queue.Full:
                    pass
            if time.monotonic() >= deadline:
                return False
            time.sleep(0.01)
        if not barrier.wait(max(0.0, deadline - time.monotonic())):
            return False
        return self._writer_error is None

    def shutdown(
        self,
        *,
        drain: bool = True,
        timeout_seconds: float | None = None,
    ) -> bool:
        """Stop the writer, draining admitted events up to a deadline."""

        with self._writer_state_lock:
            thread = self._writer_thread
            if thread is None:
                return self._writer_error is None
            self._writer_stop_requested = True
            if not drain:
                while True:
                    try:
                        self._writer_queue.get_nowait()
                    except queue.Empty:
                        break
                    self._writer_queue.task_done()
        timeout = (
            timeout_seconds
            if timeout_seconds is not None
            else self.policy.writer_shutdown_timeout_seconds
        )
        thread.join(max(0.0, timeout))
        stopped = not thread.is_alive()
        if stopped:
            with self._writer_state_lock:
                self._writer_thread = None
                self._writer_stop_requested = False
        return stopped and self._writer_error is None

    @property
    def pending_count(self) -> int:
        """Return the number of events/barriers waiting in the writer queue."""

        return self._writer_queue.qsize()

    @property
    def writer_failed_events(self) -> int:
        """Return the number of admitted events lost to a writer failure."""

        with self._writer_state_lock:
            return self._writer_failed_events

    @property
    def ledger_id(self) -> str:
        """Return the stable identifier for this on-disk ledger."""

        with self._lock:
            conn = self._thread_connection()
            self._ensure_schema(conn)
            return self._ledger_id or "unknown"

    def _ensure_writer_started_locked(self) -> None:
        if self._writer_thread is not None and self._writer_thread.is_alive():
            return
        self._writer_stop_requested = False
        self._writer_thread = threading.Thread(
            target=self._writer_loop,
            name="penguin-runtime-event-ledger",
            daemon=True,
        )
        self._writer_thread.start()

    def _writer_loop(self) -> None:
        while True:
            try:
                first = self._writer_queue.get(
                    timeout=self.policy.writer_batch_max_delay_seconds
                )
            except queue.Empty:
                if self._writer_stop_requested and self._writer_queue.empty():
                    return
                continue

            items = [first]
            deadline = time.monotonic() + self.policy.writer_batch_max_delay_seconds
            while len(items) < max(1, self.policy.writer_batch_max_events):
                remaining = max(0.0, deadline - time.monotonic())
                if remaining == 0:
                    break
                try:
                    items.append(self._writer_queue.get(timeout=remaining))
                except queue.Empty:
                    break

            events = [item.event for item in items if item.event is not None]
            failed = False
            if events:
                try:
                    with self._lock:
                        self._append_batch(events)
                except BaseException as exc:
                    failed = True
                    with self._writer_state_lock:
                        self._writer_error = exc
                        self._writer_failed_events += len(events)
                        self._writer_stop_requested = True
                finally:
                    for item in items:
                        self._writer_queue.task_done()
            else:
                for item in items:
                    self._writer_queue.task_done()

            for item in items:
                if item.barrier is not None:
                    item.barrier.set()

            if failed:
                while True:
                    try:
                        discarded = self._writer_queue.get_nowait()
                    except queue.Empty:
                        break
                    self._writer_queue.task_done()
                    if discarded.barrier is not None:
                        discarded.barrier.set()
                return

            if self._writer_stop_requested and self._writer_queue.empty():
                return

    def append(self, event: Mapping[str, Any]) -> bool:
        """Persist a redacted public RuntimeEvent envelope.

        Args:
            event: Candidate RuntimeEvent envelope.

        Returns:
            True when a new row was inserted. False when the event is invalid,
            unsafe to persist, or already present.
        """
        if _prepare_event(event) is None:
            return False
        with self._lock:
            return self._append_batch([event]) > 0

    def extend(self, events: Iterable[Mapping[str, Any]]) -> int:
        """Persist multiple redacted public RuntimeEvent envelopes.

        Args:
            events: Iterable of candidate RuntimeEvent envelopes.

        Returns:
            Number of rows inserted into the ledger.
        """
        prepared = [event for event in events if _prepare_event(event) is not None]
        if not prepared:
            return 0
        with self._lock:
            return self._append_batch(prepared)

    def _append_batch(self, events: Iterable[Mapping[str, Any]]) -> int:
        """Persist one event batch in one transaction."""

        prepared_events = [
            prepared
            for event in events
            if (prepared := _prepare_event(event)) is not None
        ]
        if not prepared_events:
            return 0

        connection_started = time.perf_counter()
        conn = self._thread_connection()
        record_runtime_duration(
            "ledger.connection",
            (time.perf_counter() - connection_started) * 1000,
        )
        try:
            schema_started = time.perf_counter()
            self._ensure_schema(conn)
            record_runtime_duration(
                "ledger.schema",
                (time.perf_counter() - schema_started) * 1000,
            )
            inserted = 0
            insert_started = time.perf_counter()
            for event in prepared_events:
                event_to_insert = event
                event_json = _json_dump(event)
                existing = conn.execute(
                    "SELECT event_json FROM runtime_events WHERE event_id = ? LIMIT 1",
                    (event["id"],),
                ).fetchone()
                if existing is not None:
                    if existing["event_json"] == event_json:
                        continue
                    event_to_insert = _conflict_event(event, event_json, conn)
                    if event_to_insert is None:
                        continue

                scope = event_to_insert.get("scope")
                scope = scope if isinstance(scope, Mapping) else {}
                privacy = event_to_insert.get("privacy")
                privacy = privacy if isinstance(privacy, Mapping) else {}
                before_changes = conn.total_changes
                conn.execute(
                    """
                    INSERT OR IGNORE INTO runtime_events (
                        event_id, stream_id, sequence, event_type, category,
                        event_time, inserted_at, session_id, conversation_id,
                        agent_id, task_id, run_id, project_id, directory,
                        privacy_classification, redacted, payload_json,
                        projection_json, event_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        event_to_insert["id"],
                        _string_or_none(event_to_insert.get("stream_id")) or "global",
                        _positive_int_or_zero(event_to_insert.get("sequence")),
                        _string_or_none(event_to_insert.get("type")) or "unknown",
                        _string_or_none(event_to_insert.get("category")) or "session_lifecycle",
                        _positive_int_or_zero(event_to_insert.get("time")),
                        int(time.time() * 1000),
                        _string_or_none(scope.get("session_id")),
                        _string_or_none(scope.get("conversation_id")),
                        _string_or_none(scope.get("agent_id")),
                        _string_or_none(scope.get("task_id")),
                        _string_or_none(scope.get("run_id")),
                        _string_or_none(scope.get("project_id")),
                        _string_or_none(scope.get("directory")),
                        _string_or_none(privacy.get("classification")) or "public",
                        1 if privacy.get("redacted") else 0,
                        _json_dump(event_to_insert.get("payload", {})),
                        _json_dump(event_to_insert.get("projections", {})),
                        _json_dump(event_to_insert),
                    ),
                )
                inserted += int(conn.total_changes > before_changes)
            record_runtime_duration(
                "ledger.insert",
                (time.perf_counter() - insert_started) * 1000,
            )
            cleanup_started = time.perf_counter()
            self.cleanup_if_due(conn=conn)
            record_runtime_duration(
                "ledger.cleanup",
                (time.perf_counter() - cleanup_started) * 1000,
            )
            commit_started = time.perf_counter()
            conn.commit()
            record_runtime_duration(
                "ledger.commit",
                (time.perf_counter() - commit_started) * 1000,
            )
            return inserted
        except Exception:
            conn.rollback()
            raise

    def contains(self, event_id: str) -> bool:
        """Return whether an event id exists in the ledger.

        Args:
            event_id: RuntimeEvent id to look up.

        Returns:
            True when the event id is currently retained.
        """
        self.flush()
        with self._lock:
            conn = self._connect()
            try:
                self._ensure_schema(conn)
                row = conn.execute(
                    "SELECT 1 FROM runtime_events WHERE event_id = ? LIMIT 1",
                    (event_id,),
                ).fetchone()
                return row is not None
            finally:
                conn.close()

    def replay_after(
        self,
        last_event_id: str,
        *,
        limit: int | None = None,
        session_id: str | None = None,
        agent_id: str | None = None,
        directory: str | None = None,
    ) -> ReplayResult:
        """Return events after ``last_event_id`` in durable insertion order.

        Args:
            last_event_id: RuntimeEvent id supplied by a reconnecting client.
            limit: Optional maximum number of events to return.
            session_id: Optional session scope for replay filtering.
            agent_id: Optional agent scope for replay filtering.
            directory: Optional directory scope for replay filtering.

        Returns:
            ReplayResult with retained events after the cursor, or a gap result
            when the cursor is no longer retained.
        """
        if not isinstance(last_event_id, str) or not last_event_id:
            return ReplayResult(found=False, events=[], **self.bounds())

        self.flush()
        with self._lock:
            conn = self._connect()
            try:
                self._ensure_schema(conn)
                cursor_row = conn.execute(
                    "SELECT rowid FROM runtime_events WHERE event_id = ? LIMIT 1",
                    (last_event_id,),
                ).fetchone()
                bounds = self.bounds(conn=conn)
                if cursor_row is None:
                    return ReplayResult(found=False, events=[], **bounds)

                clauses = ["rowid > ?"]
                params: list[Any] = [cursor_row["rowid"]]
                if session_id:
                    clauses.append("(session_id = ? OR session_id IS NULL)")
                    params.append(session_id)
                if agent_id:
                    clauses.append("(agent_id = ? OR agent_id IS NULL)")
                    params.append(agent_id)
                if directory:
                    clauses.append("(directory = ? OR directory IS NULL)")
                    params.append(directory)

                sql = """
                    SELECT event_json
                    FROM runtime_events
                    WHERE {where_clause}
                    ORDER BY rowid ASC
                """.format(where_clause=" AND ".join(clauses))
                if limit is not None and limit > 0:
                    sql += " LIMIT ?"
                    params.append(limit)
                rows = conn.execute(sql, params).fetchall()
                return ReplayResult(
                    found=True,
                    events=[_json_load(row["event_json"]) for row in rows],
                    **bounds,
                )
            finally:
                conn.close()

    def newest(self, *, limit: int = 100) -> list[dict[str, Any]]:
        """Return newest retained events in insertion order.

        Args:
            limit: Maximum number of events to return.

        Returns:
            Retained RuntimeEvent envelopes ordered oldest-to-newest within the
            selected newest slice.
        """
        self.flush()
        with self._lock:
            conn = self._connect()
            try:
                self._ensure_schema(conn)
                rows = conn.execute(
                    """
                    SELECT event_json
                    FROM runtime_events
                    ORDER BY rowid DESC
                    LIMIT ?
                    """,
                    (max(limit, 0),),
                ).fetchall()
                return [_json_load(row["event_json"]) for row in reversed(rows)]
            finally:
                conn.close()

    def bounds(
        self,
        *,
        conn: sqlite3.Connection | None = None,
    ) -> dict[str, str | None]:
        """Return oldest and newest retained event ids.

        Args:
            conn: Optional existing SQLite connection to reuse.

        Returns:
            Mapping with ``oldest_event_id`` and ``newest_event_id`` values.
        """
        owns_connection = conn is None
        if conn is None:
            self.flush()
            conn = self._connect()
        try:
            self._ensure_schema(conn)
            oldest = conn.execute(
                "SELECT event_id FROM runtime_events ORDER BY rowid ASC LIMIT 1"
            ).fetchone()
            newest = conn.execute(
                "SELECT event_id FROM runtime_events ORDER BY rowid DESC LIMIT 1"
            ).fetchone()
            return {
                "oldest_event_id": oldest["event_id"] if oldest else None,
                "newest_event_id": newest["event_id"] if newest else None,
            }
        finally:
            if owns_connection:
                conn.close()

    def cleanup_if_due(self, *, conn: sqlite3.Connection | None = None) -> None:
        """Run throttled retention cleanup when the policy interval has elapsed.

        Args:
            conn: Optional existing SQLite connection to reuse.
        """
        now = time.monotonic()
        if (
            self.policy.cleanup_interval_seconds > 0
            and now - self._last_cleanup < self.policy.cleanup_interval_seconds
        ):
            return
        self.cleanup(conn=conn)
        self._last_cleanup = now

    def cleanup(self, *, conn: sqlite3.Connection | None = None) -> None:
        """Apply max-events, max-age, and soft max-size retention rules.

        Args:
            conn: Optional existing SQLite connection to reuse.
        """
        owns_connection = conn is None
        if conn is None:
            conn = self._connect()
        try:
            self._ensure_schema(conn)
            self._cleanup_by_age(conn)
            self._cleanup_by_count(conn)
            self._cleanup_by_size(conn)
            conn.commit()
        finally:
            if owns_connection:
                conn.close()

    def _cleanup_by_age(self, conn: sqlite3.Connection) -> None:
        if self.policy.max_age_seconds is None or self.policy.max_age_seconds <= 0:
            return
        cutoff_ms = int((time.time() - self.policy.max_age_seconds) * 1000)
        conn.execute("DELETE FROM runtime_events WHERE event_time < ?", (cutoff_ms,))

    def _cleanup_by_count(self, conn: sqlite3.Connection) -> None:
        if self.policy.max_events <= 0:
            conn.execute("DELETE FROM runtime_events")
            return
        count = conn.execute("SELECT COUNT(*) AS count FROM runtime_events").fetchone()[
            "count"
        ]
        overflow = int(count) - self.policy.max_events
        if overflow <= 0:
            return
        conn.execute(
            """
            DELETE FROM runtime_events
            WHERE rowid IN (
                SELECT rowid FROM runtime_events ORDER BY rowid ASC LIMIT ?
            )
            """,
            (overflow,),
        )

    def _cleanup_by_size(self, conn: sqlite3.Connection) -> None:
        max_bytes = self.policy.max_bytes
        if max_bytes is None or max_bytes <= 0:
            return

        # WAL bytes are included in the soft cap. Checkpoint first so a large
        # sidecar does not make the row-pruning estimate over-delete retained
        # replay history when truncating the WAL would be enough.
        conn.commit()
        if not self._checkpoint_wal(conn):
            return
        current_size = self._database_size_bytes(conn)
        if current_size <= max_bytes:
            return

        count = conn.execute(
            "SELECT COUNT(*) AS count FROM runtime_events"
        ).fetchone()["count"]
        retained_count = int(count)
        if retained_count <= 1:
            self._incremental_vacuum(conn)
            return

        low_water = max(1, int(max_bytes * 0.9))
        estimated_bytes_per_row = max(1, current_size // retained_count)
        target_count = max(1, low_water // estimated_bytes_per_row)
        if target_count >= retained_count:
            target_count = retained_count - 1
        delete_count = max(1, retained_count - target_count)
        delete_count = min(delete_count, retained_count - 1)
        conn.execute(
            """
            DELETE FROM runtime_events
            WHERE rowid IN (
                SELECT rowid FROM runtime_events ORDER BY rowid ASC LIMIT ?
            )
            """,
            (delete_count,),
        )
        conn.commit()
        if not self._checkpoint_wal(conn):
            return
        self._incremental_vacuum(conn)
        conn.commit()
        self._checkpoint_wal(conn)

    def _checkpoint_wal(self, conn: sqlite3.Connection) -> bool:
        try:
            row = conn.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
        except sqlite3.DatabaseError:
            return False
        if row is None:
            return False
        return int(row[0]) == 0

    def _incremental_vacuum(self, conn: sqlite3.Connection) -> None:
        try:
            conn.execute("PRAGMA incremental_vacuum")
        except sqlite3.DatabaseError:
            pass

    def _database_size_bytes(self, conn: sqlite3.Connection) -> int:
        page_count = conn.execute("PRAGMA page_count").fetchone()[0]
        page_size = conn.execute("PRAGMA page_size").fetchone()[0]
        logical_size = int(page_count) * int(page_size)
        file_size = self.path.stat().st_size if self.path.exists() else 0
        wal_size = _path_size(self.path.with_name(f"{self.path.name}-wal"))
        return max(logical_size, file_size) + wal_size

    def _thread_connection(self) -> sqlite3.Connection:
        conn = getattr(self._local, "connection", None)
        if isinstance(conn, sqlite3.Connection):
            try:
                conn.execute("SELECT 1")
                return conn
            except sqlite3.Error:
                pass
        conn = self._connect()
        self._local.connection = conn
        return conn

    def _connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.path), timeout=30.0)
        conn.row_factory = sqlite3.Row
        auto_vacuum = conn.execute("PRAGMA auto_vacuum").fetchone()[0]
        if int(auto_vacuum) != 2:
            conn.execute("PRAGMA auto_vacuum=INCREMENTAL")
            conn.execute("VACUUM")
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=30000")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _ensure_schema(self, conn: sqlite3.Connection) -> None:
        if self._initialized:
            return
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS ledger_meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            INSERT OR IGNORE INTO ledger_meta (key, value)
            VALUES ('ledger_id', ?)
            """,
            (uuid.uuid4().hex,),
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS runtime_events (
                event_id TEXT PRIMARY KEY,
                stream_id TEXT NOT NULL,
                sequence INTEGER NOT NULL,
                event_type TEXT NOT NULL,
                category TEXT NOT NULL,
                event_time INTEGER NOT NULL,
                inserted_at INTEGER NOT NULL,
                session_id TEXT,
                conversation_id TEXT,
                agent_id TEXT,
                task_id TEXT,
                run_id TEXT,
                project_id TEXT,
                directory TEXT,
                privacy_classification TEXT,
                redacted INTEGER NOT NULL DEFAULT 0,
                payload_json TEXT NOT NULL,
                projection_json TEXT NOT NULL,
                event_json TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_runtime_events_stream_sequence
            ON runtime_events(stream_id, sequence)
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_runtime_events_scope
            ON runtime_events(session_id, agent_id, directory)
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_runtime_events_time
            ON runtime_events(event_time)
            """
        )
        ledger_row = conn.execute(
            "SELECT value FROM ledger_meta WHERE key = 'ledger_id'"
        ).fetchone()
        if ledger_row is not None:
            self._ledger_id = str(ledger_row["value"])
        conn.commit()
        self._initialized = True


_PROCESS_LEDGER: RuntimeEventLedger | None = None


def _prepare_event(event: Mapping[str, Any]) -> dict[str, Any] | None:
    """Validate and copy one event before queueing or writing it."""

    event_id = event.get("id")
    if not isinstance(event_id, str) or not event_id:
        return None
    if not _looks_like_public_runtime_event(event):
        return None
    return dict(event)


def _conflict_event(
    event: Mapping[str, Any],
    event_json: str,
    conn: sqlite3.Connection,
) -> dict[str, Any] | None:
    """Return a deterministic id for a same-id/different-payload event.

    A process restart or provider retry can re-use a source id with changed
    content. ``INSERT OR IGNORE`` would silently discard that content, so keep
    the original id and preserve the conflicting envelope under a stable
    derived id. Repeating the same conflict remains idempotent.
    """

    base_id = f"{event['id']}:conflict:{hashlib.sha256(event_json.encode()).hexdigest()[:16]}"
    candidate = base_id
    suffix = 1
    while True:
        conflict = dict(event)
        conflict["id"] = candidate
        conflict_json = _json_dump(conflict)
        existing = conn.execute(
            "SELECT event_json FROM runtime_events WHERE event_id = ? LIMIT 1",
            (candidate,),
        ).fetchone()
        if existing is None:
            return conflict
        if existing["event_json"] == conflict_json:
            return None
        candidate = f"{base_id}:{suffix}"
        suffix += 1


def _looks_like_public_runtime_event(event: Mapping[str, Any]) -> bool:
    schema = event.get("schema_version")
    if schema != RUNTIME_EVENT_SCHEMA_VERSION:
        return False
    event_type = event.get("type")
    event_id = event.get("id")
    payload = event.get("payload")
    privacy = event.get("privacy")
    if not (
        isinstance(event_type, str)
        and bool(event_type)
        and isinstance(event_id, str)
        and bool(event_id)
        and isinstance(payload, Mapping)
        and isinstance(privacy, Mapping)
    ):
        return False

    classification = privacy.get("classification")
    redacted = privacy.get("redacted")
    redacted_fields = privacy.get("redacted_fields")
    event_is_safely_redacted = _value_is_already_redacted(event)
    if classification == "public" and redacted is False:
        return event_is_safely_redacted
    if (
        classification == "sensitive"
        and redacted is True
        and isinstance(redacted_fields, list)
    ):
        return event_is_safely_redacted
    return False


def _value_is_already_redacted(value: Mapping[str, Any]) -> bool:
    redacted_value, _redacted_fields = redact_runtime_payload(dict(value))
    return _json_dump(redacted_value) == _json_dump(value)


def _path_size(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0


def _json_dump(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _json_load(value: str) -> dict[str, Any]:
    loaded = json.loads(value)
    return loaded if isinstance(loaded, dict) else {}


def _string_or_none(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _positive_int_or_zero(value: Any) -> int:
    return value if isinstance(value, int) and value > 0 else 0


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _env_optional_int(name: str, default: int | None) -> int | None:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    if raw.lower() in {"none", "off", "disabled", "0"}:
        return None
    try:
        return int(raw)
    except ValueError:
        return default


def _env_cleanup_interval_seconds(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    if raw.lower() in {"none", "off", "disabled", "0"}:
        return math.inf
    try:
        parsed = float(raw)
    except ValueError:
        return default
    return parsed if parsed > 0 else math.inf


def _env_age_seconds(name: str, default_days: int) -> int | None:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default_days * 24 * 60 * 60
    if raw.lower() in {"none", "off", "disabled", "0"}:
        return None
    try:
        return int(raw) * 24 * 60 * 60
    except ValueError:
        return default_days * 24 * 60 * 60


__all__ = [
    "DEFAULT_LEDGER_CLEANUP_INTERVAL_SECONDS",
    "DEFAULT_LEDGER_MAX_AGE_DAYS",
    "DEFAULT_LEDGER_MAX_BYTES",
    "DEFAULT_LEDGER_MAX_EVENTS",
    "DEFAULT_LEDGER_WRITER_BATCH_MAX_DELAY_SECONDS",
    "DEFAULT_LEDGER_WRITER_BATCH_MAX_EVENTS",
    "DEFAULT_LEDGER_WRITER_QUEUE_MAX_EVENTS",
    "DEFAULT_LEDGER_WRITER_SHUTDOWN_TIMEOUT_SECONDS",
    "ReplayResult",
    "RuntimeEventLedger",
    "RuntimeEventLedgerPolicy",
    "default_ledger_path",
    "get_runtime_event_ledger",
    "policy_from_env",
]
