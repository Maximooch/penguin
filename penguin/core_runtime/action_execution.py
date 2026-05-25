"""Action execution result-shaping helpers for :mod:`penguin.core`."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from penguin.utils.log_error import log_error as default_log_error
from penguin.utils.parser import parse_action as default_parse_action

__all__ = [
    "ResponseActionProcessingResult",
    "execute_action",
    "process_response_actions",
]


FINISH_ACTIONS = {"finish_response", "finish_task", "task_completed"}


@dataclass(frozen=True)
class ResponseActionProcessingResult:
    """Structured result from processing parsed assistant-response actions."""

    actions: list[Any]
    action_results: list[dict[str, Any]]
    exit_continuation: bool


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


async def process_response_actions(
    owner: Any,
    assistant_response: str,
    *,
    parse_actions: Callable[[str], list[Any]] = default_parse_action,
    log: Any,
) -> ResponseActionProcessingResult:
    """Parse and execute response actions with legacy PenguinCore semantics."""

    actions = parse_actions(assistant_response)
    exit_continuation = any(
        _action_name(action) in FINISH_ACTIONS for action in actions
    )

    action_results: list[dict[str, Any]] = []
    for action in actions:
        action_name = _action_name(action)
        if owner._check_interrupt():
            action_results.append(
                {
                    "action": action_name,
                    "result": "Action skipped due to interrupt",
                    "status": "interrupted",
                }
            )
            continue

        try:
            result = await owner.action_executor.execute_action(action)
            if result is not None:
                result_text = str(result)
                action_results.append(
                    {
                        "action": action_name,
                        "result": result_text,
                        "status": "completed",
                    }
                )
                owner.conversation_manager.add_action_result(
                    action_type=action_name,
                    result=result_text,
                    status="completed",
                )
        except Exception as exc:
            result_text = f"Error executing action: {exc}"
            error_result = {
                "action": action_name,
                "result": result_text,
                "status": "error",
            }
            action_results.append(error_result)
            owner.conversation_manager.add_action_result(
                action_type=action_name,
                result=result_text,
                status="error",
            )
            log.error("Action execution error: %s", exc)

    return ResponseActionProcessingResult(
        actions=actions,
        action_results=action_results,
        exit_continuation=exit_continuation,
    )
