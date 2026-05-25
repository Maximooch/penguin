"""Streaming and RunMode event compatibility facade for ``PenguinCore``."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from penguin.utils.callbacks import adapt_stream_callback

from . import (
    runmode_events as core_runmode_events,
    stream_events as core_stream_events,
    streaming_state as core_streaming_state,
    token_usage_runtime as core_token_usage_runtime,
)

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from penguin.system.state import Message, MessageCategory

__all__ = ["StreamingCoreFacade"]

logger = logging.getLogger("penguin.core")


def _trace_log_info(message: str, *args: Any) -> None:
    """Mirror core trace logs to uvicorn for live server debugging."""
    logger.info(message, *args)
    uvicorn_logger = logging.getLogger("uvicorn.error")
    if uvicorn_logger is not logger:
        uvicorn_logger.info(message, *args)


class StreamingCoreFacade:
    """Compatibility methods for core streaming and RunMode event helpers."""

    @property
    def total_tokens_used(self) -> int:
        """Get total tokens used via conversation manager."""
        return core_streaming_state.total_tokens_used(self)

    @property
    def streaming_active(self) -> bool:
        """Whether streaming is currently active for the default agent."""
        return core_streaming_state.streaming_active(self)

    @property
    def streaming_content(self) -> str:
        """Accumulated assistant content from default agent's stream."""
        return core_streaming_state.streaming_content(self)

    @property
    def streaming_reasoning_content(self) -> str:
        """Accumulated reasoning content from default agent's stream."""
        return core_streaming_state.streaming_reasoning_content(self)

    @property
    def streaming_stream_id(self) -> str | None:
        """Unique ID of the default agent's stream, or None if not streaming."""
        return core_streaming_state.streaming_stream_id(self)

    def is_agent_streaming(self, agent_id: str) -> bool:
        """Check if a specific agent is currently streaming."""
        return core_streaming_state.is_agent_streaming(self, agent_id)

    def get_agent_streaming_content(self, agent_id: str) -> str:
        """Get accumulated streaming content for a specific agent."""
        return core_streaming_state.get_agent_streaming_content(self, agent_id)

    def get_agent_streaming_reasoning(self, agent_id: str) -> str:
        """Get accumulated reasoning content for a specific agent."""
        return core_streaming_state.get_agent_streaming_reasoning(self, agent_id)

    def get_active_streaming_agents(self) -> list[str]:
        """Get list of agent IDs that are currently streaming."""
        return core_streaming_state.get_active_streaming_agents(self)

    def cleanup_agent_streaming(self, agent_id: str) -> None:
        """Clean up streaming state for a terminated agent."""
        core_streaming_state.cleanup_agent_streaming(self, agent_id)

    async def _emit_opencode_session_status(
        self,
        session_id: str,
        status_type: str,
        info: dict[str, Any] | None = None,
    ) -> None:
        """Emit OpenCode session.status event for a session."""
        await core_stream_events.emit_opencode_session_status(
            self,
            session_id,
            status_type,
            info=info,
        )

    async def abort_session(self, session_id: str) -> bool:
        """Abort active streaming/tool state for a session."""
        return await core_stream_events.abort_session(self, session_id, logger=logger)

    async def emit_ui_event(self, event_type: str, data: dict[str, Any]) -> None:
        """Emit an event through the unified event bus."""
        await core_stream_events.emit_ui_event(
            self,
            event_type,
            data,
            logger=logger,
        )

    def _filter_internal_markers_from_event(
        self,
        data: dict[str, Any],
    ) -> dict[str, Any]:
        """Filter internal implementation markers from event data."""
        return core_stream_events.filter_internal_markers_from_event(data)

    def _resolve_stream_scope_id(
        self,
        execution_context: Any | None,
        agent_id: str | None,
    ) -> str:
        """Resolve stream-state key for concurrent session isolation."""
        return core_stream_events.resolve_stream_scope_id(
            conversation_manager=getattr(self, "conversation_manager", None),
            execution_context=execution_context,
            agent_id=agent_id,
        )

    async def _handle_stream_chunk(
        self,
        chunk: str,
        message_type: str | None = None,
        role: str = "assistant",
        agent_id: str | None = None,
        stream_scope_id: str | None = None,
        session_id: str | None = None,
        conversation_id: str | None = None,
    ) -> None:
        """Handle streaming content chunks from any source."""
        await core_stream_events.handle_stream_chunk(
            self,
            chunk,
            message_type=message_type,
            role=role,
            agent_id=agent_id,
            stream_scope_id=stream_scope_id,
            session_id=session_id,
            conversation_id=conversation_id,
            logger=logger,
        )

    def finalize_streaming_message(
        self,
        agent_id: str | None = None,
        session_id: str | None = None,
        conversation_id: str | None = None,
        stream_scope_id: str | None = None,
    ) -> dict[str, Any] | None:
        """Finalize and persist the current streaming message."""
        return core_stream_events.finalize_streaming_message(
            self,
            agent_id=agent_id,
            session_id=session_id,
            conversation_id=conversation_id,
            stream_scope_id=stream_scope_id,
            logger=logger,
            trace_log=_trace_log_info,
        )

    def abort_streaming_message(
        self,
        agent_id: str | None = None,
        session_id: str | None = None,
        conversation_id: str | None = None,
        stream_scope_id: str | None = None,
    ) -> bool:
        """Abort an uncommitted streaming message without persisting dialog."""
        return core_stream_events.abort_streaming_message(
            self,
            agent_id=agent_id,
            session_id=session_id,
            conversation_id=conversation_id,
            stream_scope_id=stream_scope_id,
            trace_log=_trace_log_info,
        )

    def _persist_finalized_message(
        self,
        *,
        agent_id: str,
        session_id: str | None,
        message: Message,
        category: MessageCategory,
    ) -> bool:
        """Persist a finalized streaming message without reloading conversations."""
        return core_stream_events.persist_finalized_message(
            self,
            agent_id=agent_id,
            session_id=session_id,
            message=message,
            category=category,
            trace_log=_trace_log_info,
        )

    def _prepare_runmode_stream_callback(
        self,
        callback: Callable[..., Any] | None,
    ) -> Callable[[str, str], Awaitable[None]] | None:
        """Normalize run mode stream callbacks to a common async signature."""
        return core_stream_events.prepare_runmode_stream_callback(
            callback,
            adapter_factory=adapt_stream_callback,
        )

    async def _invoke_runmode_stream_callback(
        self,
        chunk: str,
        message_type: str,
        callback: Callable[[str, str], Awaitable[None]] | None = None,
    ) -> None:
        await core_stream_events.invoke_runmode_stream_callback(
            self,
            chunk,
            message_type,
            callback=callback,
            logger=logger,
        )

    def update_token_display(self) -> None:
        """Emit token usage event to UI subscribers."""
        core_token_usage_runtime.emit_token_display_update(self, log=logger)

    async def _handle_run_mode_event(self, event: dict[str, Any]) -> None:
        """Handle events emitted by RunMode."""
        await core_runmode_events.handle_run_mode_event(self, event, logger=logger)
