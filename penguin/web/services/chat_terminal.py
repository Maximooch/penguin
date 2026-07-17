"""Canonical chat terminal-state and continuation contracts."""

from __future__ import annotations

from typing import Any

__all__ = [
    "attach_chat_continuation",
    "build_continuation_prompt",
    "normalize_chat_terminal_result",
]


_COMPLETED_STATUSES = {
    "completed",
    "implicit_completion",
    "pending_review",
    "success",
}
_MAX_ITERATION_STATUSES = {"max_iterations", "iterations_exceeded"}
_STALLED_STATUSES = {
    "llm_empty_response_error",
    "repeated_empty_tool_only_iterations",
    "repeated_empty_response",
    "repeated_response",
    "request_gate_timeout",
    "tool_result_echo",
    "stalled",
}
_PROVIDER_EXHAUSTED_STATUSES = {
    "provider_recoverable_error",
    "provider_timeout",
    "provider_disconnect",
    "request_timeout",
}
_ABORTED_STATUSES = {"aborted"}
_CANCELLED_STATUSES = {"cancelled"}
_STOPPED_STATUSES = {"stopped"}

_RESUMABLE_STATUSES = (
    _MAX_ITERATION_STATUSES
    | _STALLED_STATUSES
    | _ABORTED_STATUSES
    | _CANCELLED_STATUSES
    | _STOPPED_STATUSES
)
_RETRYABLE_STATUSES = _PROVIDER_EXHAUSTED_STATUSES


def _terminal_status(process_result: dict[str, Any]) -> str:
    aborted = bool(process_result.get("aborted"))
    cancelled = bool(process_result.get("cancelled"))
    if aborted and cancelled:
        return "terminal_contract_error"

    raw_status = process_result.get("status")
    if isinstance(raw_status, str) and raw_status.strip():
        normalized = raw_status.strip()
        explicit_completed = process_result.get("completed")
        status_completed = normalized in _COMPLETED_STATUSES
        if (
            isinstance(explicit_completed, bool)
            and explicit_completed != status_completed
        ):
            return "terminal_contract_error"
        if process_result.get("error") and status_completed:
            return "terminal_contract_error"
        if status_completed and (aborted or cancelled):
            return "terminal_contract_error"
        if normalized in _ABORTED_STATUSES and cancelled:
            return "terminal_contract_error"
        if normalized in _CANCELLED_STATUSES and aborted:
            return "terminal_contract_error"
        return normalized
    if cancelled:
        return "cancelled"
    if aborted:
        return "aborted"
    if process_result.get("error"):
        return "error"
    response = process_result.get("assistant_response")
    action_results = process_result.get("action_results")
    if (isinstance(response, str) and response.strip()) or (
        isinstance(action_results, list) and bool(action_results)
    ):
        return "completed"
    return "terminal_contract_error"


def _visible_state(
    status: str,
    *,
    aborted: bool,
    cancelled: bool,
) -> str:
    if cancelled or status in _CANCELLED_STATUSES:
        return "cancelled"
    if aborted or status in _ABORTED_STATUSES:
        return "aborted"
    if status in _STOPPED_STATUSES:
        return "stopped"
    if status in _COMPLETED_STATUSES:
        return "completed"
    if status in _MAX_ITERATION_STATUSES:
        return "max_iterations"
    if status in _PROVIDER_EXHAUSTED_STATUSES:
        return "provider_exhausted"
    if status in _STALLED_STATUSES:
        return "stalled"
    return "failed"


def _action_payload(action: str) -> dict[str, Any]:
    label = "Retry" if action == "retry" else "Resume"
    return {
        "action": action,
        "label": label,
        "method": "POST",
        "endpoint": "/api/v1/chat/message",
        "requires_confirmation": True,
    }


def _continuation_payload(
    *,
    status: str,
    state: str,
    session_id: str | None,
    request_id: str | None,
    generation: int | None,
    request_context: dict[str, Any] | None,
    tool_boundary: dict[str, Any] | None,
) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    if state == "provider_exhausted" and status in _RETRYABLE_STATUSES:
        action = "retry"
    elif state in {
        "max_iterations",
        "stalled",
        "stopped",
        "aborted",
        "cancelled",
    }:
        action = "resume"
    else:
        return None, []

    action_payload = _action_payload(action)
    continuation_request: dict[str, Any] = {
        "continuation": {
            "action": action,
            "previous_status": status,
        }
    }
    if session_id:
        continuation_request["session_id"] = session_id
    if request_id:
        continuation_request["continuation"]["request_id"] = request_id
    if isinstance(generation, int) and not isinstance(generation, bool):
        continuation_request["continuation"]["generation"] = generation
    if isinstance(tool_boundary, dict):
        continuation_request["continuation"]["tool_boundary"] = dict(tool_boundary)
    if isinstance(request_context, dict):
        for key in (
            "directory",
            "model",
            "agent_id",
            "agent_mode",
            "variant",
            "service_tier",
        ):
            continuation_request[key] = request_context.get(key)

    return (
        {
            "available": True,
            **action_payload,
            "request": continuation_request,
        },
        [action_payload],
    )


