"""Focused tests for resumable approval state."""

from __future__ import annotations

import asyncio

import pytest

from penguin.security.approval import ApprovalStatus, get_approval_manager


@pytest.mark.asyncio
async def test_approved_request_can_be_consumed_exactly_once() -> None:
    """An approval wakes its waiter but grants only one matching execution."""
    manager = get_approval_manager()
    manager.reset()
    request = manager.create_request(
        tool_name="write_file",
        operation="tool.write_file",
        resource="notes.txt",
        reason="approval required",
        session_id="session_once",
    )

    waiter = asyncio.create_task(
        asyncio.to_thread(manager.wait_for_resolution, request.id, 1.0)
    )
    await asyncio.sleep(0)
    assert manager.approve(request.id) is not None
    resolved = await waiter

    assert resolved is not None
    assert resolved.status == ApprovalStatus.APPROVED
    claim = {
        "tool_name": "write_file",
        "operation": "tool.write_file",
        "resource": "notes.txt",
        "session_id": "session_once",
    }
    assert manager.consume_approved_request(request.id, **claim) is True
    assert manager.consume_approved_request(request.id, **claim) is False
    assert manager.approve(request.id) is None
    manager.reset()


@pytest.mark.asyncio
async def test_wait_timeout_expires_request_and_blocks_late_approval() -> None:
    """A timed-out wait closes the request instead of leaving stale work."""
    manager = get_approval_manager()
    manager.reset()
    request = manager.create_request(
        tool_name="execute_command",
        operation="tool.execute_command",
        resource="echo safe",
        reason="approval required",
        session_id="session_timeout",
    )

    resolved = await asyncio.to_thread(
        manager.wait_for_resolution,
        request.id,
        0.01,
    )

    assert resolved is not None
    assert resolved.status == ApprovalStatus.EXPIRED
    assert manager.approve(request.id) is None
    manager.reset()
