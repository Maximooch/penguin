"""Reconcile Responses reasoning deltas with completed snapshots."""

from __future__ import annotations

import logging
from typing import Any

__all__ = ["ResponsesReasoningStream"]

logger = logging.getLogger(__name__)


class ResponsesReasoningStream:
    """Track visible text per item and part for one provider stream."""

    def __init__(self) -> None:
        self._parts: dict[tuple[str, str, int], str] = {}
        self._item_ids: dict[int, str] = {}
        self._summary_lengths: dict[str, list[int]] = {}

    def consume(self, event: dict[str, Any]) -> str:
        """Return only text not already emitted by earlier deltas or snapshots."""
        event_type = event.get("type", "")
        if not isinstance(event_type, str):
            return ""
        if event_type == "response.completed":
            response = event.get("response")
            output = response.get("output") if isinstance(response, dict) else None
            if not isinstance(output, list):
                return ""
            return "".join(
                self.consume(
                    {
                        "type": "response.output_item.done",
                        "item": item,
                        "output_index": index,
                    }
                )
                for index, item in enumerate(output)
            )

        item = event.get("item")
        item = item if isinstance(item, dict) else {}
        if event_type in {"response.output_item.added", "response.output_item.done"}:
            if item.get("type") not in {"reasoning", "summary", "reasoning_summary"}:
                return ""
        output_index = event.get("output_index", 0)
        if type(output_index) is not int or output_index < 0:
            return ""
        item_id = event.get("item_id") or item.get("id")
        fallback_id = f"output:{output_index}"
        if isinstance(item_id, str) and item_id:
            self._item_ids[output_index] = item_id
            for key in list(self._parts):
                if key[0] == fallback_id:
                    self._parts[(item_id, *key[1:])] = self._parts.pop(key)
        else:
            item_id = self._item_ids.get(output_index, fallback_id)

        if event_type in {"response.output_item.added", "response.output_item.done"}:
            if event_type == "response.output_item.added":
                return ""
            summary = item.get("summary")
            if isinstance(summary, list):
                self._summary_lengths[item_id] = [
                    len(part["text"])
                    for part in summary
                    if isinstance(part, dict) and isinstance(part.get("text"), str)
                ]
            result = []
            for kind in ("summary", "content"):
                parts = item.get(kind)
                if not isinstance(parts, list):
                    continue
                for index, part in enumerate(parts):
                    if isinstance(part, dict):
                        result.append(
                            self._update(
                                item_id, kind, index, part.get("text"), snapshot=True
                            )
                        )
            return "".join(result)

        if event_type == "response.reasoning_summary_part.done":
            part = event.get("part")
            text = part.get("text") if isinstance(part, dict) else None
            return self._update(
                item_id, "summary", event.get("summary_index", 0), text, snapshot=True
            )

        if event_type in {
            "response.thinking.delta",
            "response.reasoning.delta",
            "response.reasoning_summary.delta",
            "response.reasoning_summary_text.delta",
            "response.reasoning_summary_text.done",
            "response.reasoning_text.delta",
            "response.reasoning_text.done",
        }:
            kind = (
                "content"
                if event_type.startswith("response.reasoning_text.")
                else "summary"
            )
            snapshot = event_type.endswith(".done")
            return self._update(
                item_id,
                kind,
                event.get(f"{kind}_index", 0),
                event.get("text" if snapshot else "delta"),
                snapshot=snapshot,
            )
        return ""

    def _update(
        self, item_id: str, kind: str, index: int, text: Any, *, snapshot: bool
    ) -> str:
        if not isinstance(text, str) or not text or type(index) is not int or index < 0:
            return ""
        key = (item_id, kind, index)
        previous = self._parts.get(key, "")
        if snapshot:
            if previous.startswith(text):
                return ""
            if not text.startswith(previous):
                # ponytail: callbacks append; replacing revised text needs UI edits.
                logger.warning(
                    "Responses reasoning snapshot revised emitted text (part=%s)",
                    index,
                )
                return ""
            self._parts[key] = text
            return text[len(previous) :]
        self._parts[key] = previous + text
        return text

    def summary_lengths(self) -> list[dict[str, Any]]:
        """Return identifiers and lengths only, without provider text or ciphertext."""
        return [
            {"item_id": item_id, "summary_chars": lengths}
            for item_id, lengths in self._summary_lengths.items()
        ]
