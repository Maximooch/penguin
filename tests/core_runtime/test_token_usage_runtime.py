"""Assault tests for token usage runtime helpers."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest
from hypothesis import given, strategies as st

from penguin.core_runtime import token_usage_runtime
from penguin.system.state import MessageCategory


class _ContextWindow:
    max_context_window_tokens = 100


class _ConversationManager:
    context_window = _ContextWindow()

    def __init__(self, usage: Any | None = None) -> None:
        self._usage = usage

    def get_token_usage(self) -> Any:
        return self._usage


class _Core:
    def __init__(
        self,
        *,
        session: Any | None = None,
        runtime_usage: Any | None = None,
    ) -> None:
        self.conversation_manager = _ConversationManager(runtime_usage)
        self.session = session

    def _find_session_store(self, session_id: str) -> tuple[Any | None, None]:
        if self.session is not None and self.session.id == session_id:
            return self.session, None
        return None, None

    def _usage_from_session_messages(
        self,
        session: Any,
        *,
        agent_id: str | None = None,
    ) -> dict[str, Any]:
        return token_usage_runtime.usage_from_session_messages(
            self,
            session,
            agent_id=agent_id,
        )


def _message(
    tokens: Any,
    category: Any = MessageCategory.DIALOG,
    *,
    agent_id: str | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(tokens=tokens, category=category, agent_id=agent_id)


def _session(
    session_id: str,
    *,
    messages: list[Any] | None = None,
    metadata: Any | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=session_id,
        messages=messages or [],
        metadata={} if metadata is None else metadata,
    )


def _expected_token_count(value: Any) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return 0
    return max(parsed, 0)


@given(
    token_values=st.lists(
        st.one_of(
            st.integers(min_value=-1_000, max_value=1_000),
            st.text(min_size=0, max_size=8),
            st.none(),
        ),
        max_size=25,
    )
)
def test_usage_from_session_messages_treats_corrupt_tokens_as_zero(
    token_values: list[Any],
) -> None:
    session = _session(
        "session_a",
        messages=[_message(value) for value in token_values],
    )

    usage = token_usage_runtime.usage_from_session_messages(_Core(), session)

    expected = sum(_expected_token_count(value) for value in token_values)
    assert usage["current_total_tokens"] == expected
    assert usage["available_tokens"] == max(100 - expected, 0)
    assert usage["categories"]["DIALOG"] == expected


@given(
    messages=st.lists(
        st.tuples(
            st.one_of(
                st.integers(min_value=-1_000, max_value=1_000),
                st.text(min_size=0, max_size=8),
                st.none(),
            ),
            st.sampled_from(["agent-a", "agent-b", None]),
            st.sampled_from([MessageCategory.DIALOG, MessageCategory.SYSTEM, "CUSTOM"]),
        ),
        max_size=30,
    )
)
def test_usage_from_session_messages_scopes_tokens_by_agent(
    messages: list[tuple[Any, str | None, Any]],
) -> None:
    session = _session(
        "session_a",
        messages=[
            _message(tokens, category=category, agent_id=agent_id)
            for tokens, agent_id, category in messages
        ],
    )

    usage = token_usage_runtime.usage_from_session_messages(
        _Core(),
        session,
        agent_id="agent-a",
    )

    expected_total = sum(
        _expected_token_count(tokens)
        for tokens, agent_id, _category in messages
        if agent_id == "agent-a"
    )
    expected_dialog = sum(
        _expected_token_count(tokens)
        for tokens, agent_id, category in messages
        if agent_id == "agent-a" and category == MessageCategory.DIALOG
    )
    expected_system = sum(
        _expected_token_count(tokens)
        for tokens, agent_id, category in messages
        if agent_id == "agent-a" and category == MessageCategory.SYSTEM
    )
    expected_custom = sum(
        _expected_token_count(tokens)
        for tokens, agent_id, category in messages
        if agent_id == "agent-a" and category == "CUSTOM"
    )

    assert usage["current_total_tokens"] == expected_total
    assert usage["available_tokens"] == max(100 - expected_total, 0)
    assert usage["categories"]["DIALOG"] == expected_dialog
    assert usage["categories"]["SYSTEM"] == expected_system
    assert usage["categories"].get("CUSTOM", 0) == expected_custom


def test_get_session_token_usage_does_not_let_metadata_owner_override_messages() -> (
    None
):
    session = _session(
        "session_a",
        messages=[_message(11, agent_id="agent-b")],
        metadata={
            "agent_id": "agent-a",
            "_opencode_usage_v1": {"current_total_tokens": 99},
        },
    )

    usage = token_usage_runtime.get_session_token_usage(
        _Core(session=session),
        "session_a",
        agent_id="agent-a",
    )

    assert usage == {
        "scope": "missing",
        "session_id": "session_a",
        "conversation_id": "session_a",
        "agent_id": "agent-a",
        "error": "agent token usage not found for session",
    }


def test_get_token_usage_returns_empty_runtime_payload_for_corrupt_runtime_usage() -> (
    None
):
    usage = token_usage_runtime.get_token_usage(_Core(runtime_usage=["bad"]))

    assert usage == {
        "scope": "runtime",
        "total": {"input": 0, "output": 0},
        "session": {"input": 0, "output": 0},
    }


def test_get_session_token_usage_falls_back_when_snapshot_metadata_is_corrupt() -> None:
    session = _session(
        "session_a",
        messages=[_message(7)],
        metadata={"_opencode_usage_v1": ["bad"]},
    )

    usage = token_usage_runtime.get_session_token_usage(
        _Core(session=session),
        "session_a",
    )

    assert usage is not None
    assert usage["scope"] == "session"
    assert usage["session_id"] == "session_a"
    assert usage["current_total_tokens"] == 7


def test_get_session_token_usage_does_not_mutate_persisted_usage_snapshot() -> None:
    snapshot = {
        "current_total_tokens": 12,
        "max_context_window_tokens": 100,
        "available_tokens": 88,
        "percentage": 12,
        "categories": {"DIALOG": 12},
        "truncations": {
            "total_truncations": 0,
            "messages_removed": 0,
            "tokens_freed": 0,
            "by_category": {},
            "recent_events": [],
        },
    }
    session = _session(
        "session_a",
        metadata={"agent_id": "agent-a", "_opencode_usage_v1": snapshot},
    )

    usage = token_usage_runtime.get_session_token_usage(
        _Core(session=session),
        "session_a",
        agent_id="agent-a",
    )

    assert usage is not None
    assert usage["scope"] == "session"
    assert "scope" not in snapshot
    assert "session_id" not in snapshot
    assert "agent_id" not in snapshot


@pytest.mark.asyncio
async def test_get_token_usage_ignores_failed_background_event_emission() -> None:
    usage_payload = {"total": {"input": 1, "output": 2}}
    core = _Core(runtime_usage=usage_payload)

    async def _emit_ui_event(_event_type: str, _payload: dict[str, Any]) -> None:
        raise RuntimeError("event bus unavailable")

    core.emit_ui_event = _emit_ui_event

    usage = token_usage_runtime.get_token_usage(core)
    await asyncio_sleep()

    assert usage == {"scope": "runtime", **usage_payload}


async def asyncio_sleep() -> None:
    await asyncio.sleep(0)
