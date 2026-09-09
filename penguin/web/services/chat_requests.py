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
from fastapi.encoders import jsonable_encoder

from penguin.system.task_cancellation import (
    CancellationTrackingTask,
    preserve_cancellation,
    task_abort_reason,
)

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
                    http_error TEXT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (session_id, request_id)
                )"""
            )
            columns = {
                row["name"] for row in db.execute("PRAGMA table_info(chat_requests)")
            }
            if "http_error" not in columns:
                try:
                    db.execute("ALTER TABLE chat_requests ADD COLUMN http_error TEXT")
                except sqlite3.OperationalError:
                    # Another process may have migrated this version-1 store.
                    columns = {
                        row["name"]
                        for row in db.execute("PRAGMA table_info(chat_requests)")
                    }
                    if "http_error" not in columns:
                        raise

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
        self,
        session_id: str,
        request_id: str,
        response: dict[str, Any],
        *,
        http_error: dict[str, Any] | None = None,
    ) -> None:
        """Persist the first authoritative HTTP result without overwriting it."""
        encoded = json.dumps(jsonable_encoder(response), allow_nan=False)
        with closing(self._connect()) as db, db:
            db.execute(
                "UPDATE chat_requests SET response=?, http_error=?, "
                "updated_at=CURRENT_TIMESTAMP "
                "WHERE session_id=? AND request_id=? AND response IS NULL",
                (
                    encoded,
                    json.dumps(http_error) if http_error else None,
                    session_id,
                    request_id,
                ),
            )

    def lookup(self, session_id: str, request_id: str) -> dict[str, Any]:
        """Read durable acceptance independently of live process ownership."""
        with closing(self._connect()) as db:
            row = db.execute(
                "SELECT response, http_error FROM chat_requests "
                "WHERE session_id=? AND request_id=?",
                (session_id, request_id),
            ).fetchone()
        if row is None:
            return {"state": "absent"}
        if row["response"] is None:
            return {"state": "accepted"}
        receipt = {"state": "completed", "response": json.loads(row["response"])}
        if row["http_error"] is not None:
            receipt["http_error"] = json.loads(row["http_error"])
        return receipt


def get_chat_request_store(core: Any) -> ChatRequestStore:
    """Resolve durable storage from the runtime workspace, not request paths."""
    from penguin.config import WORKSPACE_PATH

    workspace = getattr(getattr(core, "config", None), "workspace_path", None)
    return ChatRequestStore(Path(workspace or WORKSPACE_PATH) / "chat-requests.sqlite3")


async def execute_chat_request(
    get_store: Callable[[], ChatRequestStore],
    session_id: str,
    request_id: str,
    payload: dict[str, Any],
    execute: Callable[[], Awaitable[dict[str, Any]]],
) -> dict[str, Any]:
    """Execute only the durable claim winner, independent of HTTP observation."""

    async def run() -> dict[str, Any]:
        # Own initialization and acceptance before either can yield. A lost HTTP
        # observer must not strand a committed claim before execution starts.
        store = await asyncio.to_thread(get_store)
        if not await asyncio.to_thread(store.accept, session_id, request_id, payload):
            receipt = await asyncio.to_thread(store.lookup, session_id, request_id)
            if receipt["state"] == "completed":
                if "http_error" in receipt:
                    raise HTTPException(
                        status_code=receipt["http_error"]["status_code"],
                        detail=receipt["response"]["detail"],
                        headers=receipt["http_error"]["headers"],
                    )
                return receipt["response"]
            return {
                "status": "recovering",
                "request_state": "accepted",
                "session_id": session_id,
            }

        task = asyncio.current_task()
        assert isinstance(task, CancellationTrackingTask)
        preserve_cancellation.set(True)
        failure: HTTPException | None = None
        try:
            response = await task.run_child(execute())
        except HTTPException as exc:
            failure = exc
            response = {"detail": exc.detail}
        except asyncio.CancelledError:
            if task_abort_reason(task) is None:
                raise
            response = {}
        reason = task_abort_reason(task)
        if reason is not None:
            failure = None
            response = {
                "response": "",
                "action_results": [],
                "aborted": True,
                "status": "stopped",
                "abort_reason": reason.value,
                "session_id": session_id,
            }
        elif task.cancellation_requested:
            # core.process may swallow CancelledError. Shutdown is still uncertain.
            raise asyncio.CancelledError
        # Cancelling this await cannot stop a write already running in a thread.
        # The classified result may still commit; lookup remains authoritative.
        await asyncio.to_thread(
            store.complete,
            session_id,
            request_id,
            response,
            http_error=(
                {"status_code": failure.status_code, "headers": failure.headers}
                if failure
                else None
            ),
        )
        if failure:
            raise failure
        return response

    task = CancellationTrackingTask(
        run(), name=f"chat-request:{session_id}:{request_id}"
    )
    _tasks.add(task)

    def finished(done: asyncio.Task[dict[str, Any]]) -> None:
        _tasks.discard(done)
        if (
            not done.cancelled()
            and done.exception() is not None
            and not isinstance(done.exception(), HTTPException)
        ):
            logger.error(
                "Durable chat request failed; inspect its receipt state",
                exc_info=done.exception(),
            )

    task.add_done_callback(finished)
    return await asyncio.shield(task)
