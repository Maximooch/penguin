"""OpenCode 2 projections for Penguin approvals and questions."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from penguin.security.approval import (
    ApprovalRequest,
    ApprovalScope,
    ApprovalStatus,
    get_approval_manager,
)
from penguin.security.question import (
    QuestionRequest,
    QuestionStatus,
    get_question_manager,
)

__all__ = [
    "InteractionNotFoundError",
    "InteractionPayloadError",
    "InteractionSettledError",
    "cancel_form_request",
    "form_id_for_question",
    "get_form_payload",
    "get_permission_payload",
    "interaction_event_projection",
    "list_form_payloads",
    "list_permission_payloads",
    "permission_id_for_approval",
    "reply_form_request",
    "reply_permission_request",
]


_PERMISSION_ACTIONS = {
    "apply_diff": "edit",
    "code_execution": "shell",
    "create_file": "edit",
    "create_folder": "edit",
    "delegate": "subagent",
    "delegate_explore_task": "subagent",
    "delete_lines": "edit",
    "edit_with_pattern": "edit",
    "enhanced_read": "read",
    "enhanced_write": "edit",
    "execute_command": "shell",
    "find_file": "glob",
    "get_file_map": "list",
    "grep_search": "grep",
    "insert_lines": "edit",
    "list_files": "list",
    "multiedit_apply": "edit",
    "patch_file": "edit",
    "patch_files": "edit",
    "read_file": "read",
    "replace_lines": "edit",
    "spawn_sub_agent": "subagent",
    "webfetch": "webfetch",
    "write_file": "edit",
    "write_to_file": "edit",
}
_PERMISSION_REPLIES = {"once", "always", "reject"}


class InteractionPayloadError(ValueError):
    """Raised when an interaction payload cannot satisfy the V2 contract."""


class InteractionNotFoundError(LookupError):
    """Raised when a session does not own the requested interaction."""


class InteractionSettledError(RuntimeError):
    """Raised when a form has already been answered or cancelled."""


def permission_id_for_approval(request_id: str) -> str:
    """Return the stable V2 permission ID for a Penguin approval ID."""
    return f"per_{request_id}"


def form_id_for_question(request_id: str) -> str:
    """Return the stable V2 form ID for a Penguin question ID."""
    return f"frm_{request_id}"


def list_permission_payloads(session_id: str | None = None) -> list[dict[str, Any]]:
    """List pending Penguin approvals in V2 Permission.Request shape."""
    manager = get_approval_manager()
    return [
        _approval_payload(request)
        for request in manager.get_pending(session_id=session_id)
    ]


def get_permission_payload(session_id: str, request_id: str) -> dict[str, Any] | None:
    """Return one pending V2 permission owned by ``session_id``."""
    request = _approval_for_id(session_id, request_id)
    return _approval_payload(request) if request else None


def reply_permission_request(
    session_id: str,
    request_id: str,
    payload: Mapping[str, Any],
) -> None:
    """Resolve one Penguin approval through the V2 reply contract."""
    reply = _string(payload.get("reply"))
    if reply not in _PERMISSION_REPLIES:
        raise InteractionPayloadError("reply must be one of: once, always, reject")
    message = payload.get("message")
    if message is not None and not isinstance(message, str):
        raise InteractionPayloadError("message must be a string")

    request = _approval_for_id(session_id, request_id)
    if request is None:
        raise InteractionNotFoundError(request_id)
    manager = get_approval_manager()
    if reply == "reject":
        resolved = manager.deny(request.id)
        if resolved and isinstance(message, str) and message.strip():
            resolved.context["message"] = message.strip()
    elif reply == "once":
        resolved = manager.approve(request.id, scope=ApprovalScope.ONCE)
    else:
        resolved = manager.approve(
            request.id,
            scope=ApprovalScope.PATTERN,
            pattern=_string(request.resource) or "*",
        )
    if resolved is None:
        raise InteractionNotFoundError(request_id)


def list_form_payloads(session_id: str | None = None) -> list[dict[str, Any]]:
    """List valid pending Penguin questions as V2 forms."""
    manager = get_question_manager()
    return [
        form
        for request in manager.list_pending(session_id=session_id)
        if (form := _question_form(request)) is not None
    ]


def get_form_payload(session_id: str, form_id: str) -> dict[str, Any] | None:
    """Return one pending or retained V2 form owned by ``session_id``."""
    request = _question_for_id(session_id, form_id)
    return _question_form(request) if request else None


def reply_form_request(
    session_id: str,
    form_id: str,
    payload: Mapping[str, Any],
) -> None:
    """Translate a V2 answer object into ordered Penguin question answers."""
    request = _question_for_id(session_id, form_id)
    if request is None:
        raise InteractionNotFoundError(form_id)
    if request.status != QuestionStatus.PENDING:
        raise InteractionSettledError(form_id)
    answer = payload.get("answer")
    if not isinstance(answer, Mapping):
        raise InteractionPayloadError("answer must be an object")
    answers = _ordered_question_answers(request, answer)
    if get_question_manager().reply(request.id, answers) is None:
        raise InteractionSettledError(form_id)


def cancel_form_request(session_id: str, form_id: str) -> None:
    """Cancel a pending V2 form through Penguin's question manager."""
    request = _question_for_id(session_id, form_id)
    if request is None:
        raise InteractionNotFoundError(form_id)
    if request.status != QuestionStatus.PENDING:
        raise InteractionSettledError(form_id)
    if get_question_manager().reject(request.id) is None:
        raise InteractionSettledError(form_id)


