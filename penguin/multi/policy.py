"""Server-authoritative policy for multi-agent tool availability."""

from __future__ import annotations

from typing import Any, Mapping

from penguin.system.execution_context import get_current_execution_context

SUBAGENT_TOOL_NAMES = frozenset(
    {
        "delegate",
        "delegate_explore_task",
        "get_agent_status",
        "get_context_info",
        "resume_sub_agent",
        "send_message",
        "spawn_sub_agent",
        "stop_sub_agent",
        "sync_context",
        "wait_for_agents",
    }
)


def subagents_enabled(
    context: Mapping[str, Any] | None = None,
    *,
    default: bool = True,
) -> bool:
    """Return whether subagent capabilities are enabled for this request.

    Args:
        context: Optional explicit execution-context mapping.
        default: Value used when no request policy was supplied.

    Returns:
        ``False`` only when the active request explicitly disables subagents,
        otherwise ``default``.
    """

    if context is not None:
        explicit = context.get("subagents_enabled")
        if isinstance(explicit, bool):
            return explicit

    active_context = get_current_execution_context()
    if active_context is not None and isinstance(
        active_context.subagents_enabled,
        bool,
    ):
        return active_context.subagents_enabled
    return default


def disabled_subagent_result(tool_name: str) -> dict[str, str]:
    """Build the canonical fail-closed result for a disabled subagent tool."""

    return {
        "error": "subagents_disabled",
        "tool": tool_name,
        "message": "Subagent tools are disabled for this request",
    }


__all__ = [
    "SUBAGENT_TOOL_NAMES",
    "disabled_subagent_result",
    "subagents_enabled",
]
