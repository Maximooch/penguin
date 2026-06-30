"""Durable storage for public runtime event envelopes.

The ledger stores redacted public ``RuntimeEvent`` records for replay and
runtime observability. It is intentionally not the conversation transcript or a
private diagnostics store.
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional

from penguin.config import WORKSPACE_PATH
from penguin.system.runtime_events import RUNTIME_EVENT_SCHEMA_VERSION

DEFAULT_LEDGER_MAX_EVENTS = 100_000
DEFAULT_LEDGER_MAX_AGE_DAYS = 14
DEFAULT_LEDGER_MAX_BYTES = 256 * 1024 * 1024
DEFAULT_LEDGER_CLEANUP_INTERVAL_SECONDS = 60.0
_RUNTIME_EVENT_LEDGER_ATTR = "_runtime_event_ledger_v1"


@dataclass(frozen=True)
class RuntimeEventLedgerPolicy:
    """Retention and cleanup policy for the runtime event ledger."""

    max_events: int = DEFAULT_LEDGER_MAX_EVENTS
    max_age_seconds: Optional[int] = DEFAULT_LEDGER_MAX_AGE_DAYS * 24 * 60 * 60
    max_bytes: Optional[int] = DEFAULT_LEDGER_MAX_BYTES
    cleanup_interval_seconds: float = DEFAULT_LEDGER_CLEANUP_INTERVAL_SECONDS


@dataclass(frozen=True)
class ReplayResult:
    """Ledger replay lookup result."""

    found: bool
    events: list[dict[str, Any]]
    oldest_event_id: Optional[str] = None
    newest_event_id: Optional[str] = None


def default_ledger_path() -> Path:
    """Return the default on-disk SQLite path for runtime events."""
    override = os.getenv("PENGUIN_RUNTIME_EVENT_LEDGER_PATH")
    if override:
        return Path(override).expanduser()
    return Path(WORKSPACE_PATH).expanduser() / "runtime_events" / "runtime_events.db"


def policy_from_env() -> RuntimeEventLedgerPolicy:
    """Build a ledger policy from environment variables."""
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
        cleanup_interval_seconds=float(
            _env_optional_int(
                "PENGUIN_RUNTIME_EVENT_LEDGER_CLEANUP_INTERVAL_SECONDS",
                int(DEFAULT_LEDGER_CLEANUP_INTERVAL_SECONDS),
            )
            or 0
        ),
    )


def get_runtime_event_ledger(core: Optional[Any] = None) -> "RuntimeEventLedger":
    """Return the shared runtime event ledger for a core object or process."""
    if core is not None:
        existing = getattr(core, _RUNTIME_EVENT_LEDGER_ATTR, None)
        if isinstance(existing, RuntimeEventLedger):
            return existing
        ledger = RuntimeEventLedger(default_ledger_path(), policy=policy_from_env())
        setattr(core, _RUNTIME_EVENT_LEDGER_ATTR, ledger)
        return ledger

    global _PROCESS_LEDGER
    if _PROCESS_LEDGER is None:
        _PROCESS_LEDGER = RuntimeEventLedger(default_ledger_path(), policy=policy_from_env())
    return _PROCESS_LEDGER


class RuntimeEventLedger:
    """SQLite-backed append-only ledger for public runtime events."""

    def __init__(
        self,
        path: str | Path,
        *,
        policy: Optional[RuntimeEventLedgerPolicy] = None,
    ) -> None:
        self.path = Path(path).expanduser()
        self.policy = policy or RuntimeEventLedgerPolicy()
        self._lock = threading.RLock()
        self._last_cleanup = 0.0
        self._initialized = False

    def append(self, event: Mapping[str, Any]) -> bool:
        """Persist an event envelope if it has not already been stored."""
        event_id = event.get("id")
        if not isinstance(event_id, str) or not event_id:
            return False
        if not _looks_like_public_runtime_event(event):
            return False

        scope = event.get("scope")
        if not isinstance(scope, Mapping):
            scope = {}
        privacy = event.get("privacy")
        if not isinstance(privacy, Mapping):
            privacy = {}
        payload = event.get("payload")
        projections = event.get("projections")

        with self._lock:
            conn = self._connect()
            try:
                self._ensure_schema(conn)
                before_changes = conn.total_changes
                conn.execute(
                    """
                    INSERT OR IGNORE INTO runtime_events (
                        event_id,
                        stream_id,
                        sequence,
                        event_type,
                        category,
                        event_time,
                        inserted_at,
                        session_id,
                        conversation_id,
                        agent_id,
                        task_id,
                        run_id,
                        project_id,
                        directory,
                        privacy_classification,
                        redacted,
                        payload_json,
                        projection_json,
                        event_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        event_id,
                        _string_or_none(event.get("stream_id")) or "global",
                        _positive_int_or_zero(event.get("sequence")),
                        _string_or_none(event.get("type")) or "unknown",
                        _string_or_none(event.get("category")) or "session_lifecycle",
                        _positive_int_or_zero(event.get("time")),
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
                        _json_dump(payload if isinstance(payload, Mapping) else {}),
                        _json_dump(
                            projections if isinstance(projections, Mapping) else {}
                        ),
                        _json_dump(dict(event)),
                    ),
                )
                conn.commit()
                inserted = conn.total_changes > before_changes
                self.cleanup_if_due(conn=conn)
                return inserted
            finally:
                conn.close()

    def extend(self, events: Iterable[Mapping[str, Any]]) -> int:
        """Persist multiple events and return the number of accepted rows."""
        accepted = 0
        for event in events:
            if self.append(event):
                accepted += 1
        return accepted

    def contains(self, event_id: str) -> bool:
        """Return whether an event id exists in the ledger."""
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
        limit: Optional[int] = None,
    ) -> ReplayResult:
        """Return events after ``last_event_id`` in durable insertion order."""
        if not isinstance(last_event_id, str) or not last_event_id:
            return ReplayResult(found=False, events=[], **self.bounds())

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

                sql = """
                    SELECT event_json
                    FROM runtime_events
                    WHERE rowid > ?
                    ORDER BY rowid ASC
                """
                if limit is not None and limit > 0:
                    sql += " LIMIT ?"
                    params = (cursor_row["rowid"], limit)
                else:
                    params = (cursor_row["rowid"],)
                rows = conn.execute(sql, params).fetchall()
                return ReplayResult(
                    found=True,
                    events=[_json_load(row["event_json"]) for row in rows],
                    **bounds,
                )
            finally:
                conn.close()

    def newest(self, *, limit: int = 100) -> list[dict[str, Any]]:
        """Return the newest events in insertion order."""
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

    def bounds(self, *, conn: Optional[sqlite3.Connection] = None) -> dict[str, Optional[str]]:
        """Return oldest/newest event ids currently retained."""
        owns_connection = conn is None
        if conn is None:
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

    def cleanup_if_due(self, *, conn: Optional[sqlite3.Connection] = None) -> None:
        """Run throttled retention cleanup."""
        now = time.monotonic()
        if (
            self.policy.cleanup_interval_seconds > 0
            and now - self._last_cleanup < self.policy.cleanup_interval_seconds
        ):
            return
        self.cleanup(conn=conn)
        self._last_cleanup = now

    def cleanup(self, *, conn: Optional[sqlite3.Connection] = None) -> None:
        """Apply max-events, max-age, and soft max-size retention rules."""
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
        current_size = self._database_size_bytes(conn)
        if current_size <= max_bytes:
            return

        low_water = int(max_bytes * 0.9)
        while current_size > low_water:
            count = conn.execute(
                "SELECT COUNT(*) AS count FROM runtime_events"
            ).fetchone()["count"]
            if int(count) <= 0:
                break
            batch = max(1, min(1000, int(count) // 10 or 1))
            conn.execute(
                """
                DELETE FROM runtime_events
                WHERE rowid IN (
                    SELECT rowid FROM runtime_events ORDER BY rowid ASC LIMIT ?
                )
                """,
                (batch,),
            )
            conn.commit()
            current_size = self._database_size_bytes(conn)
            if int(count) <= batch:
                break
        try:
            conn.execute("PRAGMA incremental_vacuum")
        except sqlite3.DatabaseError:
            pass

    def _database_size_bytes(self, conn: sqlite3.Connection) -> int:
        page_count = conn.execute("PRAGMA page_count").fetchone()[0]
        page_size = conn.execute("PRAGMA page_size").fetchone()[0]
        return int(page_count) * int(page_size)

    def _connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.path), timeout=30.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=30000")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA auto_vacuum=INCREMENTAL")
        return conn

    def _ensure_schema(self, conn: sqlite3.Connection) -> None:
        if self._initialized:
            return
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
        conn.commit()
        self._initialized = True


_PROCESS_LEDGER: Optional[RuntimeEventLedger] = None


def _looks_like_public_runtime_event(event: Mapping[str, Any]) -> bool:
    schema = event.get("schema_version")
    if schema != RUNTIME_EVENT_SCHEMA_VERSION:
        return False
    event_type = event.get("type")
    event_id = event.get("id")
    payload = event.get("payload")
    return (
        isinstance(event_type, str)
        and bool(event_type)
        and isinstance(event_id, str)
        and bool(event_id)
        and isinstance(payload, Mapping)
    )


def _json_dump(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _json_load(value: str) -> dict[str, Any]:
    loaded = json.loads(value)
    return loaded if isinstance(loaded, dict) else {}


def _string_or_none(value: Any) -> Optional[str]:
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


def _env_optional_int(name: str, default: Optional[int]) -> Optional[int]:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    if raw.lower() in {"none", "off", "disabled", "0"}:
        return None
    try:
        return int(raw)
    except ValueError:
        return default


def _env_age_seconds(name: str, default_days: int) -> Optional[int]:
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
    "ReplayResult",
    "RuntimeEventLedger",
    "RuntimeEventLedgerPolicy",
    "default_ledger_path",
    "get_runtime_event_ledger",
    "policy_from_env",
]
