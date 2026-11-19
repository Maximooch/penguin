"""Permission events reach clients whichever surface raises or answers them."""

from __future__ import annotations

from typing import Any

import pytest

from penguin.security.approval import ApprovalStatus, get_approval_manager
from penguin.web import routes


@pytest.fixture
def approvals(monkeypatch: pytest.MonkeyPatch):
    manager = get_approval_manager()
    manager.reset()
    # Listeners registered by earlier tests would deliver each event twice.
    manager._on_request_created.clear()
    manager._on_request_resolved.clear()
    monkeypatch.setattr(routes, "_approval_callbacks_registered", False)
    events: list[tuple[str, dict[str, Any]]] = []
    monkeypatch.setattr(
        routes,
        "_schedule_opencode_event",
        lambda event_type, payload: events.append((event_type, payload)),
    )
    yield manager, events
    manager.reset()
    manager._on_request_created.clear()
    manager._on_request_resolved.clear()


def _request(manager):
    return manager.create_request(
        tool_name="write_file",
        operation="filesystem.write",
        resource="notes.txt",
        reason="test",
        session_id="s1",
    )


def test_websocket_failure_does_not_swallow_permission_asked(
    approvals, monkeypatch: pytest.MonkeyPatch
) -> None:
    manager, events = approvals

    def broken(*_args: Any, **_kwargs: Any) -> None:
        raise RuntimeError("no event loop for websocket send")

    monkeypatch.setattr(routes._approval_ws_manager, "send_approval_required", broken)
    routes._setup_approval_websocket_callbacks()

    _request(manager)

    assert [event_type for event_type, _ in events] == ["permission.asked"]


@pytest.mark.asyncio
async def test_approvals_endpoints_emit_permission_replied(approvals) -> None:
    manager, events = approvals
    request = _request(manager)

    await routes.deny_request(request.id)

    assert "permission.replied" in [event_type for event_type, _ in events]


@pytest.mark.asyncio
async def test_reject_message_is_visible_to_resolution_listeners(approvals) -> None:
    manager, _events = approvals
    request = _request(manager)
    seen: list[Any] = []
    manager.on_request_resolved(lambda item: seen.append(item.context.get("message")))

    await routes.reply_permission_request(
        request.id, routes.PermissionReplyAction(reply="reject", message="not this file")
    )

    assert manager.get_request(request.id).status == ApprovalStatus.DENIED
    assert seen == ["not this file"]
