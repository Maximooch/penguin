"""An approval request carries the policy and mode that a remembered grant binds.

Covers SM-107: the ACP exact-grant key hashes ``permission_mode`` and
``approval_policy`` and stores ``agent_mode`` from the approval request's
context, so a remembered grant stops matching when they change. No request
carried those fields, so the binding was a constant.
"""

from __future__ import annotations

import json
import os
from typing import TYPE_CHECKING

from penguin.security.approval import get_approval_manager
from penguin.security.permission_engine import PermissionResult
from penguin.tools.tool_manager import ToolManager

if TYPE_CHECKING:
    import pytest


def test_the_approval_request_records_policy_and_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("PENGUIN_YOLO", raising=False)
    get_approval_manager().reset()
    manager = ToolManager({}, lambda *_args: None, fast_startup=True)
    monkeypatch.setattr(
        manager,
        "check_tool_permission",
        lambda *_args, **_kwargs: (PermissionResult.ASK, "needs approval"),
    )
    target = os.path.join(manager.workspace_root, "notes.txt")

    response = manager._permission_response(
        "write_file",
        {"path": target, "content": "x"},
        {
            "session_id": "ses_1",
            "agent_id": "default",
            "agent_mode": "build",
            "approval_policy": "on-request",
            "permission_mode": "workspace",
        },
    )

    payload = response if isinstance(response, dict) else json.loads(response)
    request = get_approval_manager().get_request(payload["approval_id"])
    assert request is not None
    assert request.context["agent_mode"] == "build"
    assert request.context["approval_policy"] == "on-request"
    assert request.context["permission_mode"] == "workspace"