def interaction_event_projection(
    event_type: str,
    properties: Mapping[str, Any],
) -> tuple[str, dict[str, Any]] | None:
    """Translate legacy approval/question properties into V2 event data."""
    try:
        if event_type == "permission.asked":
            request = _permission_event_payload(properties)
            return (event_type, request) if request else None
        if event_type == "permission.replied":
            request_id = _string(properties.get("requestID"))
            session_id = _string(properties.get("sessionID"))
            reply = _string(properties.get("reply"))
            if not request_id or not session_id or reply not in _PERMISSION_REPLIES:
                return None
            return (
                event_type,
                {
                    "sessionID": session_id,
                    "requestID": permission_id_for_approval(request_id),
                    "reply": reply,
                },
            )
        if event_type == "question.asked":
            form = _question_form_from_mapping(properties)
            return ("form.created", {"form": form}) if form else None
        if event_type == "question.replied":
            request_id = _string(properties.get("requestID"))
            session_id = _string(properties.get("sessionID"))
            answers = properties.get("answers")
            if not request_id or not session_id or not isinstance(answers, list):
                return None
            request = get_question_manager().get_request(request_id)
            if request is None or request.session_id != session_id:
                return None
            answer = _form_answer_from_ordered(request, answers)
            return (
                "form.replied",
                {
                    "id": form_id_for_question(request_id),
                    "sessionID": session_id,
                    "answer": answer,
                },
            )
        if event_type == "question.rejected":
            request_id = _string(properties.get("requestID"))
            session_id = _string(properties.get("sessionID"))
            if not request_id or not session_id:
                return None
            return (
                "form.cancelled",
                {
                    "id": form_id_for_question(request_id),
                    "sessionID": session_id,
                },
            )
    except InteractionPayloadError:
        return None
    return None


def _approval_for_id(session_id: str, request_id: str) -> ApprovalRequest | None:
    raw_id = _legacy_id(request_id, "per_")
    if raw_id is None:
        return None
    request = get_approval_manager().get_request(raw_id)
    if (
        request is None
        or request.session_id != session_id
        or request.status != ApprovalStatus.PENDING
    ):
        return None
    return request


def _approval_payload(request: ApprovalRequest) -> dict[str, Any]:
    resource = _string(request.resource) or "*"
    context = request.context if isinstance(request.context, dict) else {}
    metadata: dict[str, Any] = {
        "reason": request.reason,
        "operation": request.operation,
        "tool_name": request.tool_name,
        "resource": request.resource,
    }
    tool_input = context.get("tool_input")
    if isinstance(tool_input, dict):
        metadata.update(tool_input)
    payload: dict[str, Any] = {
        "id": permission_id_for_approval(request.id),
        "sessionID": request.session_id or "",
        "action": _permission_action(request.tool_name, request.operation),
        "resources": [resource],
        "save": [resource],
        "metadata": metadata,
    }
    source = _tool_source(context.get("tool"))
    if source:
        payload["source"] = source
    return payload


def _permission_event_payload(properties: Mapping[str, Any]) -> dict[str, Any] | None:
    request_id = _string(properties.get("id"))
    session_id = _string(properties.get("sessionID"))
    action = _string(properties.get("permission"))
    resources = _string_list(properties.get("patterns"))
    if not request_id or not session_id or not action:
        return None
    payload: dict[str, Any] = {
        "id": permission_id_for_approval(request_id),
        "sessionID": session_id,
        "action": _native_permission_action(action),
        "resources": resources or ["*"],
    }
    save = _string_list(properties.get("always"))
    if save:
        payload["save"] = save
    metadata = properties.get("metadata")
    if isinstance(metadata, Mapping):
        payload["metadata"] = dict(metadata)
    source = _tool_source(properties.get("tool"))
    if source:
        payload["source"] = source
    return payload


def _permission_action(tool_name: str, operation: str) -> str:
    tool = _string(tool_name)
    if tool and tool in _PERMISSION_ACTIONS:
        return _PERMISSION_ACTIONS[tool]
    normalized = (_string(operation) or "").lower()
    if normalized.startswith("filesystem.read"):
        return "read"
    if normalized.startswith("filesystem.list"):
        return "list"
    if normalized.startswith("filesystem"):
        return "edit"
    if normalized.startswith("process"):
        return "shell"
    if normalized.startswith("network.fetch"):
        return "webfetch"
    return "tool"


