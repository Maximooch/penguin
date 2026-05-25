"""Action execution result-shaping helpers for :mod:`penguin.core`."""

from __future__ import annotations

from typing import Any, Callable

from penguin.utils.log_error import log_error as default_log_error

__all__ = [
    "execute_action",
]


async def execute_action(
    owner: Any,
    action: Any,
    *,
    log_error: Callable[..., Any] = default_log_error,
) -> dict[str, Any]:
    """Execute an action and return PenguinCore-compatible structured output."""

    action_name = _action_name(action)
    try:
        result = await owner.action_executor.execute_action(action)
        return {
            "action": action_name,
            "result": str(result) if result is not None else "",
            "status": "completed",
        }
    except Exception as exc:
        log_error(
            exc,
            context={
                "component": "core",
                "method": "execute_action",
                "action": action_name,
            },
        )
        return {
            "action": action_name,
            "result": f"Error: {exc}",
            "status": "error",
        }


def _action_name(action: Any) -> str:
    action_type = getattr(action, "action_type", None)
    value = getattr(action_type, "value", None)
    if isinstance(value, str):
        return value
    if value is not None:
        return str(value)
    if isinstance(action_type, str):
        return action_type
    return str(action_type or "unknown")
