"""Gather streamed provider tool calls with one promotion rule.

A provider streams a tool call in pieces: a start with a name and id, argument
fragments, then an end. ``ToolCallAccumulator`` keeps calls that are still
streaming apart from calls that are complete. The rule every adapter follows:

- A call becomes pending (runnable) only when it is closed: its own end event
  arrived, or the whole stream ended cleanly and ``close_all`` was called.
- A pending call is merged with another only when they share a ``call_id`` or
  ``item_id``. Calls without ids are never merged, even when identical.
- A call without a name is never pending.
- ``discard`` drops everything, for a stream that failed.
"""

from __future__ import annotations

from collections.abc import Hashable
from typing import Any, Optional

__all__ = ["ToolCallAccumulator"]

_FIELDS = ("item_id", "call_id", "name", "arguments")


def _text(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


class ToolCallAccumulator:
    """Open (streaming) and pending (complete) tool calls for one request."""

    def __init__(self) -> None:
        self._open: dict[Hashable, dict[str, Any]] = {}
        self._pending: list[dict[str, Any]] = []

    # --- streaming --------------------------------------------------------

    def open_call(
        self,
        key: Hashable,
        *,
        call_id: Any = None,
        item_id: Any = None,
        name: Any = None,
        arguments: Optional[str] = None,
    ) -> None:
        """Start a streamed call, or fill in fields of one already started."""
        call = self._open.setdefault(
            key, {"item_id": None, "call_id": None, "name": None, "arguments": ""}
        )
        for field, value in (("call_id", call_id), ("item_id", item_id)):
            if _text(value):
                call[field] = _text(value)
        if _text(name):
            call["name"] = _text(name)
        if isinstance(arguments, str) and arguments and not call["arguments"]:
            call["arguments"] = arguments

    def append_arguments(self, key: Hashable, delta: Any) -> None:
        """Append an argument fragment to a streamed call."""
        if not isinstance(delta, str) or not delta:
            return
        self.open_call(key)
        self._open[key]["arguments"] += delta

    def close_call(
        self,
        key: Hashable,
        *,
        arguments: Optional[str] = None,
        **fields: Any,
    ) -> Optional[dict[str, Any]]:
        """End a streamed call and make it pending.

        Args:
            key: The key the call was opened with.
            arguments: The provider's final arguments, replacing the streamed
                fragments when given.
            **fields: ``call_id``, ``item_id`` or ``name`` from the end event.

        Returns:
            The pending call, or ``None`` when it has no name.
        """
        self.open_call(key, **fields)
        call = self._open.pop(key)
        if isinstance(arguments, str):
            call["arguments"] = arguments
        return self.add(call)

    def close_all(self) -> None:
        """End every streamed call, in the order they were opened."""
        for key in list(self._open):
            self.close_call(key)

    # --- complete calls ---------------------------------------------------

    def add(self, call: dict[str, Any]) -> Optional[dict[str, Any]]:
        """Record a complete call, merging it with a pending call of the same id.

        Returns:
            The pending call, or ``None`` when it has no name.
        """
        incoming = {
            "item_id": _text(call.get("item_id")),
            "call_id": _text(call.get("call_id")),
            "name": _text(call.get("name")),
            "arguments": str(call.get("arguments") or ""),
        }
        for pending in self._pending:
            if any(
                incoming[field] and incoming[field] == pending[field]
                for field in ("call_id", "item_id")
            ):
                for field in _FIELDS:
                    if incoming[field]:
                        pending[field] = incoming[field]
                return pending
        if not incoming["name"]:
            return None
        self._pending.append(incoming)
        return incoming

    # --- reading ----------------------------------------------------------

    def has_open(self) -> bool:
        """Return whether a call is still streaming."""
        return bool(self._open)

    def is_open(self, key: Hashable) -> bool:
        """Return whether the call opened with ``key`` is still streaming."""
        return key in self._open

    def open_keys(self) -> list[Hashable]:
        """Return the keys of calls still streaming, in the order opened."""
        return list(self._open)

    def has_pending(self) -> bool:
        """Return whether a complete call is waiting to run."""
        return bool(self._pending)

    @property
    def last(self) -> Optional[dict[str, Any]]:
        """The most recently recorded pending call."""
        return self._pending[-1] if self._pending else None

    def drain(self) -> list[dict[str, Any]]:
        """Return the pending calls as copies and clear all state."""
        calls = [dict(call) for call in self._pending]
        self.discard()
        return calls

    def discard(self) -> None:
        """Drop open and pending calls."""
        self._open.clear()
        self._pending.clear()
