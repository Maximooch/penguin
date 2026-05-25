"""Model runtime resolution helpers for PenguinCore.

The functions in this module are intentionally free of ``PenguinCore`` state.
They accept the small pieces of configuration they need and return derived
runtime values for the caller to apply.
"""

from __future__ import annotations

import copy
import logging
from typing import Any, Awaitable, Callable, Mapping

from penguin.llm.model_config import (
    ModelConfig,
    fetch_model_specs,
    normalize_openai_service_tier,
    safe_context_window,
)

logger = logging.getLogger(__name__)

FetchModelSpecs = Callable[[str], Awaitable[dict[str, Any]]]
ResolveModelProvider = Callable[[str], tuple[str | None, str]]
ApiClientFactory = Callable[..., Any]
RefreshActiveClient = Callable[[], None]
LLMClientFactory = Callable[[ModelConfig, Any], Any]
LLMClientConfigFactory = Callable[..., Any]
LinkConfigFactory = Callable[..., Any]
LiteLLMLoader = Callable[[str], Any]


def _coerce_optional_int(value: Any) -> int | None:
    """Return a positive int or ``None`` for unset/invalid values."""

    try:
        parsed = int(value)
    except Exception:
        return None
    return parsed if parsed > 0 else None


def _model_configs_dict(model_configs: Any) -> dict[str, dict[str, Any]]:
    """Return only dict-valued model config entries."""

    if not isinstance(model_configs, Mapping):
        return {}
    result: dict[str, dict[str, Any]] = {}
    for key, value in model_configs.items():
        if isinstance(key, str) and isinstance(value, dict):
            result[key] = dict(value)
    return result


def refresh_api_client(
    owner: Any,
    *,
    api_client_factory: ApiClientFactory,
    log: logging.Logger | None = None,
) -> None:
    """Recreate and propagate the active API client for a core-like owner."""

    active_logger = log or logger
    owner.api_client = api_client_factory(model_config=owner.model_config)
    owner.api_client.set_system_prompt(owner.system_prompt)

    conversation_manager = getattr(owner, "conversation_manager", None)
    if conversation_manager:
        conversation_manager.api_client = owner.api_client
        try:
            if hasattr(conversation_manager, "context_window"):
                context_window = conversation_manager.context_window
                context_window.api_client = owner.api_client
        except Exception as exc:
            active_logger.warning(
                "Failed to propagate refreshed API client to ContextWindowManager: %s",
                exc,
            )

    engine = getattr(owner, "engine", None)
    if engine is not None:
        try:
            engine.api_client = owner.api_client
        except Exception as exc:
            active_logger.warning(
                "Failed to propagate refreshed API client to Engine: %s",
                exc,
            )


def ensure_litellm_configured(
    owner: Any,
    *,
    litellm_loader: LiteLLMLoader | None = None,
    log: logging.Logger | None = None,
) -> None:
    """Configure LiteLLM once when the optional runtime is installed."""

    if getattr(owner, "_litellm_configured", False):
        return

    active_logger = log or logger
    try:
        if litellm_loader is None:
            from penguin.llm.litellm_support import load_litellm_module

            litellm_loader = load_litellm_module

        litellm = litellm_loader("LiteLLM optional runtime")
        litellm._logging._disable_debugging()
        litellm.set_verbose = False
        litellm.drop_params = False
        owner._litellm_configured = True
    except Exception as exc:
        active_logger.debug(
            "LiteLLM optional runtime unavailable or not configured: %s",
            exc,
        )
        owner._litellm_configured = True


