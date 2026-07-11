"""Public compatibility surface for Penguin's canonical system prompt."""

from __future__ import annotations

from typing import Any

from penguin.prompt.builder import (
    CORE_ENGINEERING_DISCIPLINE,
    CORE_IDENTITY,
    RUNTIME_CONTRACT,
    VOICE_AND_COUNSEL,
    PromptBuilder,
    build_system_prompt,
    get_builder,
)
from penguin.prompt.profiles import (
    get_mode_description,
    list_available_modes,
    normalize_prompt_mode,
)

__all__ = [
    "BASE_PROMPT",
    "CORE_ENGINEERING_DISCIPLINE",
    "RUNTIME_CONTRACT",
    "SYSTEM_PROMPT",
    "SYSTEM_PROMPT_CORE",
    "VOICE_AND_COUNSEL",
    "PromptBuilder",
    "build_system_prompt",
    "get_builder",
    "get_mode_description",
    "get_system_prompt",
    "list_available_modes",
    "normalize_prompt_mode",
]


# Kept for integrations that imported the old name directly.
BASE_PROMPT = CORE_IDENTITY


def get_system_prompt(
    mode: str = "direct",
    *,
    output_style: str | None = None,
    **kwargs: Any,
) -> str:
    """Render the current system prompt for one explicit task mode.

    Unsupported modes raise ``ValueError`` instead of silently receiving the
    default prompt while the runtime claims another mode is active.
    """

    return build_system_prompt(mode=mode, output_style=output_style, **kwargs)


SYSTEM_PROMPT_CORE = get_system_prompt()
SYSTEM_PROMPT = SYSTEM_PROMPT_CORE
