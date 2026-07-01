"""OpenCode bridge helpers used by :mod:`penguin.core`.

This module owns deterministic payload shaping around model metadata, session
fallback, usage metadata, and small adapter update contracts so those behaviors
can be tested without a core instance.
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass
from math import isfinite
from typing import Any, Callable

SESSION_MODEL_ID_KEY = "_opencode_model_id_v1"
SESSION_PROVIDER_ID_KEY = "_opencode_provider_id_v1"
SESSION_VARIANT_KEY = "_opencode_variant_v1"

__all__ = [
    "SESSION_MODEL_ID_KEY",
    "SESSION_PROVIDER_ID_KEY",
    "SESSION_VARIANT_KEY",
    "UsageUpdateTarget",
    "apply_usage_to_core_latest_message",
    "apply_usage_to_latest_message",
    "build_assistant_message_info",
    "latest_model_usage",
    "normalize_optional_string",
    "prepare_scoped_event_properties",
    "resolve_adapter_directory",
    "resolve_latest_usage_message_id",
    "resolve_model_state",
    "resolve_session_id",
    "resolve_usage_loggers",
    "resolve_usage_update_target",
    "usage_tokens_and_cost",
]


@dataclass(frozen=True)
class UsageUpdateTarget:
    """Resolved target for applying provider usage to an OpenCode message."""

    adapter: Any
    message_id: str
    tokens: dict[str, Any]
    cost: float
    total_tokens: int


def normalize_optional_string(value: Any) -> str | None:
    """Return a stripped string or ``None`` for missing/blank values."""

    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def resolve_model_state(
    *,
    session_metadata: Any = None,
    model_config: Any = None,
    model_id: Any = None,
    provider_id: Any = None,
    variant: Any = None,
) -> dict[str, str | None]:
    """Resolve OpenCode model/provider/variant metadata by precedence."""

    metadata = session_metadata if isinstance(session_metadata, dict) else {}
    resolved_provider = (
        normalize_optional_string(provider_id)
        or normalize_optional_string(metadata.get(SESSION_PROVIDER_ID_KEY))
        or normalize_optional_string(metadata.get("providerID"))
        or normalize_optional_string(metadata.get("provider_id"))
        or normalize_optional_string(getattr(model_config, "provider", None))
    )
    resolved_model = (
        normalize_optional_string(model_id)
        or normalize_optional_string(metadata.get(SESSION_MODEL_ID_KEY))
        or normalize_optional_string(metadata.get("modelID"))
        or normalize_optional_string(metadata.get("model_id"))
        or normalize_optional_string(getattr(model_config, "model", None))
    )
    resolved_variant = (
        normalize_optional_string(variant)
        or normalize_optional_string(metadata.get(SESSION_VARIANT_KEY))
        or normalize_optional_string(metadata.get("variant"))
    )
    return {
        "providerID": resolved_provider,
        "modelID": resolved_model,
        "variant": resolved_variant,
    }


def resolve_session_id(
    *,
    execution_context: Any = None,
    conversation_manager: Any = None,
    default: str = "unknown",
) -> str:
    """Resolve the OpenCode session id for event emission."""

    if execution_context is not None:
        session_id = normalize_optional_string(
            getattr(execution_context, "session_id", None)
        ) or normalize_optional_string(
            getattr(execution_context, "conversation_id", None)
        )
        if session_id:
            return session_id

    get_current_session = getattr(conversation_manager, "get_current_session", None)
    current_session = get_current_session() if callable(get_current_session) else None
    current_session_id = normalize_optional_string(getattr(current_session, "id", None))
    return current_session_id or default


def resolve_adapter_directory(
    session_id: str,
    *,
    session_directories: Any = None,
    execution_context: Any = None,
    runtime_config: Any = None,
    env_getter: Any = os.getenv,
    cwd_getter: Any = os.getcwd,
) -> str:
    """Resolve the working directory attached to a TUI adapter."""

    if isinstance(session_directories, dict):
        mapped = normalize_optional_string(session_directories.get(session_id))
        if mapped:
            return mapped

    context_directory = normalize_optional_string(
        getattr(execution_context, "directory", None)
    )
    if context_directory:
        return context_directory

    runtime_directory = normalize_optional_string(
        getattr(runtime_config, "active_root", None)
    ) or normalize_optional_string(getattr(runtime_config, "project_root", None))
    if runtime_directory:
        return runtime_directory

    env_directory = normalize_optional_string(env_getter("PENGUIN_CWD"))
    if env_directory:
        return env_directory

    return str(cwd_getter())


def prepare_scoped_event_properties(
    data: Any,
    *,
    execution_context: Any = None,
    session_directories: Any = None,
    require_session: bool = False,
) -> tuple[dict[str, Any] | None, str | None]:
    """Return OpenCode event properties decorated with session and directory."""

    properties = dict(data or {})
    session_id = (
        normalize_optional_string(properties.get("sessionID"))
        or normalize_optional_string(properties.get("session_id"))
        or normalize_optional_string(properties.get("conversation_id"))
    )

    if not session_id and execution_context is not None:
        session_id = normalize_optional_string(
            getattr(execution_context, "session_id", None)
        ) or normalize_optional_string(
            getattr(execution_context, "conversation_id", None)
        )

    if not session_id and require_session:
        return None, None

    if session_id:
        properties.setdefault("sessionID", session_id)
        properties.setdefault("conversation_id", session_id)

    if "directory" not in properties:
        directory = normalize_optional_string(
            getattr(execution_context, "directory", None)
        )
        if not directory and session_id and isinstance(session_directories, dict):
            directory = normalize_optional_string(session_directories.get(session_id))
        if directory:
            properties["directory"] = directory

    return properties, session_id


def build_assistant_message_info(
    *,
    message_id: str,
    session_id: str,
    directory: str | None,
    model_state: dict[str, Any],
    created_ms: int | None = None,
    agent: str = "default",
) -> dict[str, Any]:
    """Build fallback OpenCode assistant message metadata for part-first events."""

    fallback_directory = directory or os.getcwd()
    info: dict[str, Any] = {
        "id": message_id,
        "sessionID": session_id,
        "role": "assistant",
        "time": {
            "created": created_ms if created_ms is not None else int(time.time() * 1000)
        },
        "parentID": "root",
        "modelID": model_state.get("modelID") or "penguin-default",
        "providerID": model_state.get("providerID") or "penguin",
        "mode": "chat",
        "agent": agent,
        "path": {"cwd": fallback_directory, "root": fallback_directory},
        "cost": 0,
        "tokens": {
            "input": 0,
            "output": 0,
            "reasoning": 0,
            "cache": {"read": 0, "write": 0},
        },
    }
    variant = model_state.get("variant")
    if variant:
        info["variant"] = variant
    return info


def latest_model_usage(api_client: Any) -> dict[str, Any]:
    """Return normalized usage metadata from an active model handler."""

    handler = getattr(api_client, "client_handler", None)
    getter = getattr(handler, "get_last_usage", None)
    if not callable(getter):
        return {}
    try:
        data = getter()
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def resolve_latest_usage_message_id(
    session_id: str,
    *,
    stream_states: Any = None,
    adapter: Any = None,
) -> str | None:
    """Resolve the latest assistant message id for a session usage update."""

    message_id: str | None = None
    if isinstance(stream_states, dict):
        state = stream_states.get(session_id)
        if isinstance(state, dict):
            state_message_id = state.get("message_id")
            if isinstance(state_message_id, str) and state_message_id:
                message_id = state_message_id

        if not message_id:
            scoped_prefix = f"{session_id}:"
            for key, state_value in stream_states.items():
                if not isinstance(key, str) or not key.startswith(scoped_prefix):
                    continue
                if not isinstance(state_value, dict):
                    continue
                state_message_id = state_value.get("message_id")
                if isinstance(state_message_id, str) and state_message_id:
                    message_id = state_message_id
                    break

    if not message_id and adapter is not None:
        adapter_message_id = getattr(adapter, "_current_message_id", None)
        if isinstance(adapter_message_id, str) and adapter_message_id:
            message_id = adapter_message_id

    return message_id


def _usage_int(usage: dict[str, Any], key: str) -> int:
    try:
        return max(int(usage.get(key, 0) or 0), 0)
    except (TypeError, ValueError):
        return 0


def usage_tokens_and_cost(usage: dict[str, Any]) -> tuple[dict[str, Any], float]:
    """Return OpenCode token payload and non-negative cost from usage metadata."""

    tokens = {
        "input": _usage_int(usage, "input_tokens"),
        "output": _usage_int(usage, "output_tokens"),
        "reasoning": _usage_int(usage, "reasoning_tokens"),
        "cache": {
            "read": _usage_int(usage, "cache_read_tokens"),
            "write": _usage_int(usage, "cache_write_tokens"),
        },
    }
    cost = usage.get("cost")
    try:
        normalized_cost = float(cost) if cost is not None else 0.0
    except (TypeError, ValueError):
        normalized_cost = 0.0
    if not isfinite(normalized_cost):
        normalized_cost = 0.0
    return tokens, max(normalized_cost, 0.0)


def _usage_total_tokens(usage: dict[str, Any]) -> int:
    try:
        return max(int(usage.get("total_tokens", 0) or 0), 0)
    except (TypeError, ValueError):
        return 0


def resolve_usage_update_target(
    session_id: Any,
    usage: Any,
    *,
    stream_states: Any = None,
    message_adapters: Any = None,
    get_adapter: Callable[[str], Any],
) -> UsageUpdateTarget | None:
    """Resolve adapter/message/tokens for applying usage to an OpenCode message."""

    if not isinstance(session_id, str) or not session_id.strip():
        return None
    normalized_session_id = session_id.strip()
    if not isinstance(usage, dict) or not usage:
        return None

    message_id = resolve_latest_usage_message_id(
        normalized_session_id,
        stream_states=stream_states,
    )
    adapter = (
        message_adapters.get(message_id)
        if message_id and isinstance(message_adapters, dict)
        else None
    )
    if adapter is None:
        adapter = get_adapter(normalized_session_id)

    if not message_id:
        message_id = resolve_latest_usage_message_id(
            normalized_session_id,
            adapter=adapter,
        )

    if not isinstance(message_id, str) or not message_id:
        return None

    tokens, normalized_cost = usage_tokens_and_cost(usage)
    return UsageUpdateTarget(
        adapter=adapter,
        message_id=message_id,
        tokens=tokens,
        cost=normalized_cost,
        total_tokens=_usage_total_tokens(usage),
    )


async def apply_usage_to_latest_message(
    session_id: Any,
    usage: Any,
    *,
    stream_states: Any = None,
    message_adapters: Any = None,
    get_adapter: Callable[[str], Any],
    logger: Any = None,
    extra_loggers: tuple[Any, ...] = (),
) -> bool:
    """Apply provider usage metadata to the latest OpenCode assistant message."""

    target = resolve_usage_update_target(
        session_id,
        usage,
        stream_states=stream_states,
        message_adapters=message_adapters,
        get_adapter=get_adapter,
    )
    if target is None:
        return False

    updater = getattr(target.adapter, "update_assistant_usage", None)
    if not callable(updater):
        return False

    try:
        await updater(target.message_id, tokens=target.tokens, cost=target.cost)
    except Exception:
        debug = getattr(logger, "debug", None)
        if callable(debug):
            debug("Failed to apply OpenCode usage metadata", exc_info=True)
        return False

    usage_log = (
        "opencode.usage.applied session=%s message=%s input=%s output=%s "
        "reasoning=%s cache_read=%s cache_write=%s total=%s cost=%s"
    )
    usage_args = (
        session_id,
        target.message_id,
        target.tokens["input"],
        target.tokens["output"],
        target.tokens["reasoning"],
        target.tokens["cache"]["read"],
        target.tokens["cache"]["write"],
        target.total_tokens,
        target.cost,
    )
    seen_loggers: set[int] = set()
    for candidate in (logger, *extra_loggers):
        if candidate is None:
            continue
        logger_id = id(candidate)
        if logger_id in seen_loggers:
            continue
        seen_loggers.add(logger_id)
        info = getattr(candidate, "info", None)
        if callable(info):
            info(usage_log, *usage_args)
    return True


def resolve_usage_loggers(
    logger: Any,
    *,
    logger_getter: Callable[[str], Any] = logging.getLogger,
) -> tuple[Any, ...]:
    """Return secondary loggers that should receive usage update telemetry."""

    try:
        uvicorn_logger = logger_getter("uvicorn.error")
    except Exception:
        return ()
    return (uvicorn_logger,) if uvicorn_logger is not logger else ()


async def apply_usage_to_core_latest_message(
    owner: Any,
    session_id: Any,
    usage: Any,
    *,
    logger: Any,
    logger_getter: Callable[[str], Any] = logging.getLogger,
) -> bool:
    """Apply OpenCode usage metadata using a core-like owner's bridge state."""

    return await apply_usage_to_latest_message(
        session_id,
        usage,
        stream_states=getattr(owner, "_opencode_stream_states", None),
        message_adapters=getattr(owner, "_opencode_message_adapters", None),
        get_adapter=owner._get_tui_adapter,
        logger=logger,
        extra_loggers=resolve_usage_loggers(logger, logger_getter=logger_getter),
    )
