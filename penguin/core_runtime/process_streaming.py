"""Process streaming helpers for :mod:`penguin.core`."""

from __future__ import annotations

import asyncio
import inspect
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

__all__ = [
    "EngineProcessContext",
    "prepare_engine_process_context",
]


@dataclass(frozen=True)
class EngineProcessContext:
    """Resolved stream context for an engine-backed process call."""

    stream_callback: Callable[[str, str], Awaitable[None]] | None
    scoped_conversation_id: str | None
    scoped_session_id: str | None
    stream_scope_id: str | None


def _callback_accepts_message_type(callback: Any) -> bool:
    try:
        return len(inspect.signature(callback).parameters) >= 2
    except Exception:
        return False


async def _invoke_external_stream_callback(
    callback: Any,
    chunk: str,
    message_type: str,
) -> None:
    accepts_message_type = _callback_accepts_message_type(callback)
    if asyncio.iscoroutinefunction(callback):
        if accepts_message_type:
            await callback(chunk, message_type)
        else:
            await callback(chunk)
        return

    if accepts_message_type:
        await asyncio.to_thread(callback, chunk, message_type)
    else:
        await asyncio.to_thread(callback, chunk)


def _resolve_scoped_ids(
    conversation_manager: Any,
    *,
    conversation_id: str | None,
    execution_context: Any,
) -> tuple[str | None, str | None]:
    scoped_conversation_id = conversation_id
    scoped_session_id = conversation_id

    if execution_context is not None:
        scoped_conversation_id = (
            getattr(execution_context, "conversation_id", None)
            or getattr(execution_context, "session_id", None)
            or scoped_conversation_id
        )
        scoped_session_id = (
            getattr(execution_context, "session_id", None)
            or scoped_conversation_id
            or scoped_session_id
        )

    if not scoped_session_id:
        try:
            active_session = conversation_manager.get_current_session()
            scoped_session_id = active_session.id if active_session else None
        except Exception:
            scoped_session_id = None

    if not scoped_conversation_id:
        scoped_conversation_id = scoped_session_id

    return scoped_conversation_id, scoped_session_id


def _prime_engine_conversation_manager(
    owner: Any,
    conversation_manager: Any,
    *,
    agent_id: str | None,
) -> None:
    engine = getattr(owner, "engine", None)
    if engine is None or not hasattr(engine, "prime_scoped_conversation_manager"):
        return
    prime_agent_id = agent_id or getattr(engine, "default_agent_id", "default")
    engine.prime_scoped_conversation_manager(prime_agent_id, conversation_manager)


def prepare_engine_process_context(
    owner: Any,
    *,
    conversation_manager: Any,
    conversation_id: str | None,
    agent_id: str | None,
    streaming: bool | None,
    stream_callback: Any,
    execution_context: Any,
    log: Any,
) -> EngineProcessContext:
    """Resolve engine process scope and build the optional stream callback."""
    stream_scope_id = owner._resolve_stream_scope_id(execution_context, agent_id)
    scoped_conversation_id, scoped_session_id = _resolve_scoped_ids(
        conversation_manager,
        conversation_id=conversation_id,
        execution_context=execution_context,
    )
    _prime_engine_conversation_manager(
        owner,
        conversation_manager,
        agent_id=agent_id,
    )

    async def scoped_stream_callback(
        chunk: str,
        message_type: str = "assistant",
    ) -> None:
        await owner._handle_stream_chunk(
            chunk,
            message_type=message_type,
            agent_id=agent_id,
            stream_scope_id=stream_scope_id,
            session_id=scoped_session_id,
            conversation_id=scoped_conversation_id,
        )

    if not streaming:
        engine_stream_callback = None
    elif stream_callback:

        async def combined_stream_callback(
            chunk: str,
            message_type: str = "assistant",
        ) -> None:
            await scoped_stream_callback(chunk, message_type)
            try:
                await _invoke_external_stream_callback(
                    stream_callback,
                    chunk,
                    message_type,
                )
            except Exception as cb_err:
                log.error(f"Error in external stream_callback: {cb_err}")

        engine_stream_callback = combined_stream_callback
    else:
        engine_stream_callback = scoped_stream_callback

    return EngineProcessContext(
        stream_callback=engine_stream_callback,
        scoped_conversation_id=scoped_conversation_id,
        scoped_session_id=scoped_session_id,
        stream_scope_id=stream_scope_id,
    )
