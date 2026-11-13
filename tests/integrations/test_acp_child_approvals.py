"""Pending child permissions follow child lifetime and aggregate wait state."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

pytest.importorskip("acp")
from acp.schema import AllowedOutcome, RequestPermissionResponse
from test_acp_sessions import PersistentCore

from penguin.integrations.acp.children import Child
from penguin.integrations.acp.server import PenguinACPAgent
from penguin.security.approval import get_approval_manager


async def wait_until(predicate):
    for _ in range(100):
        if predicate():
            return
        await asyncio.sleep(0.005)
    raise AssertionError("condition not reached")


@pytest.mark.asyncio
async def test_two_permissions_keep_child_waiting_until_last_reply(tmp_path):
    manager = get_approval_manager()
    manager.reset()
    agent = PenguinACPAgent(
        PersistentCore(tmp_path / "store"), allowed_roots=(tmp_path,)
    )
    conn = AsyncMock()
    agent.on_connect(conn)
    agent._transport = SimpleNamespace(subagents=True, send=AsyncMock())
    await agent.initialize(1)
    root = (await agent.new_session(str(tmp_path))).session_id
    child_task = asyncio.create_task(asyncio.Event().wait())
    agent._children.children["child"] = Child(
        root, root, "worker", tmp_path, task=child_task, cancellable=True
    )
    replies = {"one": asyncio.Event(), "two": asyncio.Event()}

    async def permission(**kwargs):
        name = kwargs["tool_call"].title.split(": ")[-1]
        await replies[name].wait()
        return RequestPermissionResponse(
            outcome=AllowedOutcome(outcome="selected", option_id="allow_once")
        )

    conn.request_permission.side_effect = permission
    try:
        one = manager.create_request(
            "read", "filesystem.read", "one", "test", session_id="child"
        )
        two = manager.create_request(
            "read", "filesystem.read", "two", "test", session_id="child"
        )
        await wait_until(lambda: conn.request_permission.await_count == 2)
        replies["one"].set()
        await wait_until(lambda: manager.get_request(one.id).status.value == "approved")
        await asyncio.sleep(0.01)
        assert agent._transport.send.call_args.args[0]["params"]["update"]["state"] == {
            "state": "requires_action"
        }
        replies["two"].set()
        await wait_until(lambda: manager.get_request(two.id).status.value == "approved")
        await wait_until(lambda: not agent._approval_tasks)
        assert agent._transport.send.call_args.args[0]["params"]["update"]["state"] == {
            "state": "running"
        }
    finally:
        child_task.cancel()
        await asyncio.gather(child_task, return_exceptions=True)
        agent.close()
        manager.reset()


@pytest.mark.asyncio
@pytest.mark.parametrize("action", ["cancel", "close", "finish"])
async def test_child_lifetime_denies_pending_and_cancels_waiters(tmp_path, action):
    manager = get_approval_manager()
    manager.reset()
    core = PersistentCore(tmp_path / "store")
    agent = PenguinACPAgent(core, allowed_roots=(tmp_path,))
    conn = AsyncMock()

    async def permission(**kwargs):
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            # A late client result must not resurrect a request already denied.
            return RequestPermissionResponse(
                outcome=AllowedOutcome(outcome="selected", option_id="allow_once")
            )

    conn.request_permission.side_effect = permission
    agent.on_connect(conn)
    agent._transport = SimpleNamespace(subagents=True, send=AsyncMock())
    await agent.initialize(1)
    root = (await agent.new_session(str(tmp_path))).session_id
    child_task = asyncio.create_task(asyncio.Event().wait())
    agent._children.children["child"] = Child(
        root, root, "worker", tmp_path, task=child_task, cancellable=True
    )
    try:
        request = manager.create_request(
            "write", "filesystem.write", "file", "test", session_id="child"
        )
        other = manager.create_request(
            "write", "filesystem.write", "other", "test", session_id="child"
        )
        await wait_until(lambda: conn.request_permission.await_count == 2)
        if action == "cancel":
            await agent.cancel("child")
        elif action == "close":
            await agent.close_session(root)
        else:
            await core.event_bus.emit(
                "agent.lifecycle",
                {
                    "parent_session_id": root,
                    "session_id": "child",
                    "state": "completed",
                    "directory": str(tmp_path),
                },
            )
        await wait_until(lambda: not agent._approval_tasks)
        assert manager.get_request(request.id).status.value == "denied"
        assert manager.get_request(other.id).status.value == "denied"
        assert not manager.get_pending("child")
        assert not agent._approval_tasks_by_session.get("child")
    finally:
        child_task.cancel()
        await asyncio.gather(child_task, return_exceptions=True)
        agent.close()
        manager.reset()
