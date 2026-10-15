"""Request-local, append-only context selection; never owns durable history."""

from __future__ import annotations

import copy
import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from penguin.llm.contracts import stable_payload_hash

if TYPE_CHECKING:
    from penguin.system.context_window import ContextWindowManager
    from penguin.system.state import Message, Session
from penguin.utils.errors import ContextWindowExceededError

__all__ = ["ContextEpoch"]
logger = logging.getLogger(__name__)


@dataclass
class ContextEpoch:
    """Keep a budgeted selection stable until source edits or safety limits."""

    session_id: str = ""
    source_signatures: list[str] = field(default_factory=list)
    selected_messages: list[Message] = field(default_factory=list)
    generation: int = 0
    reason: str = "initial"
    limits: tuple[int, int] | None = None

    def select(self, source: Session, manager: ContextWindowManager | None) -> Session:
        """Select copied messages, rebasing on edits, session changes or overflow."""
        snapshot = copy.deepcopy(source)
        signatures = [
            stable_payload_hash(
                {
                    "id": message.id,
                    "role": message.role,
                    "content": message.content,
                    "category": message.category.name,
                    "metadata": message.metadata,
                    "timestamp": message.timestamp,
                }
            )
            for message in snapshot.messages
        ]
        limits = (
            (manager.max_context_window_tokens, manager.max_context_images)
            if manager
            else None
        )
        unchanged = (
            self.limits == limits
            and self.session_id == source.id
            and signatures[: len(self.source_signatures)] == self.source_signatures
            and len(signatures) >= len(self.source_signatures)
        )
        if unchanged and self.generation:
            additions = snapshot.messages[len(self.source_signatures) :]
            if any(
                message.category.name in {"SYSTEM", "CONTEXT"} for message in additions
            ):
                return self._rebase(source, manager, signatures, "prefix_changed")
            snapshot.messages = [*copy.deepcopy(self.selected_messages), *additions]
            stats = manager.analyze_session(snapshot) if manager else None
            if not manager or (
                stats["total_tokens"] <= manager.max_context_window_tokens
                and stats["image_count"] <= manager.max_context_images
            ):
                self.selected_messages = copy.deepcopy(snapshot.messages)
                self.source_signatures = signatures
                self.reason = "append"
                if manager:
                    manager.reset_usage()
                    for message in snapshot.messages:
                        manager.update_usage(message.category, message.tokens)
                return snapshot
            self.reason = "safety_limit"
        else:
            self.reason = "source_changed" if self.generation else "initial"
        return self._rebase(source, manager, signatures, self.reason)

    def _rebase(
        self,
        source: Session,
        manager: ContextWindowManager | None,
        signatures: list[str],
        reason: str,
    ) -> Session:
        snapshot = copy.deepcopy(source)
        self.reason = reason
        if manager:
            # Source edits and model switches invalidate cached token counts.
            for message in snapshot.messages:
                message.tokens = manager.token_counter(message.content)
        if manager:
            # Image-only overflow is not handled by process_session.
            if (
                manager.analyze_session(snapshot)["image_count"]
                > manager.max_context_images
            ):
                snapshot = manager._handle_image_trimming(snapshot)
            snapshot = manager.process_session(snapshot)
            stats = manager.analyze_session(snapshot)
            if stats["total_tokens"] > manager.max_context_window_tokens:
                raise ContextWindowExceededError(
                    "Context exceeds model limit after priority trimming"
                )
        snapshot.messages = self._complete_tool_groups(
            source.messages, snapshot.messages
        )
        order = {message.id: index for index, message in enumerate(source.messages)}
        snapshot.messages.sort(key=lambda message: order[message.id])
        self.limits = (
            (manager.max_context_window_tokens, manager.max_context_images)
            if manager
            else None
        )
        logger.info(
            "cwm.epoch.rebase generation=%s reason=%s "
            "source_messages=%s selected_messages=%s",
            self.generation + 1,
            reason,
            len(source.messages),
            len(snapshot.messages),
        )
        self.session_id = source.id
        self.source_signatures = signatures
        self.selected_messages = copy.deepcopy(snapshot.messages)
        self.generation += 1
        return snapshot

    @staticmethod
    def _complete_tool_groups(
        source: list[Message], selected: list[Message]
    ) -> list[Message]:
        """Drop partial native tool exchanges instead of orphaning results."""
        groups: list[set[str]] = []
        owners: dict[str, set[str]] = {}
        for message in source:
            calls = message.metadata.get("tool_calls", [])
            if isinstance(calls, list) and calls:
                group = {message.id}
                groups.append(group)
                for call in calls:
                    if isinstance(call, dict) and call.get("id"):
                        owners[str(call["id"])] = group
            if message.role == "tool":
                group = owners.get(str(message.metadata.get("tool_call_id", "")))
                if group is not None:
                    group.add(message.id)
        kept = {message.id for message in selected}
        incomplete = set().union(*(group for group in groups if not group <= kept))
        return [message for message in selected if message.id not in incomplete]