def configure_llm_client(
    owner: Any,
    *,
    base_url: str | None = None,
    link_user_id: str | None = None,
    link_session_id: str | None = None,
    link_agent_id: str | None = None,
    link_workspace_id: str | None = None,
    link_api_key: str | None = None,
    llm_client_factory: LLMClientFactory | None = None,
    llm_client_config_factory: LLMClientConfigFactory | None = None,
    link_config_factory: LinkConfigFactory | None = None,
) -> dict[str, Any]:
    """Create or update the runtime LLM client for Link-routed inference."""

    if not hasattr(owner, "_llm_client") or owner._llm_client is None:
        if (
            llm_client_factory is None
            or llm_client_config_factory is None
            or link_config_factory is None
        ):
            from penguin.llm.client import (
                LinkConfig,
                LLMClient,
                LLMClientConfig,
            )

            llm_client_factory = llm_client_factory or LLMClient
            llm_client_config_factory = llm_client_config_factory or LLMClientConfig
            link_config_factory = link_config_factory or LinkConfig

        config = llm_client_config_factory(
            base_url=base_url,
            link=link_config_factory(
                user_id=link_user_id,
                session_id=link_session_id,
                agent_id=link_agent_id,
                workspace_id=link_workspace_id,
                api_key=link_api_key,
            ),
        )
        owner._llm_client = llm_client_factory(owner.model_config, config)
    else:
        owner._llm_client.update_config(
            base_url=base_url,
            link_user_id=link_user_id,
            link_session_id=link_session_id,
            link_agent_id=link_agent_id,
            link_workspace_id=link_workspace_id,
            link_api_key=link_api_key,
        )

    status = owner._llm_client.get_status()
    return status if isinstance(status, dict) else {}


def apply_new_model_config(
    owner: Any,
    new_model_config: ModelConfig,
    *,
    context_window_tokens: int | None = None,
    refresh_active_client: RefreshActiveClient | None = None,
    log: logging.Logger | None = None,
) -> None:
    """Apply a new model config and propagate dependent runtime state."""

    active_logger = log or logger
    owner.model_config = new_model_config

    if refresh_active_client is not None:
        refresh_active_client()

    conversation_manager = getattr(owner, "conversation_manager", None)
    if conversation_manager:
        conversation_manager.model_config = new_model_config
        try:
            if hasattr(conversation_manager, "context_window"):
                context_window = conversation_manager.context_window
                context_window.model_config = new_model_config
                if context_window_tokens:
                    old_budget = context_window.max_context_window_tokens
                    context_window.max_context_window_tokens = context_window_tokens
                    context_window._initialize_token_budgets()
                    active_logger.info(
                        "Updated context window: %s -> %s tokens",
                        old_budget,
                        context_window_tokens,
                    )
        except Exception as exc:
            active_logger.warning(
                "Failed to propagate new model config to ContextWindowManager: %s",
                exc,
            )

    engine = getattr(owner, "engine", None)
    if engine is not None:
        try:
            engine.model_config = new_model_config
        except Exception as exc:
            active_logger.warning(
                "Failed to propagate new model config to Engine: %s",
                exc,
            )


async def resolve_request_runtime(
    owner: Any,
    model_id: str | None = None,
    *,
    api_client_factory: ApiClientFactory,
) -> tuple[ModelConfig, Any]:
    """Build a request-scoped model config and API client for a core-like owner."""

    current_model = (
        owner.get_current_model() if hasattr(owner, "get_current_model") else {}
    )
    current_raw = (
        str(current_model.get("model") or "").strip()
        if isinstance(current_model, dict)
        else ""
    )
    current_provider = (
        str(current_model.get("provider") or "").strip()
        if isinstance(current_model, dict)
        else ""
    )
    current_qualified = (
        f"{current_provider}/{current_raw}" if current_provider and current_raw else ""
    )

    requested_model = model_id.strip() if isinstance(model_id, str) else ""
    if requested_model and requested_model not in {current_raw, current_qualified}:
        new_model_config, _ = await owner._build_model_config_for_model(requested_model)
    else:
        new_model_config = copy.deepcopy(owner.model_config)

    api_client = api_client_factory(model_config=new_model_config)
    api_client.set_system_prompt(owner.system_prompt)
    return new_model_config, api_client


async def load_model_for_core(
    owner: Any,
    model_id: str,
    *,
    log: logging.Logger | None = None,
) -> bool:
    """Load and apply a runtime model for a core-like owner."""

    active_logger = log or logger
    owner._last_model_load_error = None

    try:
        new_model_config, safe_window = await owner._build_model_config_for_model(
            model_id
        )
        owner._apply_new_model_config(
            new_model_config,
            context_window_tokens=safe_window,
        )

        active_logger.info(
            "Switched to model '%s' (context: %s tokens, vision: %s)",
            new_model_config.model,
            safe_window,
            new_model_config.vision_enabled,
        )
        return True

    except Exception as exc:
        owner._last_model_load_error = str(exc)
        active_logger.error("Failed to switch to model '%s': %s", model_id, exc)
        return False


