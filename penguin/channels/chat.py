"""Shared execution seam for interactive chat transports."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Mapping, Optional, Sequence

from penguin.core_runtime import process_lifecycle
from penguin.system.execution_context import ExecutionContext, execution_context_scope

__all__ = [
    "ChatProcessRequest",
    "ChatRuntimeResolutionError",
    "ChatRuntimeResolver",
    "ChatStreamCallback",
    "execute_chat_turn",
]

logger = logging.getLogger(__name__)

ChatStreamCallback = Callable[[str, str], Awaitable[None]]
ChatRuntimeResolver = Callable[[], Awaitable[Optional[tuple[Any, Any]]]]


class ChatRuntimeResolutionError(RuntimeError):
    """A request-scoped runtime could not be resolved."""


@dataclass(frozen=True)
class ChatProcessRequest:
    """A fully normalized request ready for :meth:`PenguinCore.process`.

    HTTP, Telegram, and future transports retain responsibility for authentication,
    parsing, and presentation. This request owns the concurrency and authority
    boundary that every interactive transport must share.
    """

    input_data: str | Mapping[str, Any]
    execution_context: ExecutionContext
    session_id: str | None = None
    context: Mapping[str, Any] | None = None
    agent_id: str | None = None
    max_iterations: int | None = None
    context_files: Sequence[str] = field(default_factory=tuple)
    streaming: bool = True
    stream_callback: ChatStreamCallback | None = None
    api_client_override: Any = None
    model_config_override: Any = None
    runtime_resolver: ChatRuntimeResolver | None = None


def _track_request(core: Any, session_id: str | None) -> asyncio.Task[Any] | None:
    """Register a turn before it waits for the per-session execution gate."""

    if not session_id:
        return None
    task = asyncio.current_task()
    if task is None:
        return None
    tasks_map = getattr(core, "_opencode_process_tasks", None)
    if not isinstance(tasks_map, dict):
        tasks_map = {}
        setattr(core, "_opencode_process_tasks", tasks_map)
    tasks = tasks_map.get(session_id)
    if not isinstance(tasks, set):
        tasks = set()
        tasks_map[session_id] = tasks
    tasks.add(task)
    return task


def _untrack_request(
    core: Any,
    session_id: str | None,
    task: asyncio.Task[Any] | None,
) -> None:
    if not session_id or task is None:
        return
    tasks_map = getattr(core, "_opencode_process_tasks", None)
    if not isinstance(tasks_map, dict):
        return
    tasks = tasks_map.get(session_id)
    if not isinstance(tasks, set):
        return
    tasks.discard(task)
    if not tasks:
        tasks_map.pop(session_id, None)


async def execute_chat_turn(
    core: Any,
    request: ChatProcessRequest,
) -> dict[str, Any]:
    """Run one normalized turn with request scope and per-session serialization."""

    task = _track_request(core, request.session_id)
    gate = process_lifecycle.get_session_request_gate(core, request.session_id)
    try:
        with execution_context_scope(request.execution_context):
            async with gate:
                model_config_override = request.model_config_override
                api_client_override = request.api_client_override
                if request.runtime_resolver is not None:
                    try:
                        runtime = await request.runtime_resolver()
                    except (RuntimeError, ValueError) as exc:
                        raise ChatRuntimeResolutionError(str(exc)) from exc
                    if runtime is not None:
                        model_config_override, api_client_override = runtime
                result = await core.process(
                    input_data=request.input_data,
                    context=dict(request.context)
                    if request.context is not None
                    else None,
                    conversation_id=request.session_id,
                    agent_id=request.agent_id,
                    max_iterations=request.max_iterations,
                    context_files=list(request.context_files),
                    streaming=request.streaming,
                    stream_callback=request.stream_callback,
                    api_client_override=api_client_override,
                    model_config_override=model_config_override,
                )
        if not isinstance(result, dict):
            raise TypeError("PenguinCore.process() must return a dictionary")
        return result
    finally:
        _untrack_request(core, request.session_id, task)
