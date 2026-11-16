"""Display real process events without polling or consuming model cursors."""

from __future__ import annotations

import asyncio
import json
from typing import Any

from acp.helpers import text_block
from acp.schema import ContentToolCallContent, ToolCallProgress, ToolCallStart

from penguin.integrations.acp.events import bounded

__all__ = ["ProcessTracker"]


class ProcessTracker:
    def __init__(self, owner: Any) -> None:
        self.owner = owner
        self.states: dict[tuple[str, str], dict[str, Any]] = {}
        self.lock = asyncio.Lock()
        self.handler = self.on_event
        self.bus = getattr(owner.core, "event_bus", None)
        if self.bus is not None:
            for event in ("opencode_event", "action_result"):
                self.bus.subscribe(event, self.handler)

    def close(self) -> None:
        if self.bus is not None:
            for event in ("opencode_event", "action_result"):
                self.bus.unsubscribe(event, self.handler)

    async def on_event(self, kind: str, data: dict[str, Any]) -> None:
        if self.owner._closed:
            return
        if kind == "opencode_event":
            if data.get("type") not in {
                "tool.process.output",
                "notification.process.completed",
            }:
                return
            payload = data.get("properties", {})
            completed = data["type"] == "notification.process.completed"
        else:
            payload = data.get("result")
            if isinstance(payload, str):
                try:
                    payload = json.loads(payload)
                except ValueError:
                    return
            if not isinstance(payload, dict):
                return
            payload = {
                **payload,
                "session_id": data.get("session_id"),
                "agent_id": data.get("agent_id"),
            }
            completed = payload.get("process_status") == "exited"
        if isinstance(payload, dict):
            await self.update(payload, completed=completed)

    async def update(
        self, payload: dict[str, Any], *, completed: bool, force: bool = False
    ) -> None:
        async with self.lock:
            await self._update(payload, completed=completed, force=force)

    async def _update(
        self, payload: dict[str, Any], *, completed: bool, force: bool = False
    ) -> None:
        sid = payload.get("session_id") or payload.get("sessionID")
        pid = payload.get("process_id")
        if not isinstance(sid, str) or not isinstance(pid, str):
            return
        if (
            not force
            and not completed
            and payload.get("process_status") not in {"running", "draining", "exited"}
        ):
            return
        key = (sid, pid)
        current = self.states.get(key)
        child = self.owner._children.children.get(sid)
        root = child.root if child else (current or {}).get("root", sid)
        if current and current.get("completed") and not force:
            return
        if root not in self.owner.sessions:
            # The session was closed while this process ran. Record the
            # completion so it no longer counts as unresolved, but send no
            # update to a session the client has closed.
            if completed and current is not None:
                self.states[key] = {**current, "completed": True}
                self._notify_if_resolved(root)
            return
        if current is None:
            await self.owner._send_update(
                sid,
                ToolCallStart(
                    session_update="tool_call",
                    tool_call_id="process:" + pid,
                    title="Shell process",
                    kind="execute",
                    status="in_progress",
                    raw_input={"command": bounded(payload.get("command", ""))},
                    field_meta={
                        "penguin_process": {
                            "id": pid,
                            "session": sid,
                            "agent": payload.get("agent_id") or "agent",
                        }
                    },
                ),
            )
        output = payload.get("output_tail") or payload.get("output") or ""
        output = str(output)[-8192:]
        status = "in_progress"
        if completed:
            status = (
                "completed"
                if payload.get("returncode") == 0 and not payload.get("reader_error")
                else "failed"
            )
            reason = payload.get("completion_reason") or "outcome unknown"
            output += f"\nExit: {payload.get('returncode')}; {reason}"
            if payload.get("reader_error"):
                output += "\nOutput capture failed: " + str(payload["reader_error"])
        snapshot = {
            "completed": completed,
            "output": output,
            "agent": payload.get("agent_id") or (current or {}).get("agent") or "agent",
            "root": root,
        }
        if snapshot == current and not force:
            return
        self.states[key] = snapshot
        await self.owner._send_update(
            sid,
            ToolCallProgress(
                session_update="tool_call_update",
                tool_call_id="process:" + pid,
                status=status,
                content=[
                    ContentToolCallContent(
                        type="content", content=text_block(bounded(output))
                    )
                ],
            ),
        )

    def unresolved(self, root: str) -> bool:
        """Return whether a process started in ``root`` has not completed."""
        return any(
            sid == root and not state.get("completed")
            for (sid, _), state in self.states.items()
        )

    def _notify_if_resolved(self, root: str) -> None:
        callback = getattr(self.owner, "on_root_resolved", None)
        if callable(callback) and not self.unresolved(root):
            callback(root)

    def restore(self, root: str, update: Any) -> None:
        """Rebuild process state from one saved root-journal update."""
        meta = getattr(update, "field_meta", None) or {}
        self._restore(
            root,
            root,
            getattr(update, "tool_call_id", "") or "",
            getattr(update, "status", None),
            meta.get("penguin_process"),
        )

    def restore_raw(self, root: str, record: dict[str, Any]) -> None:
        """Rebuild process state from a saved native child envelope."""
        update = record.get("update")
        target = record.get("acp_target")
        if not isinstance(update, dict) or not isinstance(target, str):
            return
        meta = update.get("_meta") or {}
        self._restore(
            root,
            target,
            str(update.get("toolCallId") or ""),
            update.get("status"),
            meta.get("penguin_process") if isinstance(meta, dict) else None,
        )

    def _restore(
        self, root: str, target: str, call_id: str, status: Any, process: Any
    ) -> None:
        if isinstance(process, dict) and isinstance(process.get("id"), str):
            sid = process.get("session") or target
            self.states[(sid, process["id"])] = {
                "agent": process.get("agent") or "agent",
                "root": root,
            }
            self.owner._children.adopt(sid, root, process.get("agent"))
        # A root process is "process:<pid>"; a child's, outside native mode,
        # is "<child>:process:<pid>"; a native child envelope targets the child.
        sid, marker, pid = call_id.rpartition("process:")
        if not marker or not pid:
            return
        sid = sid.removesuffix(":") or target
        if status in {"completed", "failed"} and (sid, pid) in self.states:
            self.states[(sid, pid)]["completed"] = True

    async def refresh(self, root: str) -> None:
        manager = getattr(self.owner.core, "tool_manager", None)
        runtime = getattr(manager, "_process_runtime", None)
        for (sid, pid), state in list(self.states.items()):
            if state.get("root", sid) != root:
                continue
            if state.get("completed"):
                continue
            record = runtime._processes.get(pid) if runtime is not None else None
            if record is not None and record.owner == (sid, state["agent"]):
                payload = runtime.status(pid)
                with record.changed:
                    payload["output_tail"] = "".join(
                        event.text for event in record.events
                    )[-8192:]
                payload.update(session_id=sid, agent_id=state["agent"])
                await self.update(
                    payload,
                    completed=payload.get("process_status") == "exited",
                    force=True,
                )
            else:
                await self.update(
                    {
                        "session_id": sid,
                        "process_id": pid,
                        "completion_reason": (
                            "No owned handle after reconnect; outcome unknown"
                        ),
                    },
                    completed=True,
                    force=True,
                )
