"""An approval request is resolved once, with the scope that was really granted."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import TYPE_CHECKING

import pytest

from penguin.security import approval as approval_module
from penguin.security.approval import (
    ApprovalManager,
    ApprovalScope,
    ApprovalStatus,
    get_approval_manager,
)

if TYPE_CHECKING:
    from collections.abc import Iterator


@pytest.fixture
def approvals() -> Iterator[ApprovalManager]:
    manager = get_approval_manager()
    manager.reset()
    yield manager
    manager.reset()


def _request(approvals: ApprovalManager, session_id: str | None = "s1"):
    return approvals.create_request(
        tool_name="write_file",
        operation="filesystem.write",
        resource="notes.txt",
        reason="test",
        session_id=session_id,
    )


def test_expired_request_cannot_be_approved(approvals: ApprovalManager) -> None:
    request = _request(approvals)
    request.expires_at = datetime.utcnow() - timedelta(seconds=1)
    resolved: list[ApprovalStatus] = []
    approvals.on_request_resolved(lambda item: resolved.append(item.status))

    assert approvals.approve(request.id, scope=ApprovalScope.SESSION) is None

    stored = approvals.get_request(request.id)
    assert stored is not None
    assert stored.status == ApprovalStatus.EXPIRED
    assert approvals.get_session_approvals("s1") == []
    assert resolved == [ApprovalStatus.EXPIRED]


def test_session_scope_without_a_session_is_recorded_as_once(
    approvals: ApprovalManager,
) -> None:
    request = _request(approvals, session_id=None)

    resolved = approvals.approve(request.id, scope=ApprovalScope.SESSION)

    assert resolved is not None
    assert resolved.resolution_scope == ApprovalScope.ONCE


def test_pattern_scope_without_a_pattern_is_recorded_as_once(
    approvals: ApprovalManager,
) -> None:
    request = _request(approvals)

    resolved = approvals.approve(request.id, scope=ApprovalScope.PATTERN)

    assert resolved is not None
    assert resolved.resolution_scope == ApprovalScope.ONCE
    assert approvals.get_session_approvals("s1") == []


def test_resolved_history_is_bounded(
    approvals: ApprovalManager, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(approval_module, "MAX_RESOLVED_HISTORY", 3)
    ids = []
    for _ in range(5):
        request = _request(approvals)
        ids.append(request.id)
        approvals.deny(request.id)

    assert [approvals.get_request(item) is not None for item in ids] == [
        False,
        False,
        True,
        True,
        True,
    ]
