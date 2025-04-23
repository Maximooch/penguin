"""SnapshotManager – lightweight persistence layer for conversation snapshots.

Stores complete serialisations of `ConversationSystem` state (usually a single
`Session` object) in a local SQLite database so we can *snapshot* the current
state, *restore* any previous state, and *branch* off a historical snapshot to
create an alternate timeline.

The contract purposefully remains minimal – a single table with the following
columns:

    id         TEXT – primary‑key UUIDv4 string
    parent_id  TEXT – optional UUIDv4 pointing at the snapshot this one was
                         branched from (NULL for root snapshots)
    timestamp  TEXT – ISO‑8601 UTC timestamp
    payload    BLOB – raw JSON string of the serialised conversation state
    meta       TEXT – optional JSON string for extra metadata (UI notes, etc.)

All operations are synchronous because snapshots are small (<10 kB) and happen
infrequently compared to token streaming.  If you need async, wrap calls in
`asyncio.to_thread` from the caller.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import logging

logger = logging.getLogger(__name__)


class SnapshotManager:
    """Thin wrapper around an on‑disk SQLite DB for snapshot CRUD."""

    _SCHEMA_SQL = (
        "CREATE TABLE IF NOT EXISTS snapshots ("
        "id TEXT PRIMARY KEY,"
        "parent_id TEXT,"
        "timestamp TEXT NOT NULL,"
        "payload BLOB NOT NULL,"
        "meta TEXT"
        ")"
    )

    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        # Use check_same_thread False so callers from different threads work.
        self.conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self.conn.execute("PRAGMA journal_mode=WAL")
        self._ensure_schema()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def snapshot(self, payload: str, *, parent_id: Optional[str] = None, meta: Optional[Dict[str, Any]] = None) -> str:
        """Persist *payload* and return the newly generated snapshot_id."""
        snap_id = uuid.uuid4().hex  # shorter than full UUID string
        timestamp = datetime.utcnow().isoformat()
        meta_json = json.dumps(meta or {})
        with self.conn:  # implicit transaction
            self.conn.execute(
                "INSERT INTO snapshots (id, parent_id, timestamp, payload, meta) VALUES (?, ?, ?, ?, ?)",
                (snap_id, parent_id, timestamp, payload, meta_json),
            )
        logger.debug("Created snapshot %s (parent=%s, %d bytes)", snap_id, parent_id, len(payload))
        return snap_id

    def restore(self, snapshot_id: str) -> Optional[str]:
        """Return *payload* string for *snapshot_id* or ``None`` if not found."""
        cur = self.conn.execute("SELECT payload FROM snapshots WHERE id = ?", (snapshot_id,))
        row = cur.fetchone()
        if row is None:
            logger.warning("Snapshot %s not found", snapshot_id)
            return None
        return row[0]

    def branch_from(self, snapshot_id: str, *, meta: Optional[Dict[str, Any]] = None) -> Tuple[str, str]:
        """Create **child** snapshot duplicating *snapshot_id*'s payload.

        Returns ``(new_snapshot_id, payload)`` so caller can immediately hydrate
        a new conversation instance.
        """
        payload = self.restore(snapshot_id)
        if payload is None:
            raise ValueError(f"Cannot branch – snapshot {snapshot_id} not found")
        new_id = self.snapshot(payload, parent_id=snapshot_id, meta=meta)
        return new_id, payload

    def list_snapshots(self, *, limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
        cur = self.conn.execute(
            "SELECT id, parent_id, timestamp, json_extract(meta, '$.name') as name FROM snapshots ORDER BY timestamp DESC LIMIT ? OFFSET ?",
            (limit, offset),
        )
        rows = cur.fetchall()
        return [
            {"id": r[0], "parent_id": r[1], "timestamp": r[2], "name": r[3]} for r in rows
        ]

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _ensure_schema(self):
        with self.conn:
            self.conn.execute(self._SCHEMA_SQL) 