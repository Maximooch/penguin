"""Prompt and output-style settings helpers for :mod:`penguin.core`."""

from __future__ import annotations

from typing import Any, Callable

__all__ = [
    "get_git_attribution_prompt",
    "get_output_style",
    "get_prompt_mode",
    "get_work_mode",
    "set_core_system_prompt",
    "set_output_style",
    "set_prompt_mode",
    "set_work_mode",
]

PromptBuilder = Callable[..., str]
OutputFormatter = Callable[[str], None]
PromptModeNormalizer = Callable[[str], str]


def set_prompt_mode(
    owner: Any,
    mode: str,
    *,
    get_system_prompt: PromptBuilder,
    normalize_prompt_mode: PromptModeNormalizer | None = None,
    logger: Any,
) -> str:
    """Set the prompt-builder mode on a core-like owner."""
    try:
        mode_normalized = str(mode).strip().lower()
        if normalize_prompt_mode is not None:
            mode_normalized = normalize_prompt_mode(mode_normalized)
        prompt = get_system_prompt(
            mode_normalized,
            output_style=get_output_style(owner),
            git_attribution_prompt=get_git_attribution_prompt(owner),
            **_configured_prompt_overlays(owner),
        )
        set_core_system_prompt(owner, prompt)
        owner.prompt_mode = mode_normalized
        try:
            from penguin.prompt.profiles import resolve_prompt_preset

            owner.work_mode = resolve_prompt_preset(mode_normalized).work_mode
        except (ImportError, ValueError):
            pass
        return f"Prompt mode set to '{mode_normalized}'."
    except Exception as exc:
        message = f"Failed to set prompt mode '{mode}': {exc}"
        logger.warning(message)
        return message


def get_prompt_mode(owner: Any) -> str:
    """Return the current prompt-builder mode from a core-like owner."""
    try:
        return getattr(owner, "prompt_mode", "direct")
    except Exception:
        return "direct"


def set_work_mode(
    owner: Any,
    mode: str,
    *,
    get_system_prompt: PromptBuilder,
    normalize_work_mode: PromptModeNormalizer,
    logger: Any,
) -> str:
    """Set task intent independently from personality and response style."""

    try:
        work_mode = normalize_work_mode(str(mode).strip().lower())
        prompt = get_system_prompt(
            work_mode=work_mode,
            output_style=get_output_style(owner),
            git_attribution_prompt=get_git_attribution_prompt(owner),
            **_configured_prompt_overlays(owner),
        )
        set_core_system_prompt(owner, prompt)
        owner.work_mode = work_mode
        owner.prompt_mode = work_mode
        return f"Work mode set to '{work_mode}'."
    except Exception as exc:
        message = f"Failed to set work mode '{mode}': {exc}"
        logger.warning(message)
        return message


def get_work_mode(owner: Any) -> str:
    """Return the current task-intent mode from a core-like owner."""

    try:
        return getattr(owner, "work_mode", "build")
    except Exception:
        return "build"


def get_git_attribution_prompt(owner: Any) -> bool:
    """Return whether active prompt rendering includes Git attribution guidance."""

    try:
        return bool(getattr(owner, "git_attribution_prompt", True))
    except Exception:
        return True


def set_core_system_prompt(owner: Any, prompt: str) -> None:
    """Set the active system prompt across core, API client, and conversation."""

    owner.system_prompt = prompt
    api_client = getattr(owner, "api_client", None)
    if api_client and hasattr(api_client, "set_system_prompt"):
        api_client.set_system_prompt(prompt)
    conversation_manager = getattr(owner, "conversation_manager", None)
    if conversation_manager and hasattr(conversation_manager, "set_system_prompt"):
        conversation_manager.set_system_prompt(prompt)


def set_output_style(
    owner: Any,
    style: str,
    *,
    get_system_prompt: PromptBuilder,
    set_output_formatting: OutputFormatter,
    logger: Any,
) -> str:
    """Set output formatting style and rebuild the active system prompt."""
    try:
        style_normalized = str(style).strip().lower()
        set_output_formatting(style_normalized)
        owner.output_style = style_normalized
        try:
            prompt = get_system_prompt(
                owner.prompt_mode,
                output_style=style_normalized,
                git_attribution_prompt=get_git_attribution_prompt(owner),
                **_configured_prompt_overlays(owner),
            )
            set_core_system_prompt(owner, prompt)
        except Exception:
            pass
        return f"Output style set to '{style_normalized}'."
    except Exception as exc:
        message = f"Failed to set output style '{style}': {exc}"
        logger.warning(message)
        return message


def get_output_style(owner: Any) -> str:
    """Return the current output style from a core-like owner."""
    try:
        return getattr(owner, "output_style", "steps_final")
    except Exception:
        return "steps_final"


def _configured_prompt_overlays(owner: Any) -> dict[str, Any]:
    """Return only explicitly initialized composition settings."""

    values: dict[str, Any] = {}
    for name in ("personality_profile", "personality_overlay", "quality_overlays"):
        if hasattr(owner, name):
            values[name] = getattr(owner, name)
    return values
