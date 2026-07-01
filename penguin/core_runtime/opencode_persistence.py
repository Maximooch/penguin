"""OpenCode transcript persistence helpers."""

from __future__ import annotations

from typing import Any

from penguin.system.execution_context import get_current_execution_context

from . import (
    opencode_bridge as core_opencode_bridge,
    opencode_transcript as core_opencode_transcript,
    session_lookup as core_session_lookup,
)

__all__ = [
    "persist_opencode_event",
    "resolve_opencode_model_state",
]


def resolve_opencode_model_state(
    owner: Any,
    *,
    session_id: str | None = None,
    model_id: str | None = None,
    provider_id: str | None = None,
    variant: str | None = None,
) -> dict[str, str | None]:
    """Resolve model/provider/variant for OpenCode event persistence."""

    session_meta: dict[str, Any] = {}
    normalized_session_id = core_opencode_bridge.normalize_optional_string(session_id)
    if normalized_session_id:
        session, _ = _find_session_store(owner, normalized_session_id)
        metadata = getattr(session, "metadata", None) if session is not None else None
        if isinstance(metadata, dict):
            session_meta = metadata

    return core_opencode_bridge.resolve_model_state(
        session_metadata=session_meta,
        model_config=getattr(owner, "model_config", None),
        model_id=model_id,
        provider_id=provider_id,
        variant=variant,
    )


async def persist_opencode_event(
    owner: Any,
    event_type: str,
    properties: dict[str, Any],
    *,
    logger: Any,
    execution_context: Any = None,
) -> None:
    """Persist OpenCode message/part events for replay via session history."""

    session_id = core_opencode_transcript.resolve_event_session_id(
        event_type,
        properties,
    )
    if session_id is None:
        return

    session, manager = _find_session_store(owner, session_id)
    if session is None or manager is None:
        return

    metadata = getattr(session, "metadata", None)
    if not isinstance(metadata, dict):
        return

    context = execution_context
    if context is None:
        context = get_current_execution_context()

    def assistant_info_factory(
        message_id: str,
        resolved_session_id: str,
    ) -> dict[str, Any]:
        fallback_directory = core_opencode_bridge.resolve_adapter_directory(
            resolved_session_id,
            session_directories=getattr(owner, "_opencode_session_directories", None),
            execution_context=context,
            runtime_config=getattr(owner, "runtime_config", None),
        )
        model_state = resolve_opencode_model_state(
            owner,
            session_id=resolved_session_id,
        )
        return core_opencode_bridge.build_assistant_message_info(
            message_id=message_id,
            session_id=resolved_session_id,
            directory=fallback_directory,
            model_state=model_state,
        )

    result = core_opencode_transcript.apply_transcript_event(
        metadata=metadata,
        event_type=event_type,
        properties=properties,
        session_id=session_id,
        assistant_info_factory=assistant_info_factory,
    )
    if not result.mark_modified:
        return

    try:
        manager.mark_session_modified(session_id)
        if result.should_save:
            manager.save_session(session)
    except Exception:
        logger.warning("Unable to persist OpenCode transcript event", exc_info=True)


def _find_session_store(owner: Any, session_id: str) -> tuple[Any | None, Any | None]:
    finder = getattr(owner, "_find_session_store", None)
    if callable(finder):
        return finder(session_id)
    return core_session_lookup.find_session_store(owner, session_id)
