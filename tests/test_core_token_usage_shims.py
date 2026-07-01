"""Core shim coverage for extracted token usage helpers."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from penguin.core import PenguinCore


def test_update_token_display_delegates_to_runtime(monkeypatch) -> None:
    core = PenguinCore.__new__(PenguinCore)
    calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []

    def _emit_token_display_update(*args: Any, **kwargs: Any) -> None:
        calls.append((args, kwargs))

    facade_globals = PenguinCore.update_token_display.__globals__
    monkeypatch.setattr(
        facade_globals["core_token_usage_runtime"],
        "emit_token_display_update",
        _emit_token_display_update,
    )

    core.update_token_display()

    assert len(calls) == 1
    args, kwargs = calls[0]
    assert args == (core,)
    assert sorted(kwargs) == ["log"]


def test_token_usage_facade_shims_delegate_to_runtime(monkeypatch) -> None:
    owner = SimpleNamespace()
    session = SimpleNamespace(id="session_a")
    calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []

    facade_globals = PenguinCore.get_token_usage.__globals__
    token_usage_runtime = facade_globals["core_token_usage_runtime"]

    def fake_get_token_usage(
        core: Any,
        *,
        session_id: str | None = None,
        conversation_id: str | None = None,
        agent_id: str | None = None,
    ) -> dict[str, Any]:
        calls.append(
            (
                "get_token_usage",
                (core,),
                {
                    "session_id": session_id,
                    "conversation_id": conversation_id,
                    "agent_id": agent_id,
                },
            )
        )
        return {"scope": "session"}

    def fake_get_session_token_usage(
        core: Any,
        session_id: str,
        *,
        conversation_id: str | None = None,
        agent_id: str | None = None,
    ) -> dict[str, Any]:
        calls.append(
            (
                "get_session_token_usage",
                (core, session_id),
                {"conversation_id": conversation_id, "agent_id": agent_id},
            )
        )
        return {"session_id": session_id}

    def fake_usage_from_session_messages(
        core: Any,
        session: Any,
        *,
        agent_id: str | None = None,
    ) -> dict[str, Any]:
        calls.append(
            (
                "usage_from_session_messages",
                (core, session),
                {"agent_id": agent_id},
            )
        )
        return {"current_total_tokens": 7}

    monkeypatch.setattr(token_usage_runtime, "get_token_usage", fake_get_token_usage)
    monkeypatch.setattr(
        token_usage_runtime,
        "get_session_token_usage",
        fake_get_session_token_usage,
    )
    monkeypatch.setattr(
        token_usage_runtime,
        "usage_from_session_messages",
        fake_usage_from_session_messages,
    )

    assert PenguinCore.get_token_usage(
        owner,
        session_id="session_a",
        conversation_id="conversation_a",
        agent_id="agent_a",
    ) == {"scope": "session"}
    assert PenguinCore._get_session_token_usage(
        owner,
        "session_a",
        conversation_id="conversation_a",
        agent_id="agent_a",
    ) == {"session_id": "session_a"}
    assert PenguinCore._usage_from_session_messages(
        owner,
        session,
        agent_id="agent_a",
    ) == {"current_total_tokens": 7}

    assert calls == [
        (
            "get_token_usage",
            (owner,),
            {
                "session_id": "session_a",
                "conversation_id": "conversation_a",
                "agent_id": "agent_a",
            },
        ),
        (
            "get_session_token_usage",
            (owner, "session_a"),
            {"conversation_id": "conversation_a", "agent_id": "agent_a"},
        ),
        (
            "usage_from_session_messages",
            (owner, session),
            {"agent_id": "agent_a"},
        ),
    ]
