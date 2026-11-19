"""Hide action tags from one channel of streamed text."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable

__all__ = ["ActionTagFilter"]


def _is_literal(text: str, open_index: int, end_index: int | None = None) -> bool:
    """Return whether a tag-looking token is escaped or quoted markdown."""
    if open_index > 0 and text[open_index - 1] in {"`", "\\"}:
        return True
    return end_index is not None and text[end_index + 1 : end_index + 2] == "`"


class ActionTagFilter:
    """Remove action tags and their bodies from streamed text.

    Text from an opening action tag onward is held back until its closing tag
    arrives, and then dropped with the tag. If the stream ends first,
    ``flush`` returns the held text: a tag that never closes, or a tag named
    in prose, hides nothing for good. Use one filter per stream channel.
    """

    def __init__(self, tags: Iterable[str]) -> None:
        self._tags = [tag.lower() for tag in tags]
        self.reset()

    def reset(self) -> None:
        """Forget any open tag and held text."""
        self._active: str | None = None
        self._held = ""
        self._buffer = ""

    def feed(self, text: str) -> str:
        """Return the part of ``text`` (and earlier held text) that is visible."""
        if not text or not self._tags:
            return text
        combined = self._buffer + text
        self._buffer = ""
        lowered = combined.lower()
        output: list[str] = []
        index = 0
        while index < len(combined):
            if self._active:
                close = f"</{self._active}>"
                close_index = lowered.find(close, index)
                if close_index == -1:
                    # Keep enough of the tail to see a close tag split across
                    # chunks; the rest is held.
                    split = max(index, len(combined) - (len(close) - 1))
                    self._held += combined[index:split]
                    self._buffer = combined[split:]
                    break
                self._active = None
                self._held = ""
                index = close_index + len(close)
                continue

            open_index = combined.find("<", index)
            if open_index == -1:
                output.append(combined[index:])
                break
            output.append(combined[index:open_index])
            end_index = combined.find(">", open_index + 1)
            if end_index == -1:
                fragment = lowered[open_index + 1 :]
                if fragment.startswith("/"):
                    fragment = fragment[1:]
                if not _is_literal(combined, open_index) and any(
                    tag.startswith(fragment) for tag in self._tags
                ):
                    self._buffer = combined[open_index:]
                else:
                    output.append(combined[open_index:])
                break

            token = lowered[open_index + 1 : end_index].strip()
            is_close = token.startswith("/")
            name = token[1:].strip() if is_close else token
            if name not in self._tags or _is_literal(combined, open_index, end_index):
                output.append(combined[open_index : end_index + 1])
            elif not is_close:
                self._active = name
                self._held = combined[open_index : end_index + 1]
            index = end_index + 1
        return "".join(output)

    def flush(self) -> str:
        """Return held text that never became a complete action, and reset."""
        text = self._held + self._buffer
        self.reset()
        return text
