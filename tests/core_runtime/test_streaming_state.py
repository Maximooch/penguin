"""Tests for streaming-state core runtime accessors."""

from __future__ import annotations

from types import SimpleNamespace

from penguin.core_runtime import streaming_state


class _StreamManager:
    is_active = True
    content = "assistant"
    reasoning_content = "reasoning"
    stream_id = "stream_1"

    def __init__(self) -> None:
        self.cleaned: list[str] = []

    def is_agent_active(self, agent_id: str) -> bool:
        return agent_id == "worker"

    def get_agent_content(self, agent_id: str) -> str:
        return f"content:{agent_id}"

    def get_agent_reasoning(self, agent_id: str) -> str:
        return f"reasoning:{agent_id}"

    def get_active_agents(self) -> list[str]:
        return ["default", "worker"]

    def cleanup_agent(self, agent_id: str) -> None:
        self.cleaned.append(agent_id)


def test_streaming_state_accessors_delegate_to_stream_manager() -> None:
    manager = _StreamManager()
    core = SimpleNamespace(_stream_manager=manager)

    assert streaming_state.streaming_active(core) is True
    assert streaming_state.streaming_content(core) == "assistant"
    assert streaming_state.streaming_reasoning_content(core) == "reasoning"
    assert streaming_state.streaming_stream_id(core) == "stream_1"
    assert streaming_state.is_agent_streaming(core, "worker") is True
    assert streaming_state.is_agent_streaming(core, "other") is False
    assert streaming_state.get_agent_streaming_content(core, "worker") == (
        "content:worker"
    )
    assert streaming_state.get_agent_streaming_reasoning(core, "worker") == (
        "reasoning:worker"
    )
    assert streaming_state.get_active_streaming_agents(core) == ["default", "worker"]

    streaming_state.cleanup_agent_streaming(core, "worker")

    assert manager.cleaned == ["worker"]


def test_total_tokens_used_reads_total_and_fails_closed() -> None:
    core = SimpleNamespace(
        conversation_manager=SimpleNamespace(
            get_token_usage=lambda: {"total": 42, "session": 7}
        )
    )
    failing_core = SimpleNamespace(
        conversation_manager=SimpleNamespace(
            get_token_usage=lambda: (_ for _ in ()).throw(RuntimeError("boom"))
        )
    )

    assert streaming_state.total_tokens_used(core) == 42
    assert streaming_state.total_tokens_used(failing_core) == 0
