"""Durable acceptance receipts for Link chat requests.

An accepted receipt never expires. Losing a process does not authorize replay of
possibly executed tools. In that case the receipt remains recovering until an
authoritative result can be reconciled.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import TYPE_CHECKING, Any

from fastapi import HTTPException

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

__all__ = ["ChatRequestStore", "execute_chat_request", "get_chat_request_store"]

logger = logging.getLogger(__name__)
_tasks: set[asyncio.Task[dict[str, Any]]] = set()


class ChatRequestStore:
    """Persist request identity and results with cross-process uniqueness."""

    def __init__(self, path: Path) -> None:
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as db, db:
            db.execute(
                """CREATE TABLE IF NOT EXISTS chat_requests (
                    session_id TEXT NOT NULL,
                    request_id TEXT NOT NULL,
                    fingerprint TEXT NOT NULL,
                    response TEXT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (session_id, request_id)
                )"""
            )

    def _connect(self) -> sqlite3.Connection:
        """Open a short-lived connection with durable SQLite commits."""
        db = sqlite3.connect(self.path)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA synchronous = FULL")
        return db

    def accept(self, session_id: str, request_id: str, payload: dict[str, Any]) -> bool:
        """Claim a new request, or reject conflicting reuse before execution."""
        fingerprint = hashlib.sha256(
            json.dumps(
                payload, sort_keys=True, separators=(",", ":"), allow_nan=False
            ).encode("utf-8")
        ).hexdigest()
        with closing(self._connect()) as db, db:
            inserted = db.execute(
                "INSERT INTO chat_requests (session_id, request_id, fingerprint) "
                "VALUES (?, ?, ?) ON CONFLICT DO NOTHING",
                (session_id, request_id, fingerprint),
            ).rowcount
            row = db.execute(
                "SELECT fingerprint FROM chat_requests "
                "WHERE session_id=? AND request_id=?",
                (session_id, request_id),
            ).fetchone()
            if row["fingerprint"] != fingerprint:
                raise HTTPException(409, "CHAT_REQUEST_IDEMPOTENCY_CONFLICT")
            return inserted == 1

    def complete(
        self, session_id: str, request_id: str, response: dict[str, Any]
    ) -> None:
        """Persist the first authoritative HTTP result without overwriting it."""
        encoded = json.dumps(response, allow_nan=False)
        with closing(self._connect()) as db, db:
            db.execute(
                "UPDATE chat_requests SET response=?, updated_at=CURRENT_TIMESTAMP "
                "WHERE session_id=? AND request_id=? AND response IS NULL",
                (encoded, session_id, request_id),
            )

    def lookup(self, session_id: str, request_id: str) -> dict[str, Any]:
        """Read durable acceptance independently of live process ownership."""
        with closing(self._connect()) as db:
            row = db.execute(
                "SELECT response FROM chat_requests "
                "WHERE session_id=? AND request_id=?",
                (session_id, request_id),
            ).fetchone()
        if row is None:
            return {"state": "absent"}
        if row["response"] is None:
            return {"state": "accepted"}
        return {"state": "completed", "response": json.loads(row["response"])}


def get_chat_request_store(core: Any) -> ChatRequestStore:
    """Resolve durable storage from the runtime workspace, not request paths."""
    from penguin.config import WORKSPACE_PATH

    workspace = getattr(getattr(core, "config", None), "workspace_path", None)
    return ChatRequestStore(Path(workspace or WORKSPACE_PATH) / "chat-requests.sqlite3")


async def execute_chat_request(
    store: ChatRequestStore,
    session_id: str,
    request_id: str,
    payload: dict[str, Any],
    execute: Callable[[], Awaitable[dict[str, Any]]],
) -> dict[str, Any]:
    """Execute only the durable claim winner, independent of HTTP observation."""
    if not store.accept(session_id, request_id, payload):
        receipt = store.lookup(session_id, request_id)
        if receipt["state"] == "completed":
            return receipt["response"]
        return {
            "status": "recovering",
            "request_state": "accepted",
            "session_id": session_id,
        }

    async def run() -> dict[str, Any]:
        response = await execute()
        store.complete(session_id, request_id, response)
        return response

    task = asyncio.create_task(run(), name=f"chat-request:{session_id}:{request_id}")
    _tasks.add(task)

    def finished(done: asyncio.Task[dict[str, Any]]) -> None:
        _tasks.discard(done)
        if not done.cancelled() and done.exception() is not None:
            logger.error(
                "Chat request remains accepted without a result",
                exc_info=done.exception(),
            )

    task.add_done_callback(finished)
    return await asyncio.shield(task)
