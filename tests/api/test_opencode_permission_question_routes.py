"""Tests for OpenCode-compatible permission/question routes."""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from penguin.security.approval import get_approval_manager
from penguin.security.question import get_question_manager
from penguin.web.routes import (
    PermissionReplyAction,
    QuestionReplyAction,
    list_pending_permissions,
    list_pending_questions,
    reply_permission_request,
    reply_question_request,
    reject_question_request,
)


@pytest.mark.asyncio
async def test_permission_list_and_reply_once() -> None:
    manager = get_approval_manager()
    manager.reset()

    request = manager.create_request(
        tool_name="write_to_file",
        operation="filesystem.write",
        resource="src/app.py",
        reason="Write requires approval",
        session_id="sess_perm",
        context={"tool_input": {"path": "src/app.py"}},
    )

    pending = await list_pending_permissions(sessionID=None, session_id=None)
    assert isinstance(pending, list)
    assert pending
    match = next(item for item in pending if item["id"] == request.id)
    assert match["sessionID"] == "sess_perm"
    assert match["permission"] == "edit"

    replied = await reply_permission_request(
        request.id,
        PermissionReplyAction(reply="once"),
    )
    assert replied is True

    resolved = manager.get_request(request.id)
    assert resolved is not None
    assert resolved.status.value == "approved"


@pytest.mark.asyncio
async def test_permission_reply_rejects_invalid_choice() -> None:
    manager = get_approval_manager()
    manager.reset()

    request = manager.create_request(
        tool_name="execute_command",
        operation="process.execute",
        resource="rm -rf build",
        reason="Dangerous command",
        session_id="sess_perm_invalid",
    )

    with pytest.raises(HTTPException) as exc:
        await reply_permission_request(
            request.id,
            PermissionReplyAction(reply="maybe"),
        )
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_question_list_reply_and_reject() -> None:
    manager = get_question_manager()
    manager.reset()

    first = manager.create_request(
        session_id="sess_question",
        questions=[
            {
                "question": "Proceed with migration?",
                "header": "Migration",
                "options": [
                    {"label": "Yes", "description": "Continue migration"},
                    {"label": "No", "description": "Stop migration"},
                ],
            }
        ],
        tool={"messageID": "msg_1", "callID": "call_1"},
    )

    pending = await list_pending_questions(sessionID=None, session_id=None)
    assert any(item["id"] == first.id for item in pending)

    replied = await reply_question_request(
        first.id,
        QuestionReplyAction(answers=[["Yes"]]),
    )
    assert replied is True

    resolved = manager.get_request(first.id)
    assert resolved is not None
    assert resolved.status.value == "answered"

    second = manager.create_request(
        session_id="sess_question",
        questions=[
            {
                "question": "Apply patch?",
                "header": "Patch",
                "options": [
                    {"label": "Apply", "description": "Apply patch now"},
                    {"label": "Skip", "description": "Skip this patch"},
                ],
            }
        ],
    )

    rejected = await reject_question_request(second.id)
    assert rejected is True

    rejected_request = manager.get_request(second.id)
    assert rejected_request is not None
    assert rejected_request.status.value == "rejected"


@pytest.mark.asyncio
async def test_question_reply_missing_request_returns_404() -> None:
    manager = get_question_manager()
    manager.reset()

    with pytest.raises(HTTPException) as exc:
        await reply_question_request(
            "question_missing",
            QuestionReplyAction(answers=[["Any"]]),
        )
    assert exc.value.status_code == 404
