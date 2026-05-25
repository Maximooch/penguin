"""Prompt and output-style settings helpers for :mod:`penguin.core`."""

from __future__ import annotations

from typing import Any, Callable

__all__ = [
    "get_output_style",
    "get_prompt_mode",
    "set_output_style",
    "set_prompt_mode",
]

PromptBuilder = Callable[[str], str]
OutputFormatter = Callable[[str], None]


def set_prompt_mode(
    owner: Any,
    mode: str,
    *,
    get_system_prompt: PromptBuilder,
    logger: Any,
) -> str:
    """Set the prompt-builder mode on a core-like owner."""
    try:
        mode_normalized = str(mode).strip().lower()
        prompt = get_system_prompt(mode_normalized)
        owner.system_prompt = prompt
        try:
            if hasattr(owner.conversation_manager, "set_system_prompt"):
                owner.conversation_manager.set_system_prompt(prompt)
        except Exception:
            pass
        owner.prompt_mode = mode_normalized
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
            if hasattr(owner, "conversation_manager") and hasattr(
                owner.conversation_manager,
                "set_system_prompt",
            ):
                prompt = get_system_prompt(owner.prompt_mode)
                owner.system_prompt = prompt
                owner.conversation_manager.set_system_prompt(prompt)
            else:
                owner.system_prompt = get_system_prompt(owner.prompt_mode)
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
