"""Core shim coverage for extracted streaming-state helpers."""

from __future__ import annotations

from typing import Any

from penguin.core import PenguinCore


def test_core_streaming_state_shims_delegate_to_runtime(monkeypatch) -> None:
    core = PenguinCore.__new__(PenguinCore)
    calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []

    def _value(name: str, value: Any):
        def _inner(*args: Any, **kwargs: Any) -> Any:
            calls.append((name, args, kwargs))
            return value

        return _inner

    monkeypatch.setattr(
        "penguin.core.core_streaming_state.total_tokens_used",
        _value("total", 9),
    )
    monkeypatch.setattr(
        "penguin.core.core_streaming_state.streaming_active",
        _value("active", True),
    )
    monkeypatch.setattr(
        "penguin.core.core_streaming_state.streaming_content",
        _value("content", "text"),
    )
    monkeypatch.setattr(
        "penguin.core.core_streaming_state.streaming_reasoning_content",
        _value("reasoning", "why"),
    )
    monkeypatch.setattr(
        "penguin.core.core_streaming_state.streaming_stream_id",
        _value("stream_id", "stream_1"),
    )
    monkeypatch.setattr(
        "penguin.core.core_streaming_state.is_agent_streaming",
        _value("agent_active", False),
    )
    monkeypatch.setattr(
        "penguin.core.core_streaming_state.get_agent_streaming_content",
        _value("agent_content", "agent text"),
    )
    monkeypatch.setattr(
        "penguin.core.core_streaming_state.get_agent_streaming_reasoning",
        _value("agent_reasoning", "agent why"),
    )
    monkeypatch.setattr(
        "penguin.core.core_streaming_state.get_active_streaming_agents",
        _value("active_agents", ["worker"]),
    )
    monkeypatch.setattr(
        "penguin.core.core_streaming_state.cleanup_agent_streaming",
        _value("cleanup", None),
    )

    assert core.total_tokens_used == 9
    assert core.streaming_active is True
    assert core.streaming_content == "text"
    assert core.streaming_reasoning_content == "why"
    assert core.streaming_stream_id == "stream_1"
    assert core.is_agent_streaming("worker") is False
    assert core.get_agent_streaming_content("worker") == "agent text"
    assert core.get_agent_streaming_reasoning("worker") == "agent why"
    assert core.get_active_streaming_agents() == ["worker"]
    assert core.cleanup_agent_streaming("worker") is None

    assert [name for name, _, _ in calls] == [
        "total",
        "active",
        "content",
        "reasoning",
        "stream_id",
        "agent_active",
        "agent_content",
        "agent_reasoning",
        "active_agents",
        "cleanup",
    ]
    assert calls[0][1] == (core,)
    assert calls[5][1] == (core, "worker")
    assert calls[-1][1] == (core, "worker")
