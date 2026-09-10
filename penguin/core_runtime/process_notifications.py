"""Bridge process events to their owning conversation and UI event stream."""

from __future__ import annotations

from dataclasses import replace
from functools import wraps
from typing import TYPE_CHECKING, Any

from penguin.system.execution_context import (
    ExecutionContext,
    execution_context_scope,
    get_current_execution_context,
)
from penguin.system.runtime_events import wrap_opencode_event
from penguin.system.state import MessageCategory
from penguin.tools.process_tools import process_owner
from penguin.tools.tool_manager import ToolManager

if TYPE_CHECKING:
    from collections.abc import Callable


def prepare_process_step(
    manager: ToolManager, cm: Any, context: ExecutionContext
) -> None:
    """Bind scoped events and persist completed-process notices before an LLM step."""
    service = manager.process_tools
    owner = process_owner(context.as_dict())
    core = getattr(cm, "core", None)
    if core is not None and callable(getattr(core, "emit_ui_event", None)):

        async def emit(kind: str, payload: dict[str, Any]) -> None:
            properties = {
                **payload,
                "sessionID": owner[0],
                "conversation_id": owner[0],
                "session_id": owner[0],
                "agent_id": owner[1],
            }
            event_type = (
                "notification.process.completed"
                if kind == "completed"
                else "tool.process.output"
            )
            await core.emit_ui_event(
                "opencode_event",
                wrap_opencode_event(
                    event_type,
                    properties,
                    default_session_id=owner[0],
                    default_directory=context.directory,
                ),
            )
            if kind == "completed":
                await core.emit_ui_event(
                    "opencode_event",
                    wrap_opencode_event(
                        "tui.toast.show",
                        {
                            "sessionID": owner[0],
                            "agent_id": owner[1],
                            "title": "Background command finished",
                            "message": (
                                f"{payload['process_id']}: exit {payload['returncode']}"
                            ),
                            "variant": "success"
                            if payload["returncode"] == 0
                            else "warning",
                        },
                        default_session_id=owner[0],
                        default_directory=context.directory,
                    ),
                )

        service.bind(owner, emit)
    for notice in service.pending(owner):
        # Lifecycle-only text: command output stays in tool results/logs and is
        # never promoted into a system instruction or an orphaned native result.
        cm.conversation.add_message(
            "system",
            f"Background process {notice['process_id']} finished: "
            f"returncode={notice['returncode']}, reason={notice['completion_reason']}. "
            "Its retained output is available through process_poll.",
            category=MessageCategory.SYSTEM_OUTPUT,
            metadata={"process_id": notice["process_id"], "process_notification": True},
        )
        service.acknowledge(owner, notice["process_id"])


def process_session_scope(step: Callable[..., Any]) -> Callable[..., Any]:
    """Give tools and completion delivery a stable owner for an entire LLM step."""

    @wraps(step)
    async def wrapped(engine: Any, *args: Any, **kwargs: Any) -> Any:
        agent_id = kwargs.get("agent_id") or engine.current_agent_id
        cm, _, manager, _ = engine._resolve_components(agent_id)
        if not isinstance(manager, ToolManager):
            return await step(engine, *args, **kwargs)
        session_id = engine._conversation_session_id(cm)
        previous = get_current_execution_context() or ExecutionContext()
        context = replace(
            previous,
            session_id=session_id or previous.session_id,
            conversation_id=session_id or previous.conversation_id,
            agent_id=agent_id or previous.agent_id or "agent",
        )
        with execution_context_scope(context):
            prepare_process_step(manager, cm, context)
            return await step(engine, *args, **kwargs)

    return wrapped


__all__ = ["prepare_process_step", "process_session_scope"]
