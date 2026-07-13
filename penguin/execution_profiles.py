"""Per-turn execution profiles for lean chat and constrained research runs.

The profile is intentionally resolved at the request boundary rather than
stored on an agent. A user can move from an ordinary agent turn to a small,
no-tool chat turn without changing the session's long-lived capabilities.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Optional

__all__ = [
    "CHAT_SYSTEM_CONTEXT",
    "RESEARCH_SYSTEM_CONTEXT",
    "RESEARCH_TOOL_NAMES",
    "ExecutionProfile",
    "ExecutionProfileName",
    "resolve_execution_profile",
    "resolve_profile_system_context",
    "resolve_profile_tools_enabled",
]

ExecutionProfileName = Literal["agent", "chat", "research"]

# Research turns can inspect the project and gather information, but cannot
# mutate files, execute commands, control a browser, or spawn agents.
RESEARCH_TOOL_NAMES = (
    "read_file",
    "read_image",
    "list_files",
    "find_file",
    "grep_search",
    "analyze_project",
    "perplexity_search",
)

# These prompts deliberately describe only the contract for the current turn.
# The full agent prompt contains instructions and tool guidance that are useful
# for autonomous work, but it needlessly dominates a casual answer or a
# constrained research pass. They are applied to a request payload only; the
# persisted conversation and the shared API client's default prompt remain
# unchanged for future agent turns.
CHAT_SYSTEM_CONTEXT = (
    "You are Penguin in Chat mode. Answer directly and helpfully using the "
    "conversation for context. Do not call tools, emit action markup, or claim "
    "to have performed actions. Ask a concise clarifying question when needed."
)

RESEARCH_SYSTEM_CONTEXT = (
    "You are Penguin in Research mode. Investigate and synthesize accurately. "
    "Use only the read-only tools supplied when they materially help. Do not "
    "modify files, execute commands, control browsers, or claim work beyond "
    "the available evidence. Cite relevant sources or files and state uncertainty."
)


@dataclass(frozen=True)
class ExecutionProfile:
    """Resolved runtime policy for one model turn."""

    name: ExecutionProfileName
    tools_enabled: bool
    allowed_tool_names: Optional[tuple[str, ...]]
    include_web_search: bool
    system_context: Optional[str]


_PROFILES: dict[str, ExecutionProfile] = {
    "agent": ExecutionProfile(
        name="agent",
        tools_enabled=True,
        allowed_tool_names=None,
        include_web_search=True,
        system_context=None,
    ),
    "chat": ExecutionProfile(
        name="chat",
        tools_enabled=False,
        allowed_tool_names=(),
        include_web_search=False,
        system_context=CHAT_SYSTEM_CONTEXT,
    ),
    "research": ExecutionProfile(
        name="research",
        tools_enabled=True,
        allowed_tool_names=RESEARCH_TOOL_NAMES,
        include_web_search=True,
        system_context=RESEARCH_SYSTEM_CONTEXT,
    ),
}


def resolve_execution_profile(value: Optional[str]) -> ExecutionProfile:
    """Return a known profile, defaulting omitted values to full agent mode."""

    normalized = (value or "agent").strip().lower()
    profile = _PROFILES.get(normalized)
    if profile is None:
        supported = ", ".join(_PROFILES)
        raise ValueError(f"execution_profile must be one of: {supported}")
    return profile


def resolve_profile_tools_enabled(
    profile: ExecutionProfile,
    requested_tools_enabled: Optional[bool],
) -> bool:
    """Apply an optional restrictive override without weakening chat safety."""

    if profile.name == "chat":
        return False
    if requested_tools_enabled is None:
        return profile.tools_enabled
    return bool(requested_tools_enabled)


def resolve_profile_system_context(value: Optional[str]) -> Optional[str]:
    """Return the compact request-only system context for an execution profile.

    ``None`` means preserve the API client's full configured system prompt.
    The returned value is intentionally a plain immutable string so callers can
    substitute it into one request without changing shared conversation state.
    """

    return resolve_execution_profile(value).system_context
