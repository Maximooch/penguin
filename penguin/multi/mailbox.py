"""Session-bound steering, delivered only between complete model/tool steps."""

from __future__ import annotations

import time
from collections import defaultdict, deque
from typing import Any

from penguin.system.state import MessageCategory

__all__ = ["AgentMailbox"]


def _session_ids(session: Any) -> list[str]:
    """Return a session's id and the id of the session it continues.

    Args:
        session: A session object, or a session id.

    Returns:
        The current id first. A continuation session (made when a session
        reaches its boundary) also owns steering queued for its predecessor.
    """
    if isinstance(session, str):
        return [session] if session else []
    session_id = getattr(session, "id", None)
    if not session_id:
        return []
    ids = [session_id]
    metadata = getattr(session, "metadata", None)
    previous = metadata.get("continued_from") if isinstance(metadata, dict) else None
    if isinstance(previous, str) and previous:
        ids.append(previous)
    return ids


class AgentMailbox:
    """Keep messages off mutable transcripts until a safe step boundary."""

    def __init__(self) -> None:
        self._pending: dict[tuple[str, str], deque[Any]] = defaultdict(deque)
        self._progress: dict[str, dict[str, Any]] = {}

    def enqueue(self, agent_id: str, session_id: str, message: Any) -> None:
        """Queue an envelope for its target session, never the sender's session."""
        self._pending[agent_id, session_id].append(message)

    def deliver(self, agent_id: str, manager: Any) -> None:
        """Persist queued steering before formatting the next provider request."""
        ids = _session_ids(getattr(manager.conversation, "session", None))
        if not ids:
            return
        session_id = ids[0]
        for previous in ids[1:]:
            carried = self._pending.pop((agent_id, previous), None)
            if carried:
                self._pending[agent_id, session_id].extendleft(reversed(carried))
        pending = self._pending.get((agent_id, session_id))
        while pending:
            message = pending[0]
            if not any(
                item.metadata.get("message_id") == message.message_id
                for item in manager.conversation.session.messages
                if message.message_id and isinstance(item.metadata, dict)
            ):
                manager.conversation.add_message(
                    role="user",
                    content=message.content,
                    category=MessageCategory.DIALOG,
                    metadata={
                        **message.metadata,
                        "via": "agent_mailbox",
                        "sender": message.sender,
                        "message_id": message.message_id,
                        "channel": message.channel,
                    },
                )
            if manager.save() is False:
                raise RuntimeError("Unable to persist queued agent message")
            pending.popleft()
            self._progress[agent_id] = {
                "session_id": session_id,
                "last_delivered_message_id": message.message_id,
                "last_progress_at": time.time(),
            }
        self._pending.pop((agent_id, session_id), None)

    def status(self, agent_id: str) -> dict[str, Any]:
        """Expose acknowledgement and queue depth without reading content."""
        return {
            **self._progress.get(agent_id, {}),
            "queued_messages": sum(
                len(queue)
                for (aid, _), queue in self._pending.items()
                if aid == agent_id
            ),
        }

    def note_progress(self, agent_id: str, session_id: str, phase: str) -> None:
        """Record a model/tool step boundary for status diagnostics."""
        self._progress.setdefault(agent_id, {}).update(
            session_id=session_id, last_progress_at=time.time(), phase=phase
        )

    def has_pending(self, agent_id: str, session: Any) -> bool:
        """Return whether this session has steering for its next step.

        Args:
            agent_id: Recipient agent.
            session: The agent's current session object, or a session id.
        """
        return any(
            self._pending.get((agent_id, session_id))
            for session_id in _session_ids(session)
        )

    def remove(self, agent_id: str) -> None:
        """Drop stale queues when an agent is explicitly unregistered."""
        for key in list(self._pending):
            if key[0] == agent_id:
                del self._pending[key]
        self._progress.pop(agent_id, None)