def canonicalize_runtime_model_id(
    model_id: str,
    provider: str,
    client_preference: str,
) -> str:
    """Canonicalize model IDs into provider-local form for runtime adapters."""

    value = str(model_id or "").strip()
    if not value:
        return value

    provider_value = str(provider or "").strip().lower()
    client_value = str(client_preference or "").strip().lower()

    # Native SDK adapters expect provider-local IDs.
    if client_value == "native" and provider_value in {"openai", "anthropic"}:
        if "/" in value:
            prefix, remainder = value.split("/", 1)
            if prefix.strip().lower() == provider_value and remainder.strip():
                return remainder.strip()
        return value

    # OpenRouter runtime model IDs should not include an extra openrouter/ prefix.
    if provider_value == "openrouter" and "/" in value:
        prefix, remainder = value.split("/", 1)
        if prefix.strip().lower() == "openrouter" and remainder.strip():
            return remainder.strip()

    return value


def resolve_model_provider(
    model_id: str,
    model_configs: Any,
    *,
    current_client_preference: str | None = None,
) -> tuple[str | None, str]:
    """Resolve provider and client preference for a model ID."""

    configs = _model_configs_dict(model_configs)
    model_conf = configs.get(model_id)
    if model_conf:
        provider = model_conf.get("provider")
        client_pref = str(model_conf.get("client_preference", "openrouter"))
        return str(provider) if provider else None, client_pref

    if "/" not in model_id:
        logger.error(
            "Model '%s' not in model_configs and not fully-qualified", model_id
        )
        return None, ""

    provider_part = model_id.split("/", 1)[0].strip().lower()

    if provider_part == "openrouter":
        return "openrouter", "openrouter"

    native_providers = {"openai", "anthropic", "google", "ollama"}
    if provider_part in native_providers:
        return provider_part, "native"

    client_pref = str(current_client_preference or "openrouter").strip().lower()
    provider = "openrouter" if client_pref == "openrouter" else provider_part
    return provider, client_pref


