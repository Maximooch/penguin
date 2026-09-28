"""Validation helpers for sub-agent admission requests."""

from __future__ import annotations

from typing import Any, Mapping

__all__ = ["validate_spawn_request"]

_ALLOWED_FIELDS = {
    "_tool_call_id",
    "background",
    "default_tools",
    "id",
    "initial_prompt",
    "model_config_id",
    "model_output_max_tokens",
    "model_overrides",
    "parent",
    "persona",
    "share_context_window",
    "share_session",
    "shared_context_window_max_tokens",
    "shared_cw_max_tokens",
    "system_prompt",
    "tool_call_id",
}


def validate_spawn_request(payload: Mapping[str, Any]) -> None:
    """Validate a spawn request before any lifecycle state is mutated.

    Raises:
        ValueError: If a supplied field is unknown or has an invalid type/value.
    """

    unknown = sorted(set(payload) - _ALLOWED_FIELDS)
    if unknown:
        raise ValueError(f"Unknown spawn_sub_agent fields: {', '.join(unknown)}")

    for field_name in ("id", "parent", "persona", "model_config_id"):
        if field_name not in payload or payload[field_name] is None:
            continue
        value = payload[field_name]
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{field_name} must be a non-empty string")

    for field_name in ("system_prompt", "initial_prompt"):
        if field_name in payload and payload[field_name] is not None:
            if not isinstance(payload[field_name], str):
                raise ValueError(f"{field_name} must be a string")

    for field_name in ("share_session", "share_context_window", "background"):
        if field_name in payload and not isinstance(payload[field_name], bool):
            raise ValueError(f"{field_name} must be a boolean")

    for field_name in (
        "shared_context_window_max_tokens",
        "shared_cw_max_tokens",
        "model_output_max_tokens",
    ):
        if field_name not in payload or payload[field_name] is None:
            continue
        value = payload[field_name]
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise ValueError(f"{field_name} must be a positive integer")

    if (
        "shared_context_window_max_tokens" in payload
        and "shared_cw_max_tokens" in payload
        and payload["shared_context_window_max_tokens"]
        != payload["shared_cw_max_tokens"]
    ):
        raise ValueError("Conflicting shared context window token limits")

    if "model_overrides" in payload and payload["model_overrides"] is not None:
        if not isinstance(payload["model_overrides"], dict):
            raise ValueError("model_overrides must be an object")

    if "default_tools" in payload and payload["default_tools"] is not None:
        default_tools = payload["default_tools"]
        if not isinstance(default_tools, list) or any(
            not isinstance(name, str) or not name.strip() for name in default_tools
        ):
            raise ValueError("default_tools must be a list of non-empty strings")
