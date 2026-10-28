"""Optional draft child-session presentation with a stable v1 fallback."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4

from acp.helpers import text_block
from acp.schema import (
    AgentMessageChunk,
    ContentToolCallContent,
    ToolCallProgress,
    ToolCallStart,
)

from penguin.integrations.acp.events import bounded

__all__ = ["ChildTracker"]


@dataclass
class Child:
    parent: str
    root: str
    agent: str
    cwd: Path
    task: Any = None
    active: bool = True
    streamed: bool = False
    cancellable: bool = False
    cancelled: bool = False


class ChildTracker:
    """Track only runtime-observed ownership; never infer parentage from names."""

    def __init__(self, owner: Any) -> None:
        self.owner = owner
        self.children: dict[str, Child] = {}
        self.replay_known: dict[str, set[str]] = {}
        self.replay_parents: dict[str, str] = {}
        self.handler = self.on_event
        bus = getattr(owner.core, "event_bus", None)
        self.bus = bus
        if bus is not None:
            bus.subscribe("agent.lifecycle", self.handler)
            bus.subscribe("stream_chunk", self.handler)

    @property
    def native(self) -> bool:
        transport = getattr(self.owner, "_transport", None)
        return bool(transport and transport.subagents)

    def close(self) -> None:
        try:
            current = asyncio.current_task()
        except RuntimeError:
            current = None
        for child in self.children.values():
            child.cancelled = True
            if (
                child.active
                and child.cancellable
                and child.task is not None
                and child.task is not current
            ):
                child.task.cancel()
        if self.bus is not None:
            self.bus.unsubscribe("agent.lifecycle", self.handler)
            self.bus.unsubscribe("stream_chunk", self.handler)

    async def raw(
        self, root: str, target: str, update: dict[str, Any], *, record: bool = True
    ) -> None:
        if record:
            self.owner._registry.append(root, {"acp_target": target, "update": update})
        await self.owner._transport.send(
            {
                "jsonrpc": "2.0",
                "method": "session/update",
                "params": {"sessionId": target, "update": update},
            }
        )

    async def send(self, sid: str, update: Any) -> None:
        child = self.children[sid]
        if self.native:
            await self.raw(
                child.root, sid, update.model_dump(by_alias=True, exclude_none=True)
            )
        else:
            if isinstance(update, (ToolCallStart, ToolCallProgress)):
                update = update.model_copy(
                    update={"tool_call_id": sid + ":" + update.tool_call_id}
                )
                if isinstance(update, ToolCallStart):
                    update.title = child.agent + ": " + update.title
                await self.owner._send_update(child.root, update)

    async def state(self, sid: str, value: str, reason: str | None = None) -> None:
        child = self.children[sid]
        if self.native:
            state = {"state": value}
            if reason:
                state["stopReason"] = reason
            await self.raw(
                child.root,
                child.parent,
                {"sessionUpdate": "subagent_update", "sessionId": sid, "state": state},
            )

    async def on_event(self, kind: str, data: dict[str, Any]) -> None:
        sid = data.get("session_id") or data.get("conversation_id")
        if kind == "stream_chunk":
            child = self.children.get(sid)
            if (
                child
                and child.active
                and not data.get("is_reasoning")
                and data.get("message_type", "assistant") == "assistant"
                and isinstance(data.get("chunk"), str)
            ):
                child.streamed = True
                await self.send(
                    sid,
                    AgentMessageChunk(
                        session_update="agent_message_chunk",
                        content=text_block(data["chunk"]),
                    ),
                )
            return
        parent = data.get("parent_session_id")
        if not isinstance(sid, str) or sid == parent:
            return
        if parent in self.owner.sessions:
            root = parent
            parent_cwd = self.owner.sessions[parent].cwd
            parent_task = self.owner.sessions[parent].task
        elif parent in self.children:
            root = self.children[parent].root
            parent_cwd = self.children[parent].cwd
            parent_task = self.children[parent].task
        else:
            return
        cwd = Path(data.get("directory") or parent_cwd).resolve()
        if not cwd.is_relative_to(parent_cwd):
            return
        if data.get("state") == "running":
            existing = self.children.get(sid)
            if existing and existing.parent != parent:
                return
            task = asyncio.current_task()
            child = Child(
                parent,
                root,
                str(data.get("agent_id") or "child"),
                cwd,
                task=task,
                cancellable=task is not parent_task,
            )
            self.children[sid] = child
            if self.native:
                await self.raw(
                    root,
                    parent,
                    {
                        "sessionUpdate": "subagent_update",
                        "sessionId": sid,
                        "title": child.agent,
                        "capabilities": {"cancel": {}} if child.cancellable else {},
                        "state": {"state": "running"},
                    },
                )
                sent_id, received_id = uuid4().hex, uuid4().hex
                content = [{"type": "text", "text": str(data.get("prompt", ""))}]
                await self.raw(
                    root,
                    parent,
                    {
                        "sessionUpdate": "session_message",
                        "messageId": sent_id,
                        "senderSessionId": parent,
                        "recipientSessionId": sid,
                        "recipientMessageId": received_id,
                        "content": content,
                    },
                )
                await self.raw(
                    root,
                    sid,
                    {
                        "sessionUpdate": "session_message",
                        "messageId": received_id,
                        "senderSessionId": parent,
                        "recipientSessionId": sid,
                        "senderMessageId": sent_id,
                        "content": content,
                    },
                )
            else:
                await self.owner._send_update(
                    root,
                    ToolCallStart(
                        session_update="tool_call",
                        tool_call_id="child:" + sid,
                        title=child.agent,
                        kind="other",
                        status="in_progress",
                    ),
                )
        elif sid in self.children:
            child = self.children[sid]
            child.active = False
            self.owner._cancel_approvals(sid)
            await self.owner._events.end_turn(sid)
            text = data.get("text")
            if isinstance(text, str) and text and not child.streamed:
                await self.send(
                    sid,
                    AgentMessageChunk(
                        session_update="agent_message_chunk", content=text_block(text)
                    ),
                )
            reason = {
                "completed": "end_turn",
                "failed": "error",
                "cancelled": "cancelled",
            }.get(data.get("state"))
            if reason is None:
                return
            if not self.native:
                await self.owner._send_update(
                    root,
                    ToolCallProgress(
                        session_update="tool_call_update",
                        tool_call_id="child:" + sid,
                        status="completed" if reason == "end_turn" else "failed",
                        content=[
                            ContentToolCallContent(
                                type="content",
                                content=text_block(bounded(text or reason)),
                            )
                        ],
                    ),
                )
            await self.state(sid, "idle", reason)
            child.active = False
            child.task = None

    async def replay(self, root: str, record: dict[str, Any]) -> None:
        target, update = record.get("acp_target"), record.get("update")
        if not isinstance(target, str) or not isinstance(update, dict):
            raise ValueError("Invalid child replay record")
        known = self.replay_known.setdefault(root, {root})
        if target not in known:
            raise ValueError("Unknown child replay target")
        kind = update.get("sessionUpdate")
        if kind == "subagent_update":
            child_id = update.get("sessionId")
            if not isinstance(child_id, str) or child_id in {root, target}:
                raise ValueError("Invalid replayed child relationship")
            if (
                child_id in self.replay_parents
                and self.replay_parents[child_id] != target
            ):
                raise ValueError("Replayed child cannot change parent")
            self.replay_parents[child_id] = target
            known.add(child_id)
        elif kind not in {
            "session_message",
            "agent_message_chunk",
            "tool_call",
            "tool_call_update",
            "plan",
        }:
            raise ValueError("Unsupported child replay update")
        if not self.native:
            content = update.get("content")
            text = ""
            if isinstance(content, list):
                text = "\n".join(
                    c.get("text") or c.get("content", {}).get("text", "")
                    for c in content
                    if isinstance(c, dict)
                )
            elif isinstance(content, dict):
                text = content.get("text", "")
            elif kind == "subagent_update":
                text = json.dumps(
                    {
                        "child": update.get("title") or update.get("sessionId"),
                        "state": update.get("state"),
                    }
                )
            if text:
                await self.owner._connection.session_update(
                    session_id=root,
                    update=AgentMessageChunk(
                        session_update="agent_message_chunk", content=text_block(text)
                    ),
                )
            return
        if update.get("sessionUpdate") == "subagent_update":
            update = {**update, "capabilities": {}}
        await self.raw(root, target, update, record=False)

    async def finish_replay(self, root: str) -> None:
        if not self.native:
            self.replay_known.pop(root, None)
            return
        for sid in self.replay_known.pop(root, {root}) - {root}:
            child = self.children.get(sid)
            state = (
                {"state": "running"} if child and child.active else {"state": "unknown"}
            )
            await self.raw(
                root,
                self.replay_parents[sid],
                {
                    "sessionUpdate": "subagent_update",
                    "sessionId": sid,
                    "capabilities": {"cancel": {}}
                    if child and child.active and child.cancellable
                    else {},
                    "state": state,
                },
                record=False,
            )

    async def close_root(self, root: str) -> None:
        for sid, child in self.children.items():
            if child.root == root:
                child.cancelled = True
                self.owner._cancel_approvals(sid)
        tasks = {
            child.task
            for child in self.children.values()
            if child.root == root
            and child.active
            and child.cancellable
            and child.task is not None
            and child.task is not asyncio.current_task()
        }
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def cancel(self, sid: str) -> bool:
        child = self.children.get(sid)
        if not child or not self.native or not child.active or not child.cancellable:
            return False
        if child.task is asyncio.current_task():
            return False
        child.cancelled = True
        self.owner._cancel_approvals(sid)
        child.task.cancel()
        await asyncio.gather(child.task, return_exceptions=True)
        if child.active:
            child.active = False
            await self.state(sid, "idle", "cancelled")
        return True
