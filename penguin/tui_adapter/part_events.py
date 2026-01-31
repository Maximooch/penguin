"""Message/Part event model for OpenCode TUI compatibility.

This module provides dataclasses and adapters to convert Penguin's internal
streaming events to OpenCode-compatible message/part events for the TUI.
"""

from dataclasses import dataclass, field
from typing import Literal, Optional, Dict, Any, Tuple, Callable
from enum import Enum
import time
import uuid
import json


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
    mode: str = "chat"
    cost: float = 0.0
    tokens: Dict[str, int] = field(default_factory=lambda: {
        "input": 0, "output": 0, "reasoning": 0, "cache": {"read": 0, "write": 0}
    })


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

    def __init__(self, event_bus: Any):
        self.event_bus = event_bus
        self._active_messages: Dict[str, Message] = {}
        self._active_parts: Dict[str, Part] = {}
        self._session_id: Optional[str] = None
        self._current_message_id: Optional[str] = None

    def set_session(self, session_id: str):
        """Set current session ID for all subsequent events."""
        self._session_id = session_id

    async def on_stream_start(
        self, 
        agent_id: str = "default",
        model_id: Optional[str] = None,
        provider_id: Optional[str] = None
    ) -> Tuple[str, str]:
        """Called when streaming starts - creates Message and initial TextPart.

        Returns:
            Tuple of (message_id, part_id)
        """
        message_id = f"msg_{uuid.uuid4().hex[:12]}"
        part_id = f"part_{uuid.uuid4().hex[:12]}"

        message = Message(
            id=message_id,
            session_id=self._session_id or "unknown",
            role="assistant",
            time_created=time.time(),
            model_id=model_id,
            provider_id=provider_id
        )
        self._active_messages[message_id] = message
        self._current_message_id = message_id

        text_part = Part(
            id=part_id,
            message_id=message_id,
            session_id=self._session_id or "unknown",
            type=PartType.TEXT,
            content={"text": ""}
        )
        self._active_parts[part_id] = text_part

        # Emit message.updated
        await self._emit("message.updated", self._message_to_dict(message))
        return message_id, part_id

    async def on_stream_chunk(
        self, 
        message_id: str, 
        part_id: str, 
        chunk: str, 
        message_type: str = "assistant"
    ):
        """Called for each chunk - emits message.part.updated with delta."""
        part = self._active_parts.get(part_id)
        if not part:
            return

        # Handle reasoning content separately
        if message_type == "reasoning":
            if part.type != PartType.REASONING:
                # Create new reasoning part
                part_id = f"part_{uuid.uuid4().hex[:12]}"
                part = Part(
                    id=part_id,
                    message_id=message_id,
                    session_id=self._session_id or "unknown",
                    type=PartType.REASONING,
                    content={"text": ""}
                )
                self._active_parts[part_id] = part
                # Emit initial part creation
                await self._emit("message.part.updated", {
                    "part": self._part_to_dict(part)
                })

        part.content["text"] = part.content.get("text", "") + chunk
        part.delta = chunk

        # Emit with delta for streaming
        await self._emit("message.part.updated", {
            "part": self._part_to_dict(part),
            "delta": chunk
        })

        part.delta = None  # Reset after emit

    async def on_stream_end(self, message_id: str, part_id: str):
        """Called when streaming ends - finalize message and part."""
        message = self._active_messages.get(message_id)
        part = self._active_parts.get(part_id)

        if message:
            message.time_completed = time.time()
            await self._emit("message.updated", self._message_to_dict(message))

        # Clean up
        self._active_parts.pop(part_id, None)
        self._current_message_id = None

    async def on_tool_start(
        self, 
        tool_name: str, 
        tool_input: Dict[str, Any],
        tool_call_id: Optional[str] = None
    ) -> str:
        """Called when a tool starts executing.

        Returns:
            part_id for tracking this tool execution
        """
        if not self._current_message_id:
            # No active message, create one
            msg_id, _ = await self.on_stream_start()

        message_id = self._current_message_id
        part_id = f"part_{uuid.uuid4().hex[:12]}"
        call_id = tool_call_id or f"call_{uuid.uuid4().hex[:12]}"

        tool_part = Part(
            id=part_id,
            message_id=message_id,
            session_id=self._session_id or "unknown",
            type=PartType.TOOL,
            content={
                "callID": call_id,
                "tool": tool_name,
                "input": tool_input,
                "state": "running",
                "output": None
            }
        )
        self._active_parts[part_id] = tool_part

        await self._emit("message.part.updated", {"part": self._part_to_dict(tool_part)})
        return part_id

    async def on_tool_end(
        self, 
        part_id: str, 
        output: Any, 
        error: Optional[str] = None
    ):
        """Called when a tool finishes executing."""
        part = self._active_parts.get(part_id)
        if not part:
            return

        part.content["state"] = "error" if error else "completed"
        part.content["output"] = output
        if error:
            part.content["error"] = error

        await self._emit("message.part.updated", {"part": self._part_to_dict(part)})

        # Keep tool part in active parts for potential updates, 
        # but could clean up here if desired

    async def on_user_message(self, content: str) -> str:
        """Called when user sends a message."""
        message_id = f"msg_{uuid.uuid4().hex[:12]}"

        message = Message(
            id=message_id,
            session_id=self._session_id or "unknown",
            role="user",
            time_created=time.time(),
            time_completed=time.time()  # User messages are complete immediately
        )

        # Create text part for user message
        part_id = f"part_{uuid.uuid4().hex[:12]}"
        text_part = Part(
            id=part_id,
            message_id=message_id,
            session_id=self._session_id or "unknown",
            type=PartType.TEXT,
            content={"text": content}
        )

        await self._emit("message.updated", self._message_to_dict(message))
        await self._emit("message.part.updated", {"part": self._part_to_dict(text_part)})

        return message_id

    def _message_to_dict(self, msg: Message) -> Dict[str, Any]:
        """Convert Message to OpenCode-compatible dict."""
        return {
            "id": msg.id,
            "sessionID": msg.session_id,
            "role": msg.role,
            "time": {
                "created": int(msg.time_created * 1000),
                "completed": int(msg.time_completed * 1000) if msg.time_completed else None
            },
            "modelID": msg.model_id,
            "providerID": msg.provider_id,
            "mode": msg.mode,
            "cost": msg.cost,
            "tokens": msg.tokens
        }

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
        await self.event_bus.emit("opencode_event", {
            "type": event_type,
            "properties": properties
        })


__all__ = [
    "PartType",
    "Part", 
    "Message",
    "EventEnvelope",
    "PartEventAdapter"
]