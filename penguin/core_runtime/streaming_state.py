"""Streaming and token state accessors for core-like owners."""

from __future__ import annotations

from typing import Any

__all__ = [
    "cleanup_agent_streaming",
    "get_active_streaming_agents",
    "get_agent_streaming_content",
    "get_agent_streaming_reasoning",
    "is_agent_streaming",
    "streaming_active",
    "streaming_content",
    "streaming_reasoning_content",
    "streaming_stream_id",
    "total_tokens_used",
]


def total_tokens_used(core: Any) -> int:
    """Return total token usage from the conversation manager."""
    try:
        token_usage = core.conversation_manager.get_token_usage()
        return token_usage.get("total", 0)
    except Exception:
        return 0


def streaming_active(core: Any) -> bool:
    """Return whether the default agent stream is active."""
    return core._stream_manager.is_active


def streaming_content(core: Any) -> str:
    """Return accumulated default-agent stream content."""
    return core._stream_manager.content


def streaming_reasoning_content(core: Any) -> str:
    """Return accumulated default-agent reasoning stream content."""
    return core._stream_manager.reasoning_content


def streaming_stream_id(core: Any) -> str | None:
    """Return the default-agent stream id, if active."""
    return core._stream_manager.stream_id


def is_agent_streaming(core: Any, agent_id: str) -> bool:
    """Return whether one agent has an active stream."""
    return core._stream_manager.is_agent_active(agent_id)


def get_agent_streaming_content(core: Any, agent_id: str) -> str:
    """Return accumulated stream content for one agent."""
    return core._stream_manager.get_agent_content(agent_id)


def get_agent_streaming_reasoning(core: Any, agent_id: str) -> str:
    """Return accumulated reasoning stream content for one agent."""
    return core._stream_manager.get_agent_reasoning(agent_id)


def get_active_streaming_agents(core: Any) -> list[str]:
    """Return agent ids with active streams."""
    return core._stream_manager.get_active_agents()


def cleanup_agent_streaming(core: Any, agent_id: str) -> None:
    """Clean up streaming state for one agent."""
    core._stream_manager.cleanup_agent(agent_id)
