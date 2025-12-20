"""Stream handling for LLM responses.

This module provides:
- StreamHandler: Abstract base class for processing raw provider streams
- DefaultStreamHandler: Basic implementation for OpenAI-style streams
- StreamingStateManager: State machine for managing streaming lifecycle

The StreamingStateManager is the main class for managing streaming state,
coalescing chunks, tracking reasoning content, and generating events for UI.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, AsyncIterator, Callable, Dict, List, Optional, Tuple
import time
import uuid


class StreamState(Enum):
    """States for the streaming state machine."""
    INACTIVE = "inactive"
    ACTIVE = "active"
    FINALIZING = "finalizing"


@dataclass
class StreamEvent:
    """Represents an event to be emitted during streaming."""
    event_type: str  # "stream_chunk", "stream_start", "stream_end"
    data: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        return {"event_type": self.event_type, "data": self.data}


@dataclass
class StreamingConfig:
    """Configuration for streaming behavior."""
    # Coalescing thresholds
    min_emit_interval: float = 0.04  # ~25 fps
    min_emit_chars: int = 12  # minimum chars before emit

    # Empty response handling
    max_empty_chunks_before_warning: int = 3

    # Placeholder for empty responses (WALLET_GUARD)
    empty_response_placeholder: str = "[Empty response from model]"


@dataclass
class FinalizedMessage:
    """Result of finalizing a streaming message."""
    content: str
    reasoning: str
    role: str
    metadata: Dict[str, Any]
    was_empty: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "content": self.content,
            "reasoning": self.reasoning,
            "role": self.role,
            "metadata": self.metadata,
            "was_empty": self.was_empty,
        }


class StreamingStateManager:
    """Manages streaming state, coalescing, and event generation.

    This class is a state machine that handles:
    - State transitions: INACTIVE → ACTIVE → FINALIZING → INACTIVE
    - Content accumulation (assistant and reasoning separately)
    - Chunk coalescing to avoid per-token UI updates
    - Empty response handling (WALLET_GUARD)
    - Event generation for UI updates

    Usage:
        manager = StreamingStateManager()

        # Process chunks
        for chunk in provider_stream:
            events = manager.handle_chunk(chunk, message_type="assistant")
            for event in events:
                await emit_ui_event(event.event_type, event.data)

        # Finalize
        message, events = manager.finalize()
        for event in events:
            await emit_ui_event(event.event_type, event.data)

        # Use the finalized message
        conversation.add_message(message.role, message.content, metadata=message.metadata)
    """

    def __init__(self, config: Optional[StreamingConfig] = None):
        self.config = config or StreamingConfig()
        self._reset_state()

    def _reset_state(self) -> None:
        """Reset all state to initial values."""
        self._state = StreamState.INACTIVE
        self._stream_id: Optional[str] = None
        self._content = ""
        self._reasoning_content = ""
        self._message_type: Optional[str] = None
        self._role = "assistant"
        self._metadata: Dict[str, Any] = {}
        self._started_at: Optional[datetime] = None
        self._last_update: Optional[datetime] = None
        self._empty_response_count = 0
        self._error: Optional[str] = None

        # Coalescing state
        self._emit_buffer = ""
        self._last_emit_ts = 0.0

    # --- Properties ---

    @property
    def state(self) -> StreamState:
        """Current state of the streaming state machine."""
        return self._state

    @property
    def is_active(self) -> bool:
        """Whether streaming is currently active."""
        return self._state == StreamState.ACTIVE

    @property
    def content(self) -> str:
        """Accumulated assistant content."""
        return self._content

    @property
    def reasoning_content(self) -> str:
        """Accumulated reasoning content."""
        return self._reasoning_content

    @property
    def stream_id(self) -> Optional[str]:
        """Unique ID for the current stream."""
        return self._stream_id

    @property
    def error(self) -> Optional[str]:
        """Error message if any."""
        return self._error

    @property
    def empty_response_count(self) -> int:
        """Number of consecutive empty chunks received."""
        return self._empty_response_count

    # --- Core Methods ---

    def handle_chunk(
        self,
        chunk: str,
        message_type: Optional[str] = None,
        role: str = "assistant",
    ) -> List[StreamEvent]:
        """Process a streaming chunk and return events to emit.

        Args:
            chunk: The content chunk to process
            message_type: Type of message - "assistant", "reasoning", etc.
            role: The role of the message (default: "assistant")

        Returns:
            List of StreamEvent objects to emit
        """
        events: List[StreamEvent] = []
        message_type = message_type or "assistant"
        now = datetime.now()

        # Handle empty/whitespace chunks
        if not chunk:
            events.extend(self._handle_empty_chunk(message_type, role, now))
            return events

        # Reset empty counter on actual content
        self._empty_response_count = 0

        # Activate streaming if not already active
        if self._state == StreamState.INACTIVE:
            self._activate(message_type, role, now)

        # Handle reasoning vs assistant content
        if message_type == "reasoning":
            events.extend(self._handle_reasoning_chunk(chunk, role, now))
        else:
            events.extend(self._handle_assistant_chunk(chunk, message_type, role, now))

        return events

    def finalize(self) -> Tuple[Optional[FinalizedMessage], List[StreamEvent]]:
        """Finalize the current streaming message.

        Returns:
            Tuple of (FinalizedMessage or None, list of events to emit)
        """
        events: List[StreamEvent] = []

        if self._state == StreamState.INACTIVE:
            return None, events

        self._state = StreamState.FINALIZING

        # Flush any remaining buffer
        if self._emit_buffer:
            events.append(self._create_chunk_event(
                chunk=self._emit_buffer,
                message_type="assistant",
                is_final=False,
            ))
            self._emit_buffer = ""

        # Handle empty response (WALLET_GUARD)
        content = self._content
        was_empty = False
        if not content.strip():
            content = self.config.empty_response_placeholder
            was_empty = True
            self._metadata["was_empty"] = True

        # Build final metadata
        final_metadata = {
            **self._metadata,
            "has_reasoning": bool(self._reasoning_content),
        }
        if self._reasoning_content:
            final_metadata["reasoning"] = self._reasoning_content
            # Rough token estimate: ~4 chars per token
            final_metadata["reasoning_length"] = len(self._reasoning_content) // 4

        # Remove streaming flag
        final_metadata.pop("is_streaming", None)

        # Create finalized message
        message = FinalizedMessage(
            content=content,
            reasoning=self._reasoning_content,
            role=self._role,
            metadata=final_metadata,
            was_empty=was_empty,
        )

        # Emit final event
        events.append(StreamEvent(
            event_type="stream_chunk",
            data={
                "stream_id": self._stream_id,
                "chunk": "",
                "is_final": True,
                "message_type": "assistant",
                "role": self._role,
                "content": self._content,
                "reasoning": self._reasoning_content,
                "metadata": final_metadata,
            }
        ))

        # Reset state
        self._reset_state()

        return message, events

    def force_activate(self, message_type: str = "assistant", role: str = "assistant") -> None:
        """Force activation of streaming (for edge cases like empty first chunk).

        This is used by WALLET_GUARD to ensure streaming is active even when
        the first chunk is empty/whitespace.
        """
        if self._state == StreamState.INACTIVE:
            self._activate(message_type, role, datetime.now())

    def abort(self) -> List[StreamEvent]:
        """Abort the current stream without finalizing.

        Returns:
            List of events to emit (e.g., abort notification)
        """
        events: List[StreamEvent] = []

        if self._state != StreamState.INACTIVE:
            events.append(StreamEvent(
                event_type="stream_chunk",
                data={
                    "stream_id": self._stream_id,
                    "chunk": "",
                    "is_final": True,
                    "aborted": True,
                    "message_type": self._message_type,
                    "role": self._role,
                    "content": self._content,
                    "reasoning": self._reasoning_content,
                }
            ))

        self._reset_state()
        return events

    # --- Private Methods ---

    def _activate(self, message_type: str, role: str, now: datetime) -> None:
        """Activate streaming state."""
        self._state = StreamState.ACTIVE
        self._stream_id = uuid.uuid4().hex
        self._content = ""
        self._reasoning_content = ""
        self._message_type = message_type
        self._role = role
        self._started_at = now
        self._metadata = {"is_streaming": True}
        self._empty_response_count = 0
        self._error = None
        self._emit_buffer = ""
        self._last_emit_ts = 0.0

    def _handle_empty_chunk(
        self,
        message_type: str,
        role: str,
        now: datetime,
    ) -> List[StreamEvent]:
        """Handle empty chunk - WALLET_GUARD logic."""
        events: List[StreamEvent] = []

        # WALLET_GUARD: Even empty chunks must activate streaming
        # so finalize() can run and add placeholder
        if self._state == StreamState.INACTIVE:
            self._activate(message_type, role, now)

        self._empty_response_count += 1

        if self._empty_response_count > self.config.max_empty_chunks_before_warning:
            if not self._error:
                self._error = "Multiple empty responses received"

        return events

    def _handle_reasoning_chunk(
        self,
        chunk: str,
        role: str,
        now: datetime,
    ) -> List[StreamEvent]:
        """Handle reasoning content - emit immediately without coalescing."""
        self._reasoning_content += chunk
        self._last_update = now

        return [self._create_chunk_event(
            chunk=chunk,
            message_type="reasoning",
            is_final=False,
            is_reasoning=True,
        )]

    def _handle_assistant_chunk(
        self,
        chunk: str,
        message_type: str,
        role: str,
        now: datetime,
    ) -> List[StreamEvent]:
        """Handle assistant content with coalescing."""
        events: List[StreamEvent] = []

        self._content += chunk
        self._last_update = now

        # Coalescing logic
        ts_now = time.monotonic()
        self._emit_buffer += chunk

        should_emit = (
            len(self._emit_buffer) >= self.config.min_emit_chars or
            self._last_emit_ts == 0.0 or
            (ts_now - self._last_emit_ts) >= self.config.min_emit_interval
        )

        if should_emit:
            events.append(self._create_chunk_event(
                chunk=self._emit_buffer,
                message_type=message_type,
                is_final=False,
            ))
            self._emit_buffer = ""
            self._last_emit_ts = ts_now

        return events

    def _create_chunk_event(
        self,
        chunk: str,
        message_type: str,
        is_final: bool,
        is_reasoning: bool = False,
    ) -> StreamEvent:
        """Create a stream_chunk event."""
        return StreamEvent(
            event_type="stream_chunk",
            data={
                "stream_id": self._stream_id,
                "chunk": chunk,
                "is_final": is_final,
                "message_type": message_type,
                "role": self._role,
                "content_so_far": self._content,
                "reasoning_so_far": self._reasoning_content,
                "metadata": self._metadata,
                "is_reasoning": is_reasoning,
            }
        )


# --- Legacy Abstract Classes (kept for backward compatibility) ---

class StreamHandler(ABC):
    """Abstract base class for processing raw provider streams.

    This handles the provider-specific stream format (e.g., OpenAI chunks).
    For state management and event generation, use StreamingStateManager.
    """

    def __init__(self, chunk_callback: Callable[[str], None] = None):
        """
        Initialize with optional callback for chunk processing
        Args:
            chunk_callback: Function to handle each chunk of streamed content
        """
        self.chunk_callback = chunk_callback

    @abstractmethod
    async def handle_stream(self, stream: AsyncIterator[Any]) -> str:
        """Process a stream and return the collected response"""
        pass


class DefaultStreamHandler(StreamHandler):
    """Default implementation for OpenAI-style streaming responses."""

    async def handle_stream(self, stream: AsyncIterator[Any]) -> str:
        collected_chunks = []
        try:
            async for chunk in stream:
                if hasattr(chunk, "choices") and chunk.choices:
                    delta = chunk.choices[0].delta
                    if hasattr(delta, "content") and delta.content:
                        collected_chunks.append(delta.content)
                        if self.chunk_callback:
                            self.chunk_callback(delta.content)
            return "".join(collected_chunks)
        except Exception as e:
            raise ValueError(f"Error processing stream: {str(e)}")


__all__ = [
    "StreamState",
    "StreamEvent",
    "StreamingConfig",
    "FinalizedMessage",
    "StreamingStateManager",
    "StreamHandler",
    "DefaultStreamHandler",
]
