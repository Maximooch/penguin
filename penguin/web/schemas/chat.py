"""Chat request, continuation, and terminal response schemas."""

# Optional is intentional while Penguin advertises Python 3.9 support.
# ruff: noqa: UP007

from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

try:
    from pydantic import ConfigDict, model_validator

    _PYDANTIC_V2 = hasattr(BaseModel, "model_validate")
except ImportError:  # pragma: no cover - exercised on Pydantic v1 installs
    from pydantic import root_validator

    _PYDANTIC_V2 = False

__all__ = [
    "ChatContinuationRequest",
    "ChatMessageRequest",
    "ChatTerminalResponse",
    "ChatToolBoundaryRequest",
    "validate_chat_continuation_controls",
]


_CONTINUATION_REQUEST_FIELDS = frozenset(
    {
        "session_id",
        "continuation",
        "directory",
        "model",
        "agent_id",
        "agent_mode",
        "variant",
        "service_tier",
    }
)


def validate_chat_continuation_controls(value: Any) -> None:
    """Reject request controls outside the server-issued continuation body.

    A continuation is an exact, one-shot capability rather than a new user
    prompt.  Its execution identity is validated against the durable marker,
    and client-controlled input such as iteration budgets, context, files, and
    message IDs must not alter the resumed turn.
    """

    if not isinstance(value, dict) or value.get("continuation") is None:
        return
    unexpected = sorted(
        key for key in value if key not in _CONTINUATION_REQUEST_FIELDS
    )
    if unexpected:
        raise ValueError(
            "exact continuation requests cannot include client controls: "
            + ", ".join(unexpected)
        )


class ChatToolBoundaryRequest(BaseModel):
    """Fingerprint of tool effects completed before a continuation boundary."""

    completed_action_count: int = Field(ge=0)
    fingerprint: str = Field(min_length=1)


class ChatContinuationRequest(BaseModel):
    """One exact, one-shot continuation of a durable terminal generation."""

    action: Literal["retry", "resume"]
    previous_status: str = Field(min_length=1)
    request_id: str = Field(min_length=1)
    generation: int = Field(gt=0)
    tool_boundary: ChatToolBoundaryRequest


class ChatMessageRequest(BaseModel):
    """Input accepted by the REST chat endpoint."""

    text: str = ""
    conversation_id: Optional[str] = None
    session_id: Optional[str] = None
    client_message_id: Optional[str] = None
    client_part_id: Optional[str] = None
    context: Optional[dict[str, Any]] = None
    context_files: Optional[list[str]] = None
    streaming: Optional[bool] = True
    max_iterations: Optional[int] = Field(default=None, ge=1)
    image_paths: Optional[list[str]] = None
    include_reasoning: Optional[bool] = False
    agent_id: Optional[str] = None
    agent_mode: Optional[str] = None
    directory: Optional[str] = None
    model: Optional[str] = None
    variant: Optional[str] = None
    service_tier: Optional[str] = None
    parts: Optional[list[dict[str, Any]]] = None
    continuation: Optional[ChatContinuationRequest] = None

    if _PYDANTIC_V2:

        @model_validator(mode="before")
        @classmethod
        def _reject_continuation_controls_v2(cls, value: Any) -> Any:
            validate_chat_continuation_controls(value)
            return value

        @model_validator(mode="after")
        def _require_text_or_continuation_v2(self) -> ChatMessageRequest:
            if not self.text.strip() and self.continuation is None:
                raise ValueError("text or continuation is required")
            if self.continuation is not None and not self.session_id:
                raise ValueError("session_id is required for continuation")
            return self

    else:

        @root_validator(pre=True)
        def _reject_continuation_controls_v1(
            cls,
            values: dict[str, Any],
        ) -> dict[str, Any]:
            validate_chat_continuation_controls(values)
            return values

        @root_validator(skip_on_failure=True)
        def _require_text_or_continuation_v1(
            cls,
            values: dict[str, Any],
        ) -> dict[str, Any]:
            text = values.get("text")
            continuation = values.get("continuation")
            if not (isinstance(text, str) and text.strip()) and continuation is None:
                raise ValueError("text or continuation is required")
            if continuation is not None and not values.get("session_id"):
                raise ValueError("session_id is required for continuation")
            return values


class ChatTerminalResponse(BaseModel):
    """Transport-independent truth about how a chat request terminated."""

    response: str
    partial_response: str
    action_results: list[Any]
    action_count: int
    status: str
    terminal_reason: str
    state: str
    completed: bool
    recoverable: bool
    aborted: bool
    cancelled: bool
    iterations: Optional[int] = None
    error: Any = None
    continuation: Optional[dict[str, Any]] = None
    actions: list[dict[str, Any]] = Field(default_factory=list)
    reasoning: Optional[str] = None
    reasoning_note: Optional[str] = None
    runtime_diagnostics: Optional[dict[str, Any]] = None

    if _PYDANTIC_V2:
        model_config = ConfigDict(extra="allow")
    else:

        class Config:
            extra = "allow"
