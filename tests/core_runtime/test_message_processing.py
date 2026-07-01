"""Tests for single-message processing helpers."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest

from penguin.core_runtime import message_processing


class _ConversationManager:
    def __init__(self) -> None:
        self.context_entries: list[str] = []
        self.process_message = AsyncMock(return_value="done")

    def add_context(self, value: str) -> None:
        self.context_entries.append(value)


@pytest.mark.asyncio
async def test_process_message_adds_context_and_delegates_to_manager() -> None:
    owner = SimpleNamespace()
    conversation_manager = _ConversationManager()
    resolver_calls: list[dict[str, Any]] = []

    def resolve_conversation_manager(core: Any, agent_id: str | None, **kwargs: Any):
        resolver_calls.append({"core": core, "agent_id": agent_id, **kwargs})
        return conversation_manager

    result = await message_processing.process_message(
        owner,
        message="hello",
        context={"project": "Penguin", "priority": "high"},
        conversation_id="conversation-1",
        agent_id="agent-1",
        context_files=["README.md"],
        streaming=True,
        resolve_conversation_manager=resolve_conversation_manager,
        log_error=lambda *_args, **_kwargs: None,
        log="logger",
    )

    assert result == "done"
    assert resolver_calls == [{"core": owner, "agent_id": "agent-1", "log": "logger"}]
    assert conversation_manager.context_entries == [
        "project: Penguin",
        "priority: high",
    ]
    conversation_manager.process_message.assert_awaited_once_with(
        message="hello",
        conversation_id="conversation-1",
        streaming=True,
        context_files=["README.md"],
    )


@pytest.mark.asyncio
async def test_process_message_logs_and_returns_error_text_on_failure() -> None:
    owner = SimpleNamespace()
    logged_errors: list[dict[str, Any]] = []

    def resolve_conversation_manager(*_args: Any, **_kwargs: Any) -> Any:
        raise RuntimeError("manager unavailable")

    def record_error(exc: BaseException, **kwargs: Any) -> None:
        logged_errors.append({"exc": exc, **kwargs})

    result = await message_processing.process_message(
        owner,
        message="hello",
        context=None,
        conversation_id=None,
        agent_id=None,
        context_files=None,
        streaming=False,
        resolve_conversation_manager=resolve_conversation_manager,
        log_error=record_error,
        log="logger",
    )

    assert result == "Error processing message: manager unavailable"
    assert str(logged_errors[0]["exc"]) == "manager unavailable"
    assert logged_errors[0]["context"] == {
        "component": "core",
        "method": "process_message",
        "message": "hello",
    }
