"""Question flow manager for OpenCode-compatible interactive prompts.

This module mirrors the approval manager pattern for pending user questions.
It provides in-memory request tracking with reply/reject lifecycle handling.
"""

from __future__ import annotations

import asyncio
import logging
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable

logger = logging.getLogger(__name__)


class QuestionStatus(Enum):
    """Status of a question request."""

    PENDING = "pending"
    ANSWERED = "answered"
    REJECTED = "rejected"


@dataclass
class QuestionRequest:
    """Pending question request payload."""

    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    session_id: str = ""
    questions: list[dict[str, Any]] = field(default_factory=list)
    tool: dict[str, Any] | None = None
    context: dict[str, Any] = field(default_factory=dict)
    status: QuestionStatus = QuestionStatus.PENDING
    answers: list[list[str]] | None = None
    created_at: datetime = field(default_factory=datetime.utcnow)
    resolved_at: datetime | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialize to OpenCode-compatible API payload."""
        payload: dict[str, Any] = {
            "id": self.id,
            "sessionID": self.session_id,
            "questions": list(self.questions),
        }
        if isinstance(self.tool, dict):
            payload["tool"] = dict(self.tool)
        return payload


class QuestionManager:
    """Singleton manager for pending question requests."""

    _instance: QuestionManager | None = None
    _lock = threading.Lock()

    def __new__(cls) -> QuestionManager:
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if getattr(self, "_initialized", False):
            return

        self._pending: dict[str, QuestionRequest] = {}
        self._resolved: dict[str, QuestionRequest] = {}
        self._waiters: dict[str, list[asyncio.Future[QuestionRequest]]] = {}
        self._data_lock = threading.RLock()

        self._on_request_created: list[Callable[[QuestionRequest], None]] = []
        self._on_request_answered: list[Callable[[QuestionRequest], None]] = []
        self._on_request_rejected: list[Callable[[QuestionRequest], None]] = []

        self._initialized = True

    def reset(self) -> None:
        """Reset all manager state. Intended for tests."""
        with self._data_lock:
            self._pending.clear()
            self._resolved.clear()
            waiters = list(self._waiters.values())
            self._waiters.clear()

        for group in waiters:
            for waiter in group:
                if waiter.done():
                    continue
                waiter.cancel()

    def _notify_waiters(self, request: QuestionRequest) -> None:
        """Resolve any async waiters for a request."""
        with self._data_lock:
            waiters = self._waiters.pop(request.id, [])

        def _resolve_waiter(
            waiter: asyncio.Future[QuestionRequest],
            resolved: QuestionRequest,
        ) -> None:
            if waiter.done():
                return
            waiter.set_result(resolved)

        for waiter in waiters:
            if waiter.done():
                continue
            try:
                waiter.get_loop().call_soon_threadsafe(_resolve_waiter, waiter, request)
            except Exception:
                logger.debug("Question waiter notification failed", exc_info=True)

    def _remove_waiter(
        self,
        request_id: str,
        waiter: asyncio.Future[QuestionRequest],
    ) -> None:
        """Remove a waiter from tracking if still present."""
        with self._data_lock:
            waiters = self._waiters.get(request_id)
            if not isinstance(waiters, list):
                return
            kept = [existing for existing in waiters if existing is not waiter]
            if kept:
                self._waiters[request_id] = kept
                return
            self._waiters.pop(request_id, None)

    def create_request(
        self,
        *,
        session_id: str,
        questions: list[dict[str, Any]],
        tool: dict[str, Any] | None = None,
        context: dict[str, Any] | None = None,
    ) -> QuestionRequest:
        """Create a new pending question request."""
        request = QuestionRequest(
            session_id=session_id,
            questions=list(questions),
            tool=dict(tool) if isinstance(tool, dict) else None,
            context=dict(context or {}),
        )

        with self._data_lock:
            self._pending[request.id] = request
            self._waiters.setdefault(request.id, [])

        for callback in self._on_request_created:
            try:
                callback(request)
            except Exception:
                logger.debug("Question created callback failed", exc_info=True)

        return request

    def reply(
        self,
        request_id: str,
        answers: list[list[str]],
    ) -> QuestionRequest | None:
        """Resolve a question request with answers."""
        with self._data_lock:
            request = self._pending.pop(request_id, None)
            if request is None:
                return None
            request.status = QuestionStatus.ANSWERED
            request.answers = list(answers)
            request.resolved_at = datetime.utcnow()
            self._resolved[request_id] = request

        self._notify_waiters(request)

        for callback in self._on_request_answered:
            try:
                callback(request)
            except Exception:
                logger.debug("Question replied callback failed", exc_info=True)

        return request

    def reject(self, request_id: str) -> QuestionRequest | None:
        """Reject a pending question request."""
        with self._data_lock:
            request = self._pending.pop(request_id, None)
            if request is None:
                return None
            request.status = QuestionStatus.REJECTED
            request.resolved_at = datetime.utcnow()
            self._resolved[request_id] = request

        self._notify_waiters(request)

        for callback in self._on_request_rejected:
            try:
                callback(request)
            except Exception:
                logger.debug("Question rejected callback failed", exc_info=True)

        return request

    def list_pending(self, session_id: str | None = None) -> list[QuestionRequest]:
        """List pending question requests, optionally filtered by session."""
        with self._data_lock:
            if isinstance(session_id, str) and session_id:
                return [
                    request
                    for request in self._pending.values()
                    if request.session_id == session_id
                ]
            return list(self._pending.values())

    def get_request(self, request_id: str) -> QuestionRequest | None:
        """Get a request by ID from pending or resolved state."""
        with self._data_lock:
            if request_id in self._pending:
                return self._pending[request_id]
            return self._resolved.get(request_id)

    async def wait_for_resolution(
        self,
        request_id: str,
        timeout_seconds: float | None = None,
    ) -> QuestionRequest | None:
        """Wait for a pending question to be answered or rejected."""
        with self._data_lock:
            resolved = self._resolved.get(request_id)
            if resolved is not None:
                return resolved
            if request_id not in self._pending:
                return None

        loop = asyncio.get_running_loop()
        waiter: asyncio.Future[QuestionRequest] = loop.create_future()

        with self._data_lock:
            resolved = self._resolved.get(request_id)
            if resolved is not None:
                return resolved
            if request_id not in self._pending:
                return self._resolved.get(request_id)
            self._waiters.setdefault(request_id, []).append(waiter)

        try:
            if timeout_seconds is None:
                return await waiter
            return await asyncio.wait_for(waiter, timeout=timeout_seconds)
        except asyncio.TimeoutError:
            return None
        finally:
            self._remove_waiter(request_id, waiter)

    def on_request_created(self, callback: Callable[[QuestionRequest], None]) -> None:
        """Register callback for request creation."""
        self._on_request_created.append(callback)

    def on_request_answered(self, callback: Callable[[QuestionRequest], None]) -> None:
        """Register callback for answered requests."""
        self._on_request_answered.append(callback)

    def on_request_rejected(self, callback: Callable[[QuestionRequest], None]) -> None:
        """Register callback for rejected requests."""
        self._on_request_rejected.append(callback)


def get_question_manager() -> QuestionManager:
    """Get singleton question manager instance."""
    return QuestionManager()
