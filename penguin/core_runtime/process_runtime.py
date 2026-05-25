"""Process orchestration helpers for :mod:`penguin.core`."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from penguin.system.execution_context import get_current_execution_context
from penguin.system.state import MessageCategory

from . import (
    conversations as core_conversations,
    process_engine as core_process_engine,
    process_input as core_process_input,
    process_lifecycle as core_process_lifecycle,
    process_streaming as core_process_streaming,
    token_usage_runtime as core_token_usage_runtime,
)

if TYPE_CHECKING:
    import logging
    from collections.abc import Awaitable, Callable

__all__ = ["process", "process_with_retry"]


def _process_retry_error_callback(retry_state: Any) -> Any:
    """Preserve PenguinCore.process retry exhaustion behavior."""
    exception = retry_state.outcome.exception()
    if isinstance(exception, KeyboardInterrupt):
        return None
    return exception


def _process_retrying(
    *,
    sleep: Callable[[float], Awaitable[None]] | None = None,
) -> AsyncRetrying:
    """Build the retry policy for public process requests."""
    kwargs: dict[str, Any] = {
        "stop": stop_after_attempt(3),
        "wait": wait_exponential(multiplier=1, min=4, max=10),
        "reraise": True,
        "retry": retry_if_exception_type(Exception),
        "retry_error_callback": _process_retry_error_callback,
    }
    if sleep is not None:
        kwargs["sleep"] = sleep
    return AsyncRetrying(**kwargs)


async def process_with_retry(
    owner: Any,
    *,
    input_data: dict[str, Any] | str,
    context: dict[str, Any] | None,
    conversation_id: str | None,
    agent_id: str | None,
    max_iterations: int,
    context_files: list[str] | None,
    streaming: bool | None,
    stream_callback: Callable[[str], None] | None,
    multi_step: bool,
    api_client_override: Any,
    model_config_override: Any,
    log: logging.Logger,
    trace_log_info: Callable[..., None],
    log_error_fn: Callable[..., None],
    retry_sleep: Callable[[float], Awaitable[None]] | None = None,
) -> dict[str, Any] | BaseException:
    """Process a user request with the public retry policy applied."""
    retrying = _process_retrying(sleep=retry_sleep)
    return await retrying(
        process,
        owner,
        input_data=input_data,
        context=context,
        conversation_id=conversation_id,
        agent_id=agent_id,
        max_iterations=max_iterations,
        context_files=context_files,
        streaming=streaming,
        stream_callback=stream_callback,
        multi_step=multi_step,
        api_client_override=api_client_override,
        model_config_override=model_config_override,
        log=log,
        trace_log_info=trace_log_info,
        log_error_fn=log_error_fn,
    )


async def process(
    owner: Any,
    *,
    input_data: dict[str, Any] | str,
    context: dict[str, Any] | None,
    conversation_id: str | None,
    agent_id: str | None,
    max_iterations: int,
    context_files: list[str] | None,
    streaming: bool | None,
    stream_callback: Callable[[str], None] | None,
    multi_step: bool,
    api_client_override: Any,
    model_config_override: Any,
    log: logging.Logger,
    trace_log_info: Callable[..., None],
    log_error_fn: Callable[..., None],
) -> dict[str, Any]:
    """Process a user request through PenguinCore-owned collaborators."""

    process_input = core_process_input.normalize_process_input(input_data)
    message = process_input.message
    image_paths = process_input.image_paths
    client_message_id = process_input.client_message_id

    if process_input.is_empty:
        return {"assistant_response": "No input provided", "action_results": []}

    conversation_manager = core_conversations.resolve_conversation_manager(
        owner,
        agent_id,
        log=log,
    )

    execution_context = get_current_execution_context()
    request_session_id = (
        execution_context.session_id
        if execution_context and execution_context.session_id
        else conversation_id
    )
    scoped_conversation = getattr(conversation_manager, "conversation", None)
    scoped_session_before = getattr(
        getattr(scoped_conversation, "session", None), "id", None
    )
    trace_log_info(
        "core.process.trace.start request=%s session=%s conversation=%s agent=%s "
        "cm=%s conv=%s conv_session=%s msg_len=%s context_files=%s images=%s "
        "streaming=%s multi_step=%s",
        execution_context.request_id if execution_context else "unknown",
        request_session_id or "unknown",
        conversation_id or "",
        agent_id or "default",
        hex(id(conversation_manager)),
        hex(id(scoped_conversation)) if scoped_conversation is not None else "none",
        scoped_session_before or "unknown",
        len(message or ""),
        len(context_files or []),
        len(image_paths or []),
        streaming,
        multi_step,
    )
    request_task = asyncio.current_task()
    request_tracked = await core_process_lifecycle.register_opencode_process_request(
        owner,
        request_session_id,
        request_task,
    )

    try:
        if conversation_id:
            load_result = core_conversations.load_process_conversation(
                conversation_manager,
                conversation_id,
                log=log,
            )
            trace_log_info(
                "core.process.trace.load request=%s session=%s conversation=%s "
                "via=%s ok=%s conv_session=%s",
                execution_context.request_id if execution_context else "unknown",
                request_session_id or "unknown",
                conversation_id,
                load_result.via,
                load_result.ok,
                load_result.scoped_session_id or "unknown",
            )

        context_file_count = core_conversations.load_process_context_files(
            conversation_manager,
            context_files,
        )
        if context_file_count:
            trace_log_info(
                "core.process.trace.context request=%s session=%s conversation=%s "
                "count=%s",
                execution_context.request_id if execution_context else "unknown",
                request_session_id or "unknown",
                conversation_id or "",
                context_file_count,
            )

        await core_process_lifecycle.emit_process_user_message(
            owner,
            message,
            message_category=MessageCategory.DIALOG,
            client_message_id=client_message_id,
            agent_id=agent_id,
            log=log,
        )

        if owner.engine:
            execution_context = get_current_execution_context()
            engine_process_context = (
                core_process_streaming.prepare_engine_process_context(
                    owner,
                    conversation_manager=conversation_manager,
                    conversation_id=conversation_id,
                    agent_id=agent_id,
                    streaming=streaming,
                    stream_callback=stream_callback,
                    execution_context=execution_context,
                    log=log,
                )
            )
            engine_stream_callback = engine_process_context.stream_callback
            scoped_conversation_id = engine_process_context.scoped_conversation_id
            response = await core_process_engine.run_engine_process(
                owner,
                message=message,
                image_paths=image_paths,
                max_iterations=max_iterations,
                context=context,
                multi_step=multi_step,
                streaming=streaming,
                stream_callback=stream_callback,
                engine_stream_callback=engine_stream_callback,
                agent_id=agent_id,
                api_client_override=api_client_override,
                model_config_override=model_config_override,
                conversation_manager=conversation_manager,
                execution_context=execution_context,
                request_session_id=request_session_id,
                scoped_conversation_id=scoped_conversation_id,
                trace_log_info=trace_log_info,
            )
            trace_log_info(
                "core.process.trace.done request=%s session=%s conversation=%s "
                "status=%s iterations=%s actions=%s usage=%s response_len=%s",
                execution_context.request_id if execution_context else "unknown",
                request_session_id or "unknown",
                scoped_conversation_id,
                response.get("status") if isinstance(response, dict) else None,
                response.get("iterations") if isinstance(response, dict) else None,
                len(response.get("action_results", []) or [])
                if isinstance(response, dict)
                else None,
                response.get("usage") if isinstance(response, dict) else None,
                len(response.get("assistant_response", "") or "")
                if isinstance(response, dict)
                else None,
            )
        else:
            conversation_manager.conversation.prepare_conversation(
                message,
                image_paths=image_paths,
            )
            internal_stream_callback = owner._handle_stream_chunk if streaming else None
            response, _ = await owner.get_response(
                stream_callback=internal_stream_callback,
                streaming=streaming,
            )

        await core_process_lifecycle.finalize_process_response(
            owner,
            conversation_manager,
            response,
            request_session_id,
            streaming=streaming,
            agent_id=agent_id,
            collect_token_usage=core_token_usage_runtime.collect_process_token_usage,
            message_category=MessageCategory.DIALOG,
            log=log,
        )

        return response

    except asyncio.CancelledError:
        return core_process_lifecycle.handle_process_cancelled(
            owner,
            request_session_id,
        )

    except Exception as exc:
        return await core_process_lifecycle.handle_process_error(
            owner,
            exc,
            input_data,
            log=log,
            log_error_fn=log_error_fn,
        )

    finally:
        await core_process_lifecycle.finalize_opencode_process_request(
            owner,
            request_session_id,
            request_task,
            request_tracked=request_tracked,
        )
