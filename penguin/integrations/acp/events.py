"""Convert scoped runtime events into bounded ACP progress updates."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

from acp.helpers import text_block
from acp.schema import (
    AgentPlanUpdate,
    ContentToolCallContent,
    PlanEntry,
    ToolCallLocation,
    ToolCallProgress,
    ToolCallStart,
)

from penguin.core_runtime.action_mapping import (
    extract_tool_file_path,
    map_action_result_metadata,
    map_action_to_tool,
    normalize_todo_items,
)

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

__all__ = ["EventBridge"]

MAX_CONTENT = 16_384


def bounded(value: Any) -> str:
    """Bound display content; never stream arbitrary event metadata wholesale."""
    text = value if isinstance(value, str) else json.dumps(value, default=str)
    if len(text) > MAX_CONTENT:
        return text[:MAX_CONTENT] + "\n[ACP display truncated]"
    return text


def _contents(value: Any) -> list[ContentToolCallContent]:
    return [ContentToolCallContent(type="content", content=text_block(bounded(value)))]


class EventBridge:
    """Subscribe only to concrete UI events and isolate them by session ID."""

    def __init__(
        self,
        bus: Any,
        session_cwd: Callable[[str], Path | None],
        send: Callable[[str, Any], Awaitable[None]],
    ) -> None:
        self.bus = bus
        self.session_cwd = session_cwd
        self.send = send
        self.calls: dict[
            tuple[str, str], tuple[str, dict[str, Any], dict[str, Any]]
        ] = {}
        self.finished: set[tuple[str, str]] = set()
        self.lock = asyncio.Lock()
        self.handler = self.on_event
        self.event_types = ("action", "action_result", "todo.updated")
        if bus is not None:
            for event in self.event_types:
                bus.subscribe(event, self.handler)

    def close(self) -> None:
        """Detach subscriptions owned by this adapter."""
        if self.bus is not None:
            for event in self.event_types:
                self.bus.unsubscribe(event, self.handler)

    def _locations(
        self, cwd: Path, tool_input: dict[str, Any]
    ) -> list[ToolCallLocation]:
        raw = extract_tool_file_path(tool_input)
        if not raw or raw.startswith("("):
            return []
        try:
            path = Path(raw)
            if not path.is_absolute():
                path = cwd / path
            path = path.resolve()
        except (OSError, ValueError):
            return []
        return [ToolCallLocation(path=str(path))] if path.is_relative_to(cwd) else []

    async def on_event(self, event_type: str, data: dict[str, Any]) -> None:
        """Emit starts/results/plans in order, never borrowing another session."""
        sid = (
            data.get("session_id")
            or data.get("conversation_id")
            or data.get("sessionID")
        )
        if not isinstance(sid, str) or (cwd := self.session_cwd(sid)) is None:
            return
        async with self.lock:
            if event_type == "todo.updated":
                entries = []
                for todo in normalize_todo_items(data.get("todos"))[:100]:
                    if todo["status"] == "cancelled":
                        continue
                    entries.append(
                        PlanEntry(
                            content=bounded(todo["content"]),
                            priority=todo["priority"],
                            status=todo["status"],
                        )
                    )
                await self.send(
                    sid, AgentPlanUpdate(session_update="plan", entries=entries)
                )
                return
            call_id = data.get("id") or data.get("call_id") or data.get("callID")
            if not isinstance(call_id, str) or not call_id:
                return
            key = (sid, call_id)
            if key in self.finished:
                return
            if key not in self.calls:
                name = str(data.get("action") or data.get("type") or "tool")
                params = data.get("params", {})
                if isinstance(params, str):
                    try:
                        params = json.loads(params)
                    except ValueError:
                        pass
                mapped, tool_input, metadata = map_action_to_tool(name, params)
                self.calls[key] = (name, tool_input, metadata)
                kind = {
                    "bash": "execute",
                    "write": "edit",
                    "grep": "search",
                    "glob": "search",
                    "list": "read",
                }.get(mapped, mapped)
                if kind not in {
                    "read",
                    "edit",
                    "delete",
                    "move",
                    "search",
                    "execute",
                    "think",
                    "fetch",
                    "switch_mode",
                }:
                    kind = "other"
                await self.send(
                    sid,
                    ToolCallStart(
                        session_update="tool_call",
                        tool_call_id=call_id,
                        title=bounded(name),
                        kind=kind,
                        status="pending",
                        locations=self._locations(cwd, tool_input),
                    ),
                )
            if event_type != "action_result":
                return
            name, tool_input, metadata = self.calls.pop(key)
            failed = data.get("status") in {
                "error",
                "failed",
                "cancelled",
                "denied",
                "interrupted",
            }
            result = data.get("result", "")
            metadata = map_action_result_metadata(
                name,
                result,
                existing=metadata,
                tool_input=tool_input,
                status="error" if failed else "completed",
            )
            content = _contents(result)
            diff = metadata.get("diff")
            if isinstance(diff, str) and diff and not failed:
                content += _contents("```diff\n" + diff + "\n```")
            await self.send(
                sid,
                ToolCallProgress(
                    session_update="tool_call_update",
                    tool_call_id=call_id,
                    status="failed" if failed else "completed",
                    content=content,
                ),
            )
            self.finished.add(key)

    async def end_turn(self, sid: str) -> None:
        """Close interrupted or missing terminal events before prompt completion."""
        async with self.lock:
            for key in list(self.calls):
                if key[0] != sid:
                    continue
                await self.send(
                    sid,
                    ToolCallProgress(
                        session_update="tool_call_update",
                        tool_call_id=key[1],
                        status="failed",
                        content=_contents(
                            "Tool ended without a result (interrupted or unavailable)."
                        ),
                    ),
                )
                self.calls.pop(key)
            self.finished = {key for key in self.finished if key[0] != sid}
