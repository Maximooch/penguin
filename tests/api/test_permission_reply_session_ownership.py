"""A permission reply must come from the session the request belongs to (SM-05).

Neither reply surface checked whose request it was answering: any client
could approve or deny another session's pending request by id. A reply now
names its session (body ``sessionID`` or the ``X-Penguin-Session-Id`` header),
and a reply that names a different session is refused and leaves the request
pending.
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from penguin.security.approval import ApprovalStatus
from penguin.web import routes
from tests.api.test_permission_reply_surfaces import _request, approvals  # noqa: F401


async def _reply(request_id: str, **session: str | None):
    return await routes.reply_permission_request(
        request_id,
        routes.PermissionReplyAction(reply="once", sessionID=session.get("body")),
        x_penguin_session_id=session.get("header"),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("source", ["body", "header"])
async def test_a_reply_from_another_session_is_refused(approvals, source) -> None:  # noqa: F811
    manager, _events = approvals
    request = _request(manager)  # belongs to session "s1"

    with pytest.raises(HTTPException) as refused:
        await _reply(request.id, **{source: "s2"})

    assert refused.value.status_code == 403
    assert manager.get_request(request.id).status == ApprovalStatus.PENDING


@pytest.mark.asyncio
@pytest.mark.parametrize("source", ["body", "header"])
async def test_a_reply_from_the_owning_session_resolves(approvals, source) -> None:  # noqa: F811
    manager, _events = approvals
    request = _request(manager)

    assert await _reply(request.id, **{source: "s1"}) is True
    assert manager.get_request(request.id).status == ApprovalStatus.APPROVED


@pytest.mark.asyncio
async def test_approve_and_deny_refuse_another_session(approvals) -> None:  # noqa: F811
    manager, _events = approvals
    first, second = _request(manager), _request(manager)

    with pytest.raises(HTTPException) as approve:
        await routes.approve_request(
            first.id, routes.ApprovalAction(scope="once", session_id="s2")
        )
    with pytest.raises(HTTPException) as deny:
        await routes.deny_request(second.id, routes.ApprovalDenyAction(session_id="s2"))

    assert (approve.value.status_code, deny.value.status_code) == (403, 403)
    assert manager.get_request(first.id).status == ApprovalStatus.PENDING
    assert manager.get_request(second.id).status == ApprovalStatus.PENDING


@pytest.mark.asyncio
async def test_a_reply_without_a_session_follows_the_setting(
    approvals,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager, _events = approvals
    strict, lenient = _request(manager), _request(manager)

    monkeypatch.setenv("PENGUIN_PERMISSION_REPLY_REQUIRE_SESSION", "true")
    with pytest.raises(HTTPException) as refused:
        await _reply(strict.id)
    assert refused.value.status_code == 400
    assert manager.get_request(strict.id).status == ApprovalStatus.PENDING

    monkeypatch.delenv("PENGUIN_PERMISSION_REPLY_REQUIRE_SESSION")
    assert await _reply(lenient.id) is True


def test_over_http_the_header_and_an_empty_body_work(approvals) -> None:  # noqa: F811
    """What real clients send: Link posts no session; the TUI sends the header."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    manager, _events = approvals
    app = FastAPI()
    app.include_router(routes.router)
    client = TestClient(app)
    first, second = _request(manager), _request(manager)

    wrong = client.post(
        f"/api/v1/permission/{first.id}/reply",
        json={"reply": "once"},
        headers={"X-Penguin-Session-Id": "s2"},
    )
    right = client.post(
        f"/api/v1/permission/{first.id}/reply",
        json={"reply": "once"},
        headers={"X-Penguin-Session-Id": "s1"},
    )
    no_body = client.post(f"/api/v1/approvals/{second.id}/deny")

    assert (wrong.status_code, right.status_code, no_body.status_code) == (
        403,
        200,
        200,
    )
    assert manager.get_request(first.id).status == ApprovalStatus.APPROVED
    assert manager.get_request(second.id).status == ApprovalStatus.DENIED
