"""Message/Part event model for OpenCode TUI compatibility.

This module provides dataclasses and adapters to convert Penguin's internal
streaming events to OpenCode-compatible message/part events for the TUI.
"""

from dataclasses import dataclass, field
from typing import Literal, Optional, Dict, Any, Tuple, Callable, Awaitable
from enum import Enum
import json
import os
import re
import time
import uuid


class PartType(Enum):
    """OpenCode-compatible part types."""

    TEXT = "text"
    REASONING = "reasoning"
    TOOL = "tool"
    STEP_START = "step-start"
    STEP_FINISH = "step-finish"
    PATCH = "patch"


@dataclass
class Part:
    """A part of a message (text, reasoning, tool, etc.)."""

    id: str
    message_id: str
    session_id: str
    type: PartType
    content: Dict[str, Any] = field(default_factory=dict)
    delta: Optional[str] = None  # For streaming text updates


@dataclass
class Message:
    """A message containing multiple parts."""

    id: str
    session_id: str
    role: Literal["user", "assistant", "system"]
    time_created: float
    time_completed: Optional[float] = None
    model_id: Optional[str] = None
    provider_id: Optional[str] = None
    agent_id: str = "default"
    parent_id: str = "root"
    path: Dict[str, str] = field(default_factory=dict)
    mode: str = "chat"
    cost: float = 0.0
    tokens: Dict[str, Any] = field(
        default_factory=lambda: {
            "input": 0,
            "output": 0,
            "reasoning": 0,
            "cache": {"read": 0, "write": 0},
        }
    )


@dataclass
class EventEnvelope:
    """OpenCode-compatible event wrapper."""

    type: str
    properties: Dict[str, Any]

    def to_sse(self) -> str:
        """Convert to Server-Sent Event format."""
        return f"data: {json.dumps({'type': self.type, 'properties': self.properties})}\n\n"


