"""Checkpoint snapshot shaping outside the orchestration manager."""

from __future__ import annotations

import copy
import uuid
from datetime import datetime
from typing import Callable

from penguin.system.native_tool_history import preserve_native_tool_adjacency
from penguin.system.state import Message, MessageCategory, Session

__all__ = [
    "build_flat_session_snapshot",
    "preserve_native_tool_adjacency",
]


def build_flat_session_snapshot(
    tail_session: Session,
    *,
    lineage: list[str],
    load_session: Callable[[str], Session | None],
    preserve_session_identity: bool,
) -> Session:
    """Build one flattened lineage snapshot on an offload executor thread."""

    metadata = copy.deepcopy(tail_session.metadata)
    metadata.update(
        {
            "lineage": lineage,
            "flattened_snapshot": True,
            "original_created_at": (lineage[0] if lineage else tail_session.created_at),
        }
    )
    if not preserve_session_identity:
        metadata["branched_from"] = tail_session.id
    merged_session = Session(
        id=(tail_session.id if preserve_session_identity else _new_session_id()),
        created_at=tail_session.created_at,
        last_active=tail_session.last_active,
        metadata=metadata,
    )

    for session_id in lineage:
        source_session = (
            tail_session if session_id == tail_session.id else load_session(session_id)
        )
        if source_session is None:
            continue
        for lifecycle in source_session.llm_request_lifecycles:
            if isinstance(lifecycle, dict):
                merged_session.add_llm_request_lifecycle(copy.deepcopy(lifecycle))
        for tool_call_record in source_session.tool_call_records:
            if isinstance(tool_call_record, dict):
                merged_session.add_tool_call_record(copy.deepcopy(tool_call_record))
        for tool_result_record in source_session.tool_result_records:
            if isinstance(tool_result_record, dict):
                merged_session.add_tool_result_record(copy.deepcopy(tool_result_record))
        for message in source_session.messages:
            merged_session.add_message(
                Message(
                    role=message.role,
                    content=copy.deepcopy(message.content),
                    category=message.category,
                    id=message.id,
                    timestamp=message.timestamp,
                    metadata=copy.deepcopy(message.metadata),
                    tokens=message.tokens,
                    agent_id=message.agent_id,
                    recipient_id=message.recipient_id,
                    message_type=message.message_type,
                )
            )

    _dedupe_system_messages(merged_session)
    merged_session.last_active = tail_session.last_active
    merged_session.metadata["message_count"] = len(merged_session.messages)
    return merged_session


def _dedupe_system_messages(session: Session) -> None:
    """Keep only the newest system message of each metadata type."""

    seen_system_types: set[str] = set()
    messages_to_keep: list[Message] = []
    for message in reversed(session.messages):
        if message.category == MessageCategory.SYSTEM:
            message_type = str(message.metadata.get("type", "generic"))
            if message_type in seen_system_types:
                continue
            seen_system_types.add(message_type)
        messages_to_keep.append(message)
    session.messages = list(reversed(messages_to_keep))


def _new_session_id() -> str:
    """Create a new branch session id using Penguin's session-id shape."""

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"session_{timestamp}_{uuid.uuid4().hex[:8]}"
