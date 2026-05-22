from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import HTTPException

from penguin.core import PenguinCore
from penguin.system.state import Message, MessageCategory, Session
from penguin.web.routes import get_session_token_usage, get_token_usage


class _Manager:
    def __init__(self, sessions: list[Session]) -> None:
        self.sessions = {session.id: (session, False) for session in sessions}
        self.session_index = {
            session.id: {"token_count": session.total_tokens} for session in sessions
        }

    def load_session(self, session_id: str) -> Session | None:
        item = self.sessions.get(session_id)
        if item is None:
            return None
        return item[0]


class _ContextWindow:
    max_context_window_tokens = 200_000


class _ConversationManager:
    def __init__(self, sessions: list[Session]) -> None:
        self.context_window = _ContextWindow()
        self.session_manager = _Manager(sessions)
        self.agent_session_managers: dict[str, Any] = {}

    def get_token_usage(self) -> dict[str, Any]:
        return {
            "current_total_tokens": 99_000,
            "max_context_window_tokens": 200_000,
            "available_tokens": 101_000,
            "percentage": 49.5,
            "categories": {"DIALOG": 99_000},
            "truncations": {
                "total_truncations": 4,
                "messages_removed": 47,
                "tokens_freed": 67_000,
                "by_category": {},
                "recent_events": [],
            },
        }


def _message(category: MessageCategory, tokens: int) -> Message:
    return Message(role="user", content="x", category=category, tokens=tokens)


def _session(session_id: str, tokens: int) -> Session:
    session = Session(id=session_id)
    session.messages.append(_message(MessageCategory.DIALOG, tokens))
    return session


def _core(sessions: list[Session]) -> Any:
    core = SimpleNamespace()

    core.conversation_manager = _ConversationManager(sessions)
    core._find_session_store = PenguinCore._find_session_store.__get__(core)
    core._get_session_token_usage = PenguinCore._get_session_token_usage.__get__(core)
    usage_from_messages = PenguinCore._usage_from_session_messages
    core._usage_from_session_messages = usage_from_messages.__get__(core)
    core.get_token_usage = PenguinCore.get_token_usage.__get__(core)
    return core


@pytest.mark.asyncio
async def test_token_usage_query_is_session_scoped_without_runtime_bleed() -> None:
    session_a = _session("session_a", 70_000)
    session_a.metadata["_opencode_usage_v1"] = {
        "current_total_tokens": 70_000,
        "max_context_window_tokens": 200_000,
        "available_tokens": 130_000,
        "percentage": 35.0,
        "categories": {"DIALOG": 70_000},
        "truncations": {
            "total_truncations": 2,
            "messages_removed": 47,
            "tokens_freed": 67_000,
            "by_category": {},
            "recent_events": [],
        },
    }
    session_b = _session("session_b", 123)

    response = await get_token_usage(
        session_id="session_b",
        conversation_id=None,
        agent_id=None,
        core=_core([session_a, session_b]),
    )

    usage = response["usage"]
    assert usage["scope"] == "session"
    assert usage["session_id"] == "session_b"
    assert usage["current_total_tokens"] == 123
    assert usage["truncations"]["messages_removed"] == 0
    assert usage["truncations"]["tokens_freed"] == 0


@pytest.mark.asyncio
async def test_token_usage_without_session_is_marked_runtime() -> None:
    response = await get_token_usage(
        session_id=None,
        conversation_id=None,
        agent_id=None,
        core=_core([_session("session_a", 10)]),
    )

    usage = response["usage"]
    assert usage["scope"] == "runtime"
    assert usage["truncations"]["messages_removed"] == 47


@pytest.mark.asyncio
async def test_session_token_usage_path_returns_404_for_missing_session() -> None:
    with pytest.raises(HTTPException) as exc:
        await get_session_token_usage(
            "missing_session",
            conversation_id=None,
            agent_id=None,
            core=_core([]),
        )

    assert exc.value.status_code == 404
    assert exc.value.detail["scope"] == "missing"
