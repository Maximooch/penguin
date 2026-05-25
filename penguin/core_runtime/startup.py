"""Startup helpers used by :mod:`penguin.core` construction."""

from __future__ import annotations

from typing import Any, Callable

RuntimeConfigFactory = Callable[[dict[str, Any]], Any]
SystemPromptBuilder = Callable[[str], str]
OutputFormatter = Callable[[str], Any]

__all__ = [
    "OutputFormatter",
    "RuntimeConfigFactory",
    "SystemPromptBuilder",
    "initialize_prompt_and_output_state",
    "initialize_runtime_config",
]


def initialize_runtime_config(
    owner: Any,
    *,
    config: Any,
    runtime_config: Any | None,
    tool_manager: Any | None,
    runtime_config_factory: RuntimeConfigFactory,
) -> None:
    """Attach runtime config and register the tool manager as an observer."""

    if runtime_config is None:
        config_dict = config.to_dict() if hasattr(config, "to_dict") else {}
        owner.runtime_config = runtime_config_factory(config_dict)
    else:
        owner.runtime_config = runtime_config

    observer = getattr(tool_manager, "on_runtime_config_change", None)
    if tool_manager is not None and callable(observer):
        owner.runtime_config.register_observer(observer)


def initialize_prompt_and_output_state(
    owner: Any,
    raw_config: Any,
    *,
    get_system_prompt: SystemPromptBuilder,
    fallback_system_prompt: str,
    set_output_formatting: OutputFormatter | None = None,
) -> None:
    """Initialize output display flags, prompt mode, style, and prompt text."""

    output_config = getattr(owner.config, "output", None)
    owner.show_tool_results = _resolve_show_tool_results(output_config, raw_config)
    owner.prompt_mode = _resolve_prompt_mode(raw_config)
    owner.output_style = _apply_output_style(
        output_config,
        raw_config,
        set_output_formatting=set_output_formatting,
    )
    try:
        owner.system_prompt = get_system_prompt(owner.prompt_mode)
    except Exception:
        owner.system_prompt = fallback_system_prompt


def _resolve_show_tool_results(output_config: Any, raw_config: Any) -> bool:
    if output_config and hasattr(output_config, "show_tool_results"):
        return bool(output_config.show_tool_results)

    try:
        raw_output_config = (
            raw_config.get("output", {}) if isinstance(raw_config, dict) else {}
        )
        show_tool_value = raw_output_config.get("show_tool_results", True)
        if isinstance(show_tool_value, str):
            return show_tool_value.strip().lower() in {"1", "true", "yes", "on"}
        return bool(show_tool_value)
    except Exception:
        return True


def _resolve_prompt_mode(raw_config: Any) -> str:
    try:
        mode = str(raw_config.get("prompt", {}).get("mode", "direct")).strip().lower()
    except Exception:
        mode = "direct"
    return mode or "direct"


def _apply_output_style(
    output_config: Any,
    raw_config: Any,
    *,
    set_output_formatting: OutputFormatter | None,
) -> str:
    try:
        formatter = set_output_formatting or _load_output_formatter()
        if output_config and getattr(output_config, "prompt_style", None):
            prompt_style = str(output_config.prompt_style).strip().lower()
        else:
            prompt_style = (
                str(raw_config.get("output", {}).get("prompt_style", "steps_final"))
                .strip()
                .lower()
            )
        output_style = prompt_style or "steps_final"
        formatter(output_style)
        return output_style
    except Exception:
        return "steps_final"


def _load_output_formatter() -> OutputFormatter:
    from penguin.prompt.builder import set_output_formatting

    return set_output_formatting