def normalize_chat_terminal_result(
    process_result: dict[str, Any],
    *,
    session_id: str | None = None,
    request_id: str | None = None,
    continuation_generation: int | None = None,
    continuation_context: dict[str, Any] | None = None,
    continuation_tool_boundary: dict[str, Any] | None = None,
    allow_continuation: bool = True,
) -> dict[str, Any]:
    """Return one truthful REST/WebSocket terminal payload.

    HTTP success only describes transport success. ``completed`` and ``state``
    describe whether Penguin actually completed the requested turn.
    """

    status = _terminal_status(process_result)
    contract_error = status == "terminal_contract_error"
    aborted = not contract_error and (
        bool(process_result.get("aborted")) or status in _ABORTED_STATUSES
    )
    cancelled = not contract_error and (
        bool(process_result.get("cancelled")) or status in _CANCELLED_STATUSES
    )
    state = _visible_state(status, aborted=aborted, cancelled=cancelled)
    completed = state == "completed"

    recoverable_default = state in {
        "provider_exhausted",
        "max_iterations",
        "stalled",
        "stopped",
        "aborted",
        "cancelled",
    }
    recoverable = (
        bool(process_result.get("recoverable"))
        if "recoverable" in process_result
        else recoverable_default
    )

    response = process_result.get("assistant_response", "")
    if not isinstance(response, str):
        response = str(response or "")
    partial_response = process_result.get("partial_response")
    if not isinstance(partial_response, str):
        error_payload = process_result.get("error")
        provider_data = (
            error_payload.get("provider_data")
            if isinstance(error_payload, dict)
            else None
        )
        nested_partial = (
            provider_data.get("partial_output")
            if isinstance(provider_data, dict)
            else None
        )
        if isinstance(nested_partial, str):
            partial_response = nested_partial
    if not isinstance(partial_response, str):
        partial_response = "" if completed else response

    action_results = process_result.get("action_results")
    if not isinstance(action_results, list):
        action_results = []

    continuation, actions = _continuation_payload(
        status=status,
        state=state,
        session_id=session_id,
        request_id=request_id,
        generation=continuation_generation,
        request_context=continuation_context,
        tool_boundary=continuation_tool_boundary,
    )
    if not recoverable or not allow_continuation:
        continuation = None
        actions = []

    error = process_result.get("error")
    if status == "terminal_contract_error" and not error:
        error = {
            "code": "invalid_terminal_result",
            "message": "Penguin produced empty or contradictory terminal truth.",
        }

    payload: dict[str, Any] = {
        "response": response,
        "partial_response": partial_response,
        "action_results": action_results,
        "action_count": len(action_results),
        "status": status,
        "terminal_reason": status,
        "state": state,
        "completed": completed,
        "recoverable": recoverable,
        "aborted": aborted,
        "cancelled": cancelled,
        "iterations": process_result.get("iterations"),
        "error": error,
        "continuation": continuation,
        "actions": actions,
    }
    return payload


def attach_chat_continuation(
    terminal_payload: dict[str, Any],
    *,
    session_id: str,
    request_id: str,
    generation: int | None,
    request_context: dict[str, Any] | None,
    tool_boundary: dict[str, Any] | None,
    allow_continuation: bool,
) -> dict[str, Any]:
    """Attach the exact durable continuation request to a terminal snapshot."""

    payload = dict(terminal_payload)
    status = _terminal_status(payload)
    aborted = bool(payload.get("aborted")) or status in _ABORTED_STATUSES
    cancelled = bool(payload.get("cancelled")) or status in _CANCELLED_STATUSES
    state = str(
        payload.get("state")
        or _visible_state(
            status,
            aborted=aborted,
            cancelled=cancelled,
        )
    )
    continuation, actions = _continuation_payload(
        status=status,
        state=state,
        session_id=session_id,
        request_id=request_id,
        generation=generation,
        request_context=request_context,
        tool_boundary=tool_boundary,
    )
    recoverable = bool(payload.get("recoverable"))
    if not recoverable or not allow_continuation:
        continuation = None
        actions = []
    payload["continuation"] = continuation
    payload["actions"] = actions
    return payload


def build_continuation_prompt(
    *,
    action: str,
    previous_status: str,
    tool_boundary: dict[str, Any] | None = None,
) -> str:
    """Translate an explicit continuation action into a bounded model prompt."""

    normalized_action = action.strip().lower() if isinstance(action, str) else ""
    normalized_status = (
        previous_status.strip() if isinstance(previous_status, str) else ""
    )
    if normalized_action == "retry":
        if normalized_status not in _RETRYABLE_STATUSES:
            raise ValueError(
                f"retry is not valid after terminal status {normalized_status!r}"
            )
        prompt = (
            "Retry the interrupted provider turn from the current durable conversation "
            f"state. The previous request ended with {normalized_status}. Do not "
            "repeat completed work or re-run completed tools. Continue from the first "
            "incomplete operation and report any new terminal failure explicitly."
        )
        return _append_tool_boundary(prompt, tool_boundary)

    if normalized_action == "resume":
        if normalized_status not in _RESUMABLE_STATUSES:
            raise ValueError(
                f"resume is not valid after terminal status {normalized_status!r}"
            )
        prompt = (
            "Continue the current task from the current durable conversation state. "
            f"The previous turn ended with {normalized_status}. Do not repeat "
            "completed "
            "work. Inspect the existing results, continue from the first incomplete "
            "step, and report the next terminal state explicitly."
        )
        return _append_tool_boundary(prompt, tool_boundary)

    raise ValueError(f"unsupported continuation action {normalized_action!r}")


def _append_tool_boundary(
    prompt: str,
    tool_boundary: dict[str, Any] | None,
) -> str:
    if not isinstance(tool_boundary, dict):
        return prompt
    count = tool_boundary.get("completed_action_count")
    fingerprint = tool_boundary.get("fingerprint")
    if not isinstance(count, int) or not isinstance(fingerprint, str):
        return prompt
    return (
        f"{prompt} The durable completed-tool boundary contains {count} completed "
        f"action(s) with fingerprint {fingerprint}; treat every action at or before "
        "that boundary as already applied."
    )
