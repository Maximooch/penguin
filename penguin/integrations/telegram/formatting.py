"""Pure Telegram text formatting and streaming helpers."""

from __future__ import annotations

import html
import re
from dataclasses import dataclass, field

TELEGRAM_TEXT_LIMIT = 4000

_FENCED_CODE = re.compile(r"```(?:[A-Za-z0-9_+.-]+\n)?(.*?)```", re.DOTALL)
_INLINE_CODE = re.compile(r"`([^`\n]*)`")
_LINK = re.compile(r"\[([^\]\n]+)\]\((https?://[^\s)]+)\)")


def utf16_length(text: str) -> int:
    """Return Telegram's UTF-16 code-unit length for text."""
    return len(text.encode("utf-16-le", errors="surrogatepass")) // 2


def split_text(text: str, limit: int = TELEGRAM_TEXT_LIMIT) -> list[str]:
    """Split text without losing content, keeping each chunk within ``limit``."""
    if limit < 1:
        raise ValueError("limit must be positive")
    if not text:
        return []

    chunks: list[str] = []
    remaining = text
    while remaining:
        end = _utf16_prefix_end(remaining, limit)
        if end == 0:
            raise ValueError("limit is smaller than one Unicode character")
        if end == len(remaining):
            chunks.append(remaining)
            break

        candidate = remaining[:end]
        newline = candidate.rfind("\n")
        space = candidate.rfind(" ")
        preferred = max(newline, space)
        if preferred >= end // 2:
            end = preferred + 1
        chunks.append(remaining[:end])
        remaining = remaining[end:]
    return chunks


def render_html(markdown: str) -> str:
    """Render a small, safe Markdown subset as Telegram HTML."""
    if not markdown:
        return ""

    marker = "\ue000"
    while marker in markdown:
        marker += "\ue000"
    protected: list[str] = []

    def stash(value: str) -> str:
        token = f"{marker}{len(protected)}{marker}"
        protected.append(value)
        return token

    text = _FENCED_CODE.sub(
        lambda match: stash(
            f"<pre><code>{html.escape(match.group(1), quote=False)}</code></pre>"
        ),
        markdown,
    )
    text = _INLINE_CODE.sub(
        lambda match: stash(f"<code>{html.escape(match.group(1), quote=False)}</code>"),
        text,
    )
    text = _LINK.sub(
        lambda match: stash(
            f'<a href="{html.escape(match.group(2), quote=True)}">'
            f"{html.escape(match.group(1), quote=False)}</a>"
        ),
        text,
    )

    text = html.escape(text, quote=False)
    text = re.sub(r"(?m)^#{1,6}[ \t]+(.+)$", r"<b>\1</b>", text)
    text = re.sub(r"\*\*([^*\n]+)\*\*", r"<b>\1</b>", text)
    text = re.sub(r"__([^_\n]+)__", r"<b>\1</b>", text)
    text = re.sub(r"~~([^~\n]+)~~", r"<s>\1</s>", text)
    text = re.sub(r"(?<!\*)\*([^*\n]+)\*(?!\*)", r"<i>\1</i>", text)

    for index, value in enumerate(protected):
        text = text.replace(f"{marker}{index}{marker}", value)
    return text


def plain_text(markdown: str) -> str:
    """Return a clean plain-text fallback for the supported Markdown subset."""
    text = _FENCED_CODE.sub(lambda match: match.group(1), markdown)
    text = _INLINE_CODE.sub(lambda match: match.group(1), text)
    text = _LINK.sub(lambda match: match.group(1), text)
    text = re.sub(r"(?m)^#{1,6}[ \t]+", "", text)
    text = re.sub(r"\*\*([^*\n]+)\*\*", r"\1", text)
    text = re.sub(r"__([^_\n]+)__", r"\1", text)
    text = re.sub(r"~~([^~\n]+)~~", r"\1", text)
    return re.sub(r"(?<!\*)\*([^*\n]+)\*(?!\*)", r"\1", text)


def html_chunks(markdown: str, limit: int = TELEGRAM_TEXT_LIMIT) -> list[str]:
    """Render independently valid HTML chunks under Telegram's length limit."""
    return [rendered for rendered, _fallback in formatted_chunks(markdown, limit)]


def formatted_chunks(
    markdown: str, limit: int = TELEGRAM_TEXT_LIMIT
) -> list[tuple[str, str]]:
    """Return aligned HTML and plain-text chunks for delivery fallback."""
    if limit < 16:
        raise ValueError("HTML chunk limit must be at least 16")

    pending = split_text(markdown, limit)
    chunks: list[tuple[str, str]] = []
    while pending:
        source = pending.pop(0)
        rendered = render_html(source)
        fallback = plain_text(source)
        if utf16_length(rendered) <= limit and utf16_length(fallback) <= limit:
            chunks.append((rendered, fallback))
            continue
        half = max(1, utf16_length(source) // 2)
        parts = split_text(source, half)
        if len(parts) == 1:
            raise ValueError("text cannot be represented within the HTML limit")
        pending[0:0] = parts
    return chunks


def plain_chunks(markdown: str, limit: int = TELEGRAM_TEXT_LIMIT) -> list[str]:
    """Return plain fallback chunks under Telegram's length limit."""
    return split_text(plain_text(markdown), limit)


@dataclass
class StreamingCoalescer:
    """Coalesce streaming deltas and expose deterministic throttled previews."""

    interval_seconds: float = 0.75
    _text: str = field(default="", init=False, repr=False)
    _last_emitted: str = field(default="", init=False, repr=False)
    _last_emit_at: float | None = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        if self.interval_seconds <= 0:
            raise ValueError("interval_seconds must be positive")

    @property
    def text(self) -> str:
        """Return all content received so far."""
        return self._text

    @property
    def has_pending(self) -> bool:
        """Return whether the latest content has not been emitted."""
        return self._text != self._last_emitted

    def push(self, delta: str) -> None:
        """Append a stream delta."""
        self._text += delta

    def take(self, now: float, *, force: bool = False) -> str | None:
        """Return the latest cumulative preview when due, otherwise ``None``."""
        if not self.has_pending:
            return None
        if (
            not force
            and self._last_emit_at is not None
            and now - self._last_emit_at < self.interval_seconds
        ):
            return None
        self._last_emitted = self._text
        self._last_emit_at = now
        return self._text


def _utf16_prefix_end(text: str, limit: int) -> int:
    units = 0
    for index, char in enumerate(text):
        char_units = utf16_length(char)
        if units + char_units > limit:
            return index
        units += char_units
    return len(text)


__all__ = [
    "TELEGRAM_TEXT_LIMIT",
    "StreamingCoalescer",
    "formatted_chunks",
    "html_chunks",
    "plain_chunks",
    "plain_text",
    "render_html",
    "split_text",
    "utf16_length",
]
