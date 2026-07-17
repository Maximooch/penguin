"""Public compatibility surface for Penguin's canonical system prompt."""

from __future__ import annotations

from typing import Any

from penguin.prompt.builder import (
    CORE_ENGINEERING_DISCIPLINE,
    CORE_IDENTITY,
    OPERATING_CONTRACT,
    PENGUIN_SOUL,
    RUNTIME_CONTRACT,
    VOICE_AND_COUNSEL,
    PromptBuilder,
    build_system_prompt,
    get_builder,
    list_output_styles,
)
from penguin.prompt.profiles import (
    get_mode_description,
    get_work_mode_description,
    list_available_modes,
    list_available_work_modes,
    list_quality_overlays,
    normalize_prompt_mode,
    normalize_work_mode,
)
from penguin.prompt.soul import list_personality_profiles

__all__ = [
    "BASE_PROMPT",
    "CORE_ENGINEERING_DISCIPLINE",
    "OPERATING_CONTRACT",
    "PENGUIN_SOUL",
    "RUNTIME_CONTRACT",
    "SYSTEM_PROMPT",
    "SYSTEM_PROMPT_CORE",
    "VOICE_AND_COUNSEL",
    "PromptBuilder",
    "build_system_prompt",
    "get_builder",
    "get_mode_description",
    "get_system_prompt",
    "get_work_mode_description",
    "list_available_modes",
    "list_available_work_modes",
    "list_output_styles",
    "list_personality_profiles",
    "list_quality_overlays",
    "normalize_prompt_mode",
    "normalize_work_mode",
]


# Kept for integrations that imported the old name directly.
BASE_PROMPT = CORE_IDENTITY


def get_system_prompt(
    mode: str = "direct",
    *,
    work_mode: str | None = None,
    output_style: str | None = None,
    **kwargs: Any,
) -> str:
    """Render the current system prompt for one explicit task mode.

    Unsupported modes raise ``ValueError`` instead of silently receiving the
    default prompt while the runtime claims another mode is active.
    """

    return build_system_prompt(
        mode=mode,
        work_mode=work_mode,
        output_style=output_style,
        **kwargs,
    )


SYSTEM_PROMPT_CORE = get_system_prompt()
SYSTEM_PROMPT = SYSTEM_PROMPT_CORE