def _native_permission_action(action: str) -> str:
    return {"bash": "shell", "task": "subagent"}.get(action, action)


def _tool_source(value: Any) -> dict[str, str] | None:
    if not isinstance(value, Mapping):
        return None
    message_id = _string(value.get("messageID"))
    call_id = _string(value.get("callID")) or _string(value.get("id"))
    if not message_id or not call_id:
        return None
    return {"type": "tool", "messageID": message_id, "id": call_id}


def _question_for_id(session_id: str, form_id: str) -> QuestionRequest | None:
    raw_id = _legacy_id(form_id, "frm_")
    if raw_id is None:
        return None
    request = get_question_manager().get_request(raw_id)
    if request is None or request.session_id != session_id:
        return None
    return request


def _question_form(request: QuestionRequest) -> dict[str, Any] | None:
    return _question_form_from_mapping(request.to_dict())


def _question_form_from_mapping(value: Mapping[str, Any]) -> dict[str, Any] | None:
    request_id = _string(value.get("id"))
    session_id = _string(value.get("sessionID"))
    questions = value.get("questions")
    if (
        not request_id
        or not session_id
        or not isinstance(questions, list)
        or not questions
    ):
        return None
    fields: list[dict[str, Any]] = []
    for index, question in enumerate(questions):
        field = _question_field(index, question)
        if field is None:
            return None
        fields.append(field)
    first_title = (
        _string(questions[0].get("header"))
        if isinstance(questions[0], Mapping)
        else None
    )
    return {
        "id": form_id_for_question(request_id),
        "sessionID": session_id,
        "title": first_title if len(fields) == 1 and first_title else "Questions",
        "fields": fields,
    }


def _question_field(index: int, value: Any) -> dict[str, Any] | None:
    if not isinstance(value, Mapping):
        return None
    question = _string(value.get("question"))
    header = _string(value.get("header"))
    raw_options = value.get("options")
    if not question or not header or not isinstance(raw_options, list):
        return None
    options: list[dict[str, Any]] = []
    for raw_option in raw_options:
        if not isinstance(raw_option, Mapping):
            return None
        label = _string(raw_option.get("label"))
        if not label:
            return None
        option: dict[str, Any] = {"value": label, "label": label}
        description = _string(raw_option.get("description"))
        if description:
            option["description"] = description
        options.append(option)
    if not options:
        return None
    common: dict[str, Any] = {
        "key": _question_key(index),
        "title": header,
        "description": question,
        "required": True,
        "options": options,
        "custom": value.get("custom")
        if isinstance(value.get("custom"), bool)
        else True,
    }
    if value.get("multiple") is True:
        return {**common, "type": "multiselect"}
    return {**common, "type": "string"}


def _ordered_question_answers(
    request: QuestionRequest,
    answer: Mapping[str, Any],
) -> list[list[str]]:
    expected = {_question_key(index) for index in range(len(request.questions))}
    if set(answer) != expected:
        unknown = sorted(set(answer) - expected)
        missing = sorted(expected - set(answer))
        detail = (
            f"unknown fields: {', '.join(unknown)}"
            if unknown
            else f"missing fields: {', '.join(missing)}"
        )
        raise InteractionPayloadError(detail)

    ordered: list[list[str]] = []
    for index, question in enumerate(request.questions):
        if not isinstance(question, Mapping):
            raise InteractionPayloadError("question request is malformed")
        value = answer[_question_key(index)]
        multiple = question.get("multiple") is True
        if multiple:
            if (
                not isinstance(value, list)
                or not value
                or not all(isinstance(item, str) and item for item in value)
            ):
                raise InteractionPayloadError(
                    f"expected a non-empty string array for {_question_key(index)}"
                )
            selected = list(value)
        else:
            if not isinstance(value, str) or not value:
                raise InteractionPayloadError(
                    f"expected a non-empty string for {_question_key(index)}"
                )
            selected = [value]
        if question.get("custom") is False:
            labels = {
                item.get("label")
                for item in question.get("options", [])
                if isinstance(item, Mapping)
            }
            if any(item not in labels for item in selected):
                raise InteractionPayloadError(
                    f"invalid option for {_question_key(index)}"
                )
        ordered.append(selected)
    return ordered


def _form_answer_from_ordered(
    request: QuestionRequest,
    answers: list[Any],
) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for index, question in enumerate(request.questions):
        values = answers[index] if index < len(answers) else []
        values = values if isinstance(values, list) else []
        strings = [item for item in values if isinstance(item, str)]
        if isinstance(question, Mapping) and question.get("multiple") is True:
            result[_question_key(index)] = strings
        else:
            result[_question_key(index)] = strings[0] if strings else ""
    return result


def _question_key(index: int) -> str:
    return f"question_{index}"


def _legacy_id(value: str, prefix: str) -> str | None:
    return (
        value[len(prefix) :]
        if value.startswith(prefix) and len(value) > len(prefix)
        else None
    )


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item.strip() for item in value if isinstance(item, str) and item.strip()]


def _string(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None
