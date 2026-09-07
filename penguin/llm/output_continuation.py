"""Preserve provider output boundaries without ending semantic work."""

from typing import Any

from penguin.llm.contracts import FinishReason, LLMRequestLifecycle
from penguin.llm.provider_transform import normalize_finish_reason
from penguin.system.state import MessageCategory

__all__ = ["provider_finish_reason", "queue_output_continuation"]


def provider_finish_reason(api_client: Any) -> FinishReason:
    """Read the typed result of the latest provider attempt."""
    getter = getattr(api_client, "get_last_request_lifecycle", None)
    result = getter() if callable(getter) else None
    if isinstance(result, LLMRequestLifecycle) and result.finish_reason is not None:
        return normalize_finish_reason(result.finish_reason)
    handler = getattr(api_client, "client_handler", api_client)
    getter = getattr(handler, "get_last_finish_reason", None)
    if callable(getter):
        return normalize_finish_reason(getter())
    return FinishReason.UNKNOWN


def queue_output_continuation(conversation: Any) -> None:
    """Continue from the existing partial without inserting it a second time."""
    conversation.add_message(
        role="system",
        content=(
            "The previous assistant output reached a per-call output boundary. "
            "Continue exactly where it stopped without repeating any prior text."
        ),
        category=MessageCategory.SYSTEM_OUTPUT,
        metadata={"type": "output_boundary_continuation"},
        message_type="status",
    )
