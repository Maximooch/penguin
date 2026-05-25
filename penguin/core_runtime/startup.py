"""Startup helpers used by :mod:`penguin.core` construction."""

from __future__ import annotations

from typing import Any, Callable

RuntimeConfigFactory = Callable[[dict[str, Any]], Any]
ModelConfigFactory = Callable[..., Any]
ToolManagerFactory = Callable[..., Any]
SystemPromptBuilder = Callable[[str], str]
OutputFormatter = Callable[[str], Any]

__all__ = [
    "ModelConfigFactory",
    "OutputFormatter",
    "RuntimeConfigFactory",
    "SystemPromptBuilder",
    "ToolManagerFactory",
    "build_initial_model_config",
    "build_tool_manager",
    "initialize_prompt_and_output_state",
    "initialize_runtime_config",
]


def build_initial_model_config(
    config: Any,
    *,
    model: str | None,
    provider: str | None,
    default_model: str,
    default_provider: str,
    model_config_factory: ModelConfigFactory,
) -> Any:
    """Build the startup model config from live config plus explicit overrides."""

    source_model_config = getattr(config, "model_config", None)
    return model_config_factory(
        model=model or getattr(source_model_config, "model", default_model),
        provider=provider or getattr(source_model_config, "provider", default_provider),
        api_base=_initial_api_base(config, source_model_config),
        use_assistants_api=bool(
            getattr(source_model_config, "use_assistants_api", False)
        ),
        client_preference=getattr(
            source_model_config,
            "client_preference",
            "openrouter",
        ),
        streaming_enabled=bool(getattr(source_model_config, "streaming_enabled", True)),
        max_output_tokens=_initial_max_output_tokens(source_model_config),
        max_context_window_tokens=getattr(
            source_model_config,
            "max_context_window_tokens",
            None,
        ),
        service_tier=getattr(source_model_config, "service_tier", None),
    )


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


def build_tool_manager(
    config: Any,
    *,
    log_error: Callable[..., Any],
    fast_startup: bool,
    tool_manager_factory: ToolManagerFactory,
) -> Any:
    """Build ToolManager with a deterministic dict payload from live Config."""

    return tool_manager_factory(
        _safe_config_dict(config),
        log_error,
        fast_startup=fast_startup,
    )


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


def _safe_config_dict(config: Any) -> dict[str, Any]:
    try:
        return config.to_dict() if hasattr(config, "to_dict") else {}
    except Exception:
        return {}


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


def _initial_api_base(config: Any, source_model_config: Any) -> str | None:
    api_base = getattr(source_model_config, "api_base", None)
    if api_base:
        return api_base

    api_config = getattr(config, "api", None)
    return getattr(api_config, "base_url", None)


def _initial_max_output_tokens(source_model_config: Any) -> Any:
    try:
        raw_values = vars(source_model_config)
    except TypeError:
        raw_values = {}

    if isinstance(raw_values, dict):
        max_output_tokens = raw_values.get("max_output_tokens")
        if max_output_tokens is not None:
            return max_output_tokens
        if "max_tokens" in raw_values:
            return raw_values.get("max_tokens")

    max_output_tokens = getattr(source_model_config, "max_output_tokens", None)
    if max_output_tokens is not None:
        return max_output_tokens
    return None
