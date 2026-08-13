"""Engine process dispatch helpers for :mod:`penguin.core`."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable

__all__ = [
    "run_engine_process",
]


def _conversation_session_id(conversation_manager: Any) -> str:
    return (
        getattr(
            getattr(
                getattr(conversation_manager, "conversation", None),
                "session",
                None,
            ),
            "id",
            None,
        )
        or "unknown"
    )


def _conversation_identity(conversation_manager: Any) -> str:
    conversation = getattr(conversation_manager, "conversation", None)
    return hex(id(conversation)) if conversation is not None else "none"


def _formal_task_message_callback(stream_callback: Any) -> Callable[..., Any] | None:
    if not stream_callback:
        return None

    pending_tasks: set[asyncio.Task[Any]] = set()

    async def bridged_callback(
        message: str,
        msg_type: str,
        action_name: str | None = None,
        **kwargs: Any,
    ) -> None:
        if msg_type == "assistant":
            task = asyncio.create_task(asyncio.to_thread(stream_callback, message))
            pending_tasks.add(task)
            task.add_done_callback(pending_tasks.discard)

    return bridged_callback


def _trace_engine_process(
    *,
    trace_log_info: Any,
    execution_context: Any,
    request_session_id: str | None,
    scoped_conversation_id: str | None,
    agent_id: str | None,
    is_formal_task: bool,
    conversation_manager: Any,
) -> None:
    trace_log_info(
        "core.process.trace.engine request=%s session=%s conversation=%s "
        "agent=%s formal_task=%s cm=%s conv=%s conv_session=%s",
        (
            getattr(execution_context, "request_id", None)
            if execution_context
            else "unknown"
        ),
        request_session_id or "unknown",
        scoped_conversation_id or "",
        agent_id or "default",
        bool(is_formal_task),
        hex(id(conversation_manager)),
        _conversation_identity(conversation_manager),
        _conversation_session_id(conversation_manager),
    )


async def run_engine_process(
    owner: Any,
    *,
    message: str,
    image_paths: list[str],
    max_iterations: int | None,
    context: dict[str, Any] | None,
    multi_step: bool,
    streaming: bool | None,
    stream_callback: Any,
    engine_stream_callback: Any,
    agent_id: str | None,
    api_client_override: Any,
    model_config_override: Any,
    conversation_manager: Any,
    execution_context: Any,
    request_session_id: str | None,
    scoped_conversation_id: str | None,
    trace_log_info: Any,
    tools_enabled: bool = True,
    allowed_tool_names: list[str] | None = None,
    include_web_search: bool = True,
) -> Any:
    """Dispatch a process request through the configured Engine."""
    profile_kwargs: dict[str, Any] = {}
    if not (tools_enabled and allowed_tool_names is None and include_web_search):
        profile_kwargs = {
            "tools_enabled": tools_enabled,
            "allowed_tool_names": allowed_tool_names,
            "include_web_search": include_web_search,
        }

    if multi_step:
        is_formal_task = bool(context and context.get("task_mode", False))
        _trace_engine_process(
            trace_log_info=trace_log_info,
            execution_context=execution_context,
            request_session_id=request_session_id,
            scoped_conversation_id=scoped_conversation_id,
            agent_id=agent_id,
            is_formal_task=is_formal_task,
            conversation_manager=conversation_manager,
        )

        if is_formal_task:
            return await owner.engine.run_task(
                task_prompt=message,
                image_paths=image_paths,
                max_iterations=max_iterations,
                task_context=context,
                message_callback=_formal_task_message_callback(stream_callback),
                agent_id=agent_id,
                api_client_override=api_client_override,
                model_config_override=model_config_override,
                **profile_kwargs,
            )

        return await owner.engine.run_response(
            prompt=message,
            image_paths=image_paths,
            max_iterations=max_iterations,
            streaming=streaming,
            stream_callback=engine_stream_callback,
            agent_id=agent_id,
            api_client_override=api_client_override,
            model_config_override=model_config_override,
            **profile_kwargs,
        )

    return await owner.engine.run_single_turn(
        message,
        image_paths=image_paths,
        streaming=streaming,
        stream_callback=engine_stream_callback,
        agent_id=agent_id,
        api_client_override=api_client_override,
        model_config_override=model_config_override,
        **profile_kwargs,
    )