class PartEventAdapter:
    """Adapts Penguin StreamEvent to OpenCode-compatible Part events."""

    def __init__(
        self,
        event_bus: Any,
        persist_callback: Optional[
            Callable[[str, Dict[str, Any]], Optional[Awaitable[None]]]
        ] = None,
        emit_session_status_events: bool = True,
    ):
        self.event_bus = event_bus
        self.persist_callback = persist_callback
        self._emit_session_status_events = bool(emit_session_status_events)
        self._active_messages: Dict[str, Message] = {}
        self._active_parts: Dict[str, Part] = {}
        self._session_id: Optional[str] = None
        self._current_message_id: Optional[str] = None
        self._current_reasoning_part_id: Optional[str] = None
        self._current_text_part_id: Optional[str] = None
        self._stream_active: bool = False
        self._active_tool_parts: set[str] = set()
        self._active_tool_counts_by_message: Dict[str, int] = {}
        self._session_status: str = "idle"
        self._default_directory: Optional[str] = None
        self._last_id_ts = 0
        self._last_id_inc = 0
        self._action_active: Optional[str] = None
        self._action_buffer = ""
        try:
            from penguin.utils.parser import ActionType

            self._action_tags = [
                action_type.value.lower() for action_type in ActionType
            ]
        except Exception:
            self._action_tags = []
        self._filter_re = re.compile(r"</?finish_response\b[^>]*>?", re.IGNORECASE)

    def set_session(self, session_id: str):
        """Set current session ID for all subsequent events."""
        self._session_id = session_id

    def set_directory(self, directory: Optional[str]) -> None:
        """Set default directory for path metadata when context is absent."""
        if isinstance(directory, str) and directory.strip():
            self._default_directory = directory.strip()
            return
        self._default_directory = None

    def _path(self) -> Dict[str, str]:
        try:
            from penguin.system.execution_context import get_current_execution_context

            context = get_current_execution_context()
            if context and context.directory:
                return {"cwd": context.directory, "root": context.directory}
        except Exception:
            pass
        cwd = self._default_directory or os.getenv("PENGUIN_CWD") or os.getcwd()
        return {"cwd": cwd, "root": cwd}

    def _mode(self) -> str:
        """Resolve OpenCode message mode from execution context."""
        try:
            from penguin.system.execution_context import get_current_execution_context

            context = get_current_execution_context()
            raw_mode = getattr(context, "agent_mode", None) if context else None
            if isinstance(raw_mode, str):
                normalized = raw_mode.strip().lower()
                if normalized in {"plan", "build"}:
                    return normalized
        except Exception:
            pass
        return "chat"

    def _next_id(self, prefix: str) -> str:
        ts = int(time.time() * 1000)
        if ts == self._last_id_ts:
            self._last_id_inc += 1
        if ts != self._last_id_ts:
            self._last_id_ts = ts
            self._last_id_inc = 0
        stamp = str(ts).rjust(13, "0")
        return f"{prefix}_{stamp}_{self._last_id_inc:02d}"

    def _strip_action_tags_keep_whitespace(self, text: str) -> str:
        if not text:
            return text

        if not self._action_tags:
            return text

        combined = f"{self._action_buffer}{text}"
        self._action_buffer = ""
        lowered = combined.lower()
        output: list[str] = []
        index = 0

        def _is_literal_tag(open_index: int, end_index: Optional[int] = None) -> bool:
            """Return True when a tag-looking token is escaped/literal markdown text."""
            if open_index > 0:
                prev_char = combined[open_index - 1]
                if prev_char in {"`", "\\"}:
                    return True
            if end_index is not None and end_index + 1 < len(combined):
                next_char = combined[end_index + 1]
                if next_char == "`":
                    return True
            return False

        while index < len(combined):
            if self._action_active:
                close_token = f"</{self._action_active}>"
                close_index = lowered.find(close_token, index)
                if close_index == -1:
                    tail_len = max(len(close_token) - 1, 0)
                    if tail_len:
                        self._action_buffer = combined[-tail_len:]
                    return "".join(output)
                index = close_index + len(close_token)
                self._action_active = None
                continue

            open_index = combined.find("<", index)
            if open_index == -1:
                output.append(combined[index:])
                return "".join(output)

            output.append(combined[index:open_index])
            end_index = combined.find(">", open_index + 1)
            if end_index == -1:
                if _is_literal_tag(open_index):
                    output.append(combined[open_index:])
                    return "".join(output)
                fragment = lowered[open_index + 1 :]
                if fragment.startswith("/"):
                    fragment = fragment[1:]
                if any(tag.startswith(fragment) for tag in self._action_tags):
                    self._action_buffer = combined[open_index:]
                    return "".join(output)
                output.append(combined[open_index:])
                return "".join(output)

            tag_token = lowered[open_index + 1 : end_index].strip()
            is_close = tag_token.startswith("/")
            tag_name = tag_token[1:].strip() if is_close else tag_token
            if tag_name not in self._action_tags:
                output.append(combined[open_index : end_index + 1])
                index = end_index + 1
                continue

            if _is_literal_tag(open_index, end_index):
                output.append(combined[open_index : end_index + 1])
                index = end_index + 1
                continue

            if is_close:
                index = end_index + 1
                continue

            close_token = f"</{tag_name}>"
            close_index = lowered.find(close_token, end_index + 1)
            if close_index == -1:
                self._action_active = tag_name
                tail_len = max(len(close_token) - 1, 0)
                if tail_len:
                    self._action_buffer = combined[-tail_len:]
                return "".join(output)

            index = close_index + len(close_token)

        return "".join(output)

    def _strip_internal(self, text: str, trim: bool = True) -> str:
        cleaned = self._strip_action_tags_keep_whitespace(text)
        cleaned = self._filter_re.sub("", cleaned)
        return cleaned.strip() if trim else cleaned

    async def _emit_session_status(self, status_type: str):
        await self._emit(
            "session.status",
            {
                "sessionID": self._session_id or "unknown",
                "status": {"type": status_type},
            },
        )

    async def _sync_session_status(self) -> None:
        """Emit session status only when state changes."""
        next_status = (
            "busy" if self._stream_active or bool(self._active_tool_parts) else "idle"
        )
        if next_status == self._session_status:
            return
        self._session_status = next_status
        if not self._emit_session_status_events:
            return
        await self._emit_session_status(next_status)

    async def _ensure_tool_message(
        self,
        message_id: Optional[str] = None,
        agent_id: str = "default",
    ) -> str:
        """Ensure a target assistant message exists for tool parts."""
        existing_message_id = message_id or self._current_message_id
        if existing_message_id and existing_message_id in self._active_messages:
            self._current_message_id = existing_message_id
            return existing_message_id

        created_message_id = existing_message_id or self._next_id("msg")
        message = Message(
            id=created_message_id,
            session_id=self._session_id or "unknown",
            role="assistant",
            time_created=time.time(),
            agent_id=agent_id,
            parent_id="root",
            path=self._path(),
            mode=self._mode(),
        )
        self._active_messages[created_message_id] = message
        self._current_message_id = created_message_id
        await self._emit("message.updated", self._message_to_dict(message))
        return created_message_id

    async def on_stream_start(
        self,
        agent_id: str = "default",
        model_id: Optional[str] = None,
        provider_id: Optional[str] = None,
    ) -> Tuple[str, str]:
        """Called when streaming starts - creates Message and initial TextPart.

        Returns:
            Tuple of (message_id, part_id)
        """
        self._action_active = None
        self._action_buffer = ""
        message_id = self._next_id("msg")
        reasoning_id = self._next_id("part")
        part_id = self._next_id("part")

        message = Message(
            id=message_id,
            session_id=self._session_id or "unknown",
            role="assistant",
            time_created=time.time(),
            model_id=model_id,
            provider_id=provider_id,
            agent_id=agent_id,
            parent_id="root",
            path=self._path(),
            mode=self._mode(),
        )
        self._active_messages[message_id] = message
        self._current_message_id = message_id
        self._current_text_part_id = part_id
        self._current_reasoning_part_id = reasoning_id

        reasoning_part = Part(
            id=reasoning_id,
            message_id=message_id,
            session_id=self._session_id or "unknown",
            type=PartType.REASONING,
            content={"text": ""},
        )
        self._active_parts[reasoning_id] = reasoning_part

        text_part = Part(
            id=part_id,
            message_id=message_id,
            session_id=self._session_id or "unknown",
            type=PartType.TEXT,
            content={"text": ""},
        )
        self._active_parts[part_id] = text_part

        self._stream_active = True
        await self._sync_session_status()
        # Emit message.updated
        await self._emit("message.updated", self._message_to_dict(message))
        await self._emit(
            "message.part.updated", {"part": self._part_to_dict(reasoning_part)}
        )
        return message_id, part_id

    async def on_stream_chunk(
        self, message_id: str, part_id: str, chunk: str, message_type: str = "assistant"
    ):
        """Called for each chunk - emits message.part.updated with delta."""
        current_id = (
            self._current_text_part_id
            if message_type != "reasoning"
            else self._current_reasoning_part_id
        )
        part = self._active_parts.get(current_id or part_id)
        if not part:
            return

        chunk = self._strip_internal(chunk, trim=False)
        # Handle reasoning content separately
        if message_type == "reasoning":
            if not self._current_reasoning_part_id:
                part_id = self._next_id("part")
                part = Part(
                    id=part_id,
                    message_id=message_id,
                    session_id=self._session_id or "unknown",
                    type=PartType.REASONING,
                    content={"text": ""},
                )
                self._active_parts[part_id] = part
                self._current_reasoning_part_id = part_id
                await self._emit(
                    "message.part.updated", {"part": self._part_to_dict(part)}
                )
            part = self._active_parts.get(self._current_reasoning_part_id)
            if not part:
                return

        part.content["text"] = f"{part.content.get('text', '')}{chunk}"
        part.delta = chunk

        # Emit with delta for streaming
        await self._emit(
            "message.part.updated", {"part": self._part_to_dict(part), "delta": chunk}
        )

        part.delta = None  # Reset after emit

    async def on_stream_end(self, message_id: str, part_id: str):
        """Called when streaming ends - finalize message and part."""
        message = self._active_messages.get(message_id)

        if message:
            message.time_completed = time.time()
            await self._emit("message.updated", self._message_to_dict(message))

        self._stream_active = False

        # Clean up
        self._active_parts.pop(part_id, None)
        if self._current_reasoning_part_id:
            self._active_parts.pop(self._current_reasoning_part_id, None)
        # Keep the current message so post-stream tool events can attach to
        # the same assistant response.
        self._current_message_id = message_id
        self._current_reasoning_part_id = None
        self._current_text_part_id = None
        self._action_active = None
        self._action_buffer = ""
        await self._sync_session_status()

    async def on_tool_start(
        self,
        tool_name: str,
        tool_input: Dict[str, Any],
        tool_call_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        message_id: Optional[str] = None,
        agent_id: str = "default",
    ) -> str:
        """Called when a tool starts executing.

        Returns:
            part_id for tracking this tool execution
        """
        msg_id = await self._ensure_tool_message(
            message_id=message_id,
            agent_id=agent_id,
        )
        self._current_message_id = msg_id
        target_message_id = msg_id or "unknown"
        part_id = self._next_id("part")
        call_id = tool_call_id or self._next_id("call")

        start_time = int(time.time() * 1000)
        state: Dict[str, Any] = {
            "status": "running",
            "input": tool_input or {},
            "time": {"start": start_time},
        }
        if metadata:
            state["metadata"] = metadata

        tool_part = Part(
            id=part_id,
            message_id=target_message_id,
            session_id=self._session_id or "unknown",
            type=PartType.TOOL,
            content={
                "callID": call_id,
                "tool": tool_name,
                "state": state,
            },
        )
        self._active_parts[part_id] = tool_part
        self._active_tool_parts.add(part_id)
        self._active_tool_counts_by_message[target_message_id] = (
            self._active_tool_counts_by_message.get(target_message_id, 0) + 1
        )
        await self._sync_session_status()

        await self._emit(
            "message.part.updated", {"part": self._part_to_dict(tool_part)}
        )
        return part_id

    async def on_tool_end(
        self,
        part_id: str,
        output: Any,
        error: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ):
        """Called when a tool finishes executing."""
        part = self._active_parts.get(part_id)
        if not part:
            return

        now = int(time.time() * 1000)
        existing_state = part.content.get("state")
        input_data: Dict[str, Any] = {}
        start_time = now
        existing_meta: Dict[str, Any] = {}
        if isinstance(existing_state, dict):
            existing_input = existing_state.get("input")
            if isinstance(existing_input, dict):
                input_data = existing_input
            time_data = existing_state.get("time")
            if isinstance(time_data, dict) and isinstance(time_data.get("start"), int):
                start_time = time_data["start"]
            meta_data = existing_state.get("metadata")
            if isinstance(meta_data, dict):
                existing_meta = meta_data

        merged_meta = dict(existing_meta)
        if metadata:
            merged_meta.update(metadata)

        new_state: Dict[str, Any] = {
            "status": "error" if error else "completed",
            "input": input_data,
            "time": {"start": start_time, "end": now},
        }
        if error:
            new_state["error"] = error
        else:
            new_state["output"] = output
        if merged_meta:
            new_state["metadata"] = merged_meta

        part.content["state"] = new_state

        await self._emit("message.part.updated", {"part": self._part_to_dict(part)})

        message_id = part.message_id
        self._active_tool_parts.discard(part_id)
        remaining_for_message = max(
            self._active_tool_counts_by_message.get(message_id, 1) - 1,
            0,
        )
        if remaining_for_message == 0:
            self._active_tool_counts_by_message.pop(message_id, None)
            if not self._stream_active:
                message = self._active_messages.get(message_id)
                if message and message.time_completed is None:
                    message.time_completed = time.time()
                    await self._emit("message.updated", self._message_to_dict(message))
        else:
            self._active_tool_counts_by_message[message_id] = remaining_for_message

        self._active_parts.pop(part_id, None)
        await self._sync_session_status()

    async def abort(self, reason: str = "Tool execution was interrupted") -> bool:
        """Abort active stream/tool parts and force session idle state."""
        changed = False

        message_id = self._current_message_id
        text_part_id = self._current_text_part_id
        if self._stream_active:
            if isinstance(message_id, str) and isinstance(text_part_id, str):
                await self.on_stream_end(message_id, text_part_id)
                changed = True
            else:
                if isinstance(message_id, str):
                    message = self._active_messages.get(message_id)
                    if message and message.time_completed is None:
                        message.time_completed = time.time()
                        await self._emit(
                            "message.updated", self._message_to_dict(message)
                        )
                        changed = True
                self._stream_active = False
                self._current_reasoning_part_id = None
                self._current_text_part_id = None

        for tool_part_id in list(self._active_tool_parts):
            part = self._active_parts.get(tool_part_id)
            if part is None:
                self._active_tool_parts.discard(tool_part_id)
                continue
            await self.on_tool_end(
                tool_part_id,
                "",
                error=reason,
                metadata={"aborted": True},
            )
            changed = True

        self._action_active = None
        self._action_buffer = ""
        await self._sync_session_status()
        return changed

    async def on_user_message(self, content: str) -> str:
        """Called when user sends a message."""
        message_id = self._next_id("msg")

        message = Message(
            id=message_id,
            session_id=self._session_id or "unknown",
            role="user",
            time_created=time.time(),
            time_completed=time.time(),  # User messages are complete immediately
            agent_id="default",
            parent_id="root",
            path=self._path(),
            mode=self._mode(),
        )

        # Create text part for user message
        part_id = self._next_id("part")
        text_part = Part(
            id=part_id,
            message_id=message_id,
            session_id=self._session_id or "unknown",
            type=PartType.TEXT,
            content={"text": self._strip_internal(content)},
        )

        await self._emit("message.updated", self._message_to_dict(message))
        await self._emit(
            "message.part.updated", {"part": self._part_to_dict(text_part)}
        )

        return message_id

    async def update_assistant_usage(
        self,
        message_id: str,
        *,
        tokens: Optional[Dict[str, Any]] = None,
        cost: Optional[float] = None,
    ) -> None:
        """Update assistant message usage/cost metadata and re-emit message.updated."""
        message = self._active_messages.get(message_id)
        if message is None:
            message = Message(
                id=message_id,
                session_id=self._session_id or "unknown",
                role="assistant",
                time_created=time.time(),
                time_completed=time.time(),
                agent_id="default",
                parent_id="root",
                path=self._path(),
                mode=self._mode(),
            )
            self._active_messages[message_id] = message

        if message.role != "assistant":
            return

        if isinstance(tokens, dict):
            raw_cache = tokens.get("cache")
            cache: Dict[str, Any] = raw_cache if isinstance(raw_cache, dict) else {}
            message.tokens = {
                "input": max(int(tokens.get("input", 0) or 0), 0),
                "output": max(int(tokens.get("output", 0) or 0), 0),
                "reasoning": max(int(tokens.get("reasoning", 0) or 0), 0),
                "cache": {
                    "read": max(int(cache.get("read", 0) or 0), 0),
                    "write": max(int(cache.get("write", 0) or 0), 0),
                },
            }

        if isinstance(cost, (int, float)):
            message.cost = max(float(cost), 0.0)

        await self._emit("message.updated", self._message_to_dict(message))

    def _message_to_dict(self, msg: Message) -> Dict[str, Any]:
        """Convert Message to OpenCode-compatible dict."""
        base = {
            "id": msg.id,
            "sessionID": msg.session_id,
            "role": msg.role,
            "time": {
                "created": int(msg.time_created * 1000),
                "completed": int(msg.time_completed * 1000)
                if msg.time_completed
                else None,
            },
        }
        if msg.role == "assistant":
            return {
                **base,
                "parentID": msg.parent_id,
                "modelID": msg.model_id,
                "providerID": msg.provider_id,
                "mode": msg.mode,
                "agent": msg.agent_id,
                "path": msg.path or self._path(),
                "cost": msg.cost,
                "tokens": msg.tokens,
            }
        if msg.role == "user":
            return {
                **base,
                "agent": msg.agent_id,
                "model": {
                    "providerID": msg.provider_id or "penguin",
                    "modelID": msg.model_id or "penguin-default",
                },
            }
        return base

    def _part_to_dict(self, part: Part) -> Dict[str, Any]:
        """Convert Part to OpenCode-compatible dict."""
        result = {
            "id": part.id,
            "messageID": part.message_id,
            "sessionID": part.session_id,
            "type": part.type.value,
        }
        # Merge content fields
        result.update(part.content)
        return result

    async def _emit(self, event_type: str, properties: Dict[str, Any]):
        """Emit through EventBus with OpenCode envelope format."""
        if self.persist_callback is not None:
            try:
                result = self.persist_callback(event_type, properties)
                if result is not None:
                    await result
            except Exception:
                pass
        await self.event_bus.emit(
            "opencode_event", {"type": event_type, "properties": properties}
        )


__all__ = ["PartType", "Part", "Message", "EventEnvelope", "PartEventAdapter"]