async def build_model_config_for_model(
    model_id: str,
    *,
    model_configs: Any,
    current_model_config: ModelConfig | None = None,
    fetch_specs: FetchModelSpecs | None = None,
    resolve_provider: ResolveModelProvider | None = None,
) -> tuple[ModelConfig, int | None]:
    """Resolve a runtime model id into a concrete ``ModelConfig``.

    Returns:
        A tuple of ``(model_config, safe_context_window_tokens)``. The caller is
        responsible for applying the config to runtime state.
    """

    configs = _model_configs_dict(model_configs)
    fetch_specs = fetch_specs or fetch_model_specs
    current_client_preference = (
        getattr(current_model_config, "client_preference", None)
        if current_model_config is not None
        else None
    )
    if resolve_provider is None:
        provider, client_pref = resolve_model_provider(
            model_id,
            configs,
            current_client_preference=current_client_preference,
        )
    else:
        provider, client_pref = resolve_provider(model_id)
    if not provider:
        raise ValueError(f"Could not resolve provider for model '{model_id}'")

    provider_value = provider.strip().lower()
    client_value = client_pref.strip().lower()
    runtime_model_id = canonicalize_runtime_model_id(
        model_id,
        provider_value,
        client_value,
    )

    model_lookup_id = (
        runtime_model_id
        if runtime_model_id in configs and model_id not in configs
        else model_id
    )

    requires_openrouter_specs = bool(
        provider_value == "openrouter" or client_value == "openrouter"
    )
    model_specs: dict[str, Any] = {}
    spec_model_id = runtime_model_id if provider_value == "openrouter" else model_id

    if requires_openrouter_specs:
        model_specs = await fetch_specs(spec_model_id)
        if not model_specs:
            raise ValueError(
                f"Could not fetch specifications for model '{spec_model_id}'"
            )
        logger.info("Fetched specs for %s: %s", spec_model_id, model_specs)

    model_specific = configs.get(model_lookup_id, {})

    context_length = _coerce_optional_int(model_specs.get("context_length"))
    if context_length is None:
        context_length = _coerce_optional_int(
            model_specific.get("context_window")
            or model_specific.get("max_context_window_tokens")
        )

    safe_window = safe_context_window(context_length)
    max_output = _coerce_optional_int(model_specs.get("max_output_tokens"))
    if max_output is None:
        max_output = _coerce_optional_int(
            model_specific.get("max_output_tokens") or model_specific.get("max_tokens")
        )
    if max_output is not None and safe_window is not None and max_output > safe_window:
        logger.warning(
            "Clamping model '%s' max_output_tokens from %s to safe window %s",
            runtime_model_id,
            max_output,
            safe_window,
        )
        max_output = safe_window

    new_model_config = ModelConfig.for_model(
        model_name=model_lookup_id,
        provider=provider,
        client_preference=client_pref,
        model_configs=configs,
    )

    new_model_config.model = runtime_model_id
    if "service_tier" not in model_specific:
        inherited_service_tier = (
            getattr(current_model_config, "service_tier", None)
            if current_model_config is not None
            else None
        )
        new_model_config.service_tier = normalize_openai_service_tier(
            inherited_service_tier
        )
    if context_length is not None:
        new_model_config.max_context_window_tokens = context_length
        new_model_config.max_history_tokens = safe_window
    if max_output is not None:
        new_model_config.max_output_tokens = max_output
    if (
        safe_window is not None
        and new_model_config.max_output_tokens is not None
        and new_model_config.max_output_tokens > safe_window
    ):
        logger.warning(
            "Clamping model '%s' max_output_tokens from %s to safe window %s",
            runtime_model_id,
            new_model_config.max_output_tokens,
            safe_window,
        )
        new_model_config.max_output_tokens = safe_window

    user_explicit_vision = model_specific.get("vision_enabled")
    if user_explicit_vision is not None:
        new_model_config.vision_enabled = bool(user_explicit_vision)
        logger.info(
            "Model '%s' vision set to %s (user config)",
            runtime_model_id,
            new_model_config.vision_enabled,
        )
    elif model_specs.get("supports_vision"):
        new_model_config.vision_enabled = True
        logger.info("Model '%s' supports vision (auto-detected)", runtime_model_id)

    return new_model_config, safe_window


def list_available_models(
    model_configs: Any,
    *,
    current_model_name: str | None = None,
) -> list[dict[str, Any]]:
    """Return model metadata derived from configured model entries."""

    models: list[dict[str, Any]] = []
    for model_id, conf in _model_configs_dict(model_configs).items():
        entry = {
            "id": model_id,
            "name": conf.get("model", model_id),
            "provider": conf.get("provider", "unknown"),
            "client_preference": conf.get("client_preference", "openrouter"),
            "vision_enabled": conf.get("vision_enabled", False),
            "max_output_tokens": conf.get("max_output_tokens", conf.get("max_tokens")),
            "temperature": conf.get("temperature"),
            "current": model_id == current_model_name
            or conf.get("model") == current_model_name,
        }
        models.append(entry)

    models.sort(key=lambda item: (not item["current"], item["id"]))
    return models


def current_model_payload(
    model_config: ModelConfig | None,
) -> dict[str, Any] | None:
    """Return the public current-model payload for a loaded config."""

    if model_config is None:
        return None

    return {
        "model": model_config.model,
        "provider": model_config.provider,
        "client_preference": model_config.client_preference,
        "max_output_tokens": getattr(model_config, "max_output_tokens", None),
        "temperature": getattr(model_config, "temperature", None),
        "streaming_enabled": model_config.streaming_enabled,
        "vision_enabled": bool(getattr(model_config, "vision_enabled", False)),
        "api_base": getattr(model_config, "api_base", None),
    }


__all__ = [
    "apply_new_model_config",
    "build_model_config_for_model",
    "canonicalize_runtime_model_id",
    "current_model_payload",
    "ensure_litellm_configured",
    "list_available_models",
    "load_model_for_core",
    "refresh_api_client",
    "resolve_model_provider",
    "resolve_request_runtime",
]
