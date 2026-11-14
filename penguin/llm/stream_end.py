"""One decision for how a provider stream ended.

Every streaming adapter reaches the end of its event loop holding the same
facts: whether it was cancelled, whether the provider reported an error,
whether the provider's terminal marker arrived, whether the provider cut the
output short, whether a tool call is waiting, and whether any text arrived.
``classify_stream_end`` turns those facts into one outcome so the adapters
cannot disagree about which fact wins.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Optional

from penguin.llm.contracts import FinishReason

__all__ = [
    "StreamEnd",
    "classify_stream_end",
    "finish_reason_for",
    "is_stream_failure",
    "keeps_tool_calls",
    "responses_incomplete_reason",
    "stream_output_state",
]


class StreamEnd(str, Enum):
    """How a provider stream ended, in priority order."""

    CANCELLED = "cancelled"
    PROVIDER_ERROR = "provider_error"
    INCOMPLETE = "incomplete"
    TRUNCATED = "truncated"
    FILTERED = "filtered"
    TOOL_CALLS = "tool_calls"
    TEXT = "text"
    EMPTY = "empty"


def classify_stream_end(
    *,
    saw_terminal: bool,
    pending_tool: bool,
    has_text: bool,
    cancelled: bool = False,
    saw_error: bool = False,
    stopped_early: Optional[FinishReason] = None,
) -> StreamEnd:
    """Classify the end of a provider stream.

    Args:
        saw_terminal: The provider's own end marker arrived (for example
            ``response.completed``, ``message_stop`` or a ``finish_reason``).
        pending_tool: A tool call is waiting to be executed.
        has_text: Assistant text was received.
        cancelled: The request was cancelled by the caller.
        saw_error: The provider reported an error during the stream.
        stopped_early: ``FinishReason.LENGTH`` or
            ``FinishReason.CONTENT_FILTER`` when the provider ended the output
            before the model finished; otherwise ``None``.

    Returns:
        The single outcome. A failure always wins over a waiting tool call,
        because a tool call from a failed or cut-off stream may be partial.
    """
    if cancelled:
        return StreamEnd.CANCELLED
    if saw_error:
        return StreamEnd.PROVIDER_ERROR
    if not saw_terminal:
        return StreamEnd.INCOMPLETE
    if stopped_early is FinishReason.CONTENT_FILTER:
        return StreamEnd.FILTERED
    if stopped_early is FinishReason.LENGTH:
        return StreamEnd.TRUNCATED
    if pending_tool:
        return StreamEnd.TOOL_CALLS
    if has_text:
        return StreamEnd.TEXT
    return StreamEnd.EMPTY


_FINISH_REASONS: dict[StreamEnd, FinishReason] = {
    StreamEnd.CANCELLED: FinishReason.ERROR,
    StreamEnd.PROVIDER_ERROR: FinishReason.ERROR,
    StreamEnd.INCOMPLETE: FinishReason.ERROR,
    StreamEnd.TRUNCATED: FinishReason.LENGTH,
    StreamEnd.FILTERED: FinishReason.CONTENT_FILTER,
    StreamEnd.TOOL_CALLS: FinishReason.TOOL_CALLS,
    StreamEnd.TEXT: FinishReason.STOP,
    StreamEnd.EMPTY: FinishReason.STOP,
}


def finish_reason_for(end: StreamEnd) -> FinishReason:
    """Return the canonical finish reason for a stream outcome."""
    return _FINISH_REASONS[end]


def is_stream_failure(end: StreamEnd) -> bool:
    """Return whether the outcome is a failed request, not a model answer."""
    return end in {
        StreamEnd.CANCELLED,
        StreamEnd.PROVIDER_ERROR,
        StreamEnd.INCOMPLETE,
    }


def keeps_tool_calls(end: StreamEnd) -> bool:
    """Return whether tool calls gathered during the stream may be executed."""
    return end is StreamEnd.TOOL_CALLS


def stream_output_state(*, pending_tool: bool, has_text: bool) -> str:
    """Describe what a stream had produced, for diagnostics."""
    if pending_tool:
        return "tool_call"
    return "text" if has_text else "empty"


def responses_incomplete_reason(response: Any) -> FinishReason:
    """Map a Responses API ``response.incomplete`` payload to a finish reason.

    Args:
        response: The ``response`` object of the event, as a dict or SDK model.

    Returns:
        ``CONTENT_FILTER`` when the provider says so, otherwise ``LENGTH``:
        an incomplete response is output that was cut short.
    """
    details = (
        response.get("incomplete_details")
        if isinstance(response, dict)
        else getattr(response, "incomplete_details", None)
    )
    reason = (
        details.get("reason")
        if isinstance(details, dict)
        else getattr(details, "reason", None)
    )
    if reason == "content_filter":
        return FinishReason.CONTENT_FILTER
    return FinishReason.LENGTH
