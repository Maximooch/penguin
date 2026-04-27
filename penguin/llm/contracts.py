from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import (
    Any,
    Callable,
    Dict,
    List,
    Optional,
    Protocol,
    Union,
    runtime_checkable,
)


StreamCallback = Callable[[str, str], Any]


class FinishReason(str, Enum):
    """Canonical finish reasons across provider implementations."""

    STOP = "stop"
    LENGTH = "length"
    TOOL_CALLS = "tool_calls"
    CONTENT_FILTER = "content_filter"
    ERROR = "error"
    UNKNOWN = "unknown"


class StreamEventType(str, Enum):
    """Canonical internal stream event grammar."""

    TEXT_START = "text_start"
    TEXT_DELTA = "text_delta"
    TEXT_END = "text_end"
    REASONING_START = "reasoning_start"
    REASONING_DELTA = "reasoning_delta"
    REASONING_END = "reasoning_end"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    FINISH = "finish"
    ERROR = "error"


class ErrorCategory(str, Enum):
    """Canonical error categories for retries and diagnostics."""

    AUTH = "auth"
    RATE_LIMIT = "rate_limit"
    TIMEOUT = "timeout"
    NETWORK = "network"
    BAD_REQUEST = "bad_request"
    PROVIDER_UNAVAILABLE = "provider_unavailable"
    RUNTIME = "runtime"
    UNKNOWN = "unknown"


@dataclass
class LLMToolCall:
    """Canonical representation of one tool call emitted by a provider."""

    name: str
    arguments: str = ""
    call_id: Optional[str] = None
    item_id: Optional[str] = None
    provider_data: Dict[str, Any] = field(default_factory=dict)


@dataclass
class LLMUsage:
    """Canonical normalized token/cost usage payload."""

    input_tokens: int = 0
    output_tokens: int = 0
    reasoning_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    total_tokens: int = 0
    cost: float = 0.0
    provider_data: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.total_tokens <= 0:
            self.total_tokens = max(
                self.input_tokens + self.output_tokens + self.reasoning_tokens,
                0,
            )

    @classmethod
    def from_dict(cls, payload: Optional[Dict[str, Any]]) -> "LLMUsage":
        """Build normalized usage from a provider dict when available."""

        if not isinstance(payload, dict):
            return cls()

        def _to_int(key: str) -> int:
            try:
                return int(payload.get(key) or 0)
            except Exception:
                return 0

        def _to_float(key: str) -> float:
            try:
                return float(payload.get(key) or 0.0)
            except Exception:
                return 0.0

        return cls(
            input_tokens=_to_int("input_tokens"),
            output_tokens=_to_int("output_tokens"),
            reasoning_tokens=_to_int("reasoning_tokens"),
            cache_read_tokens=_to_int("cache_read_tokens"),
            cache_write_tokens=_to_int("cache_write_tokens"),
            total_tokens=_to_int("total_tokens"),
            cost=_to_float("cost"),
            provider_data=dict(payload),
        )

    def to_dict(self) -> Dict[str, Any]:
        """Return a provider-agnostic usage payload."""

        return {
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "reasoning_tokens": self.reasoning_tokens,
            "cache_read_tokens": self.cache_read_tokens,
            "cache_write_tokens": self.cache_write_tokens,
            "total_tokens": self.total_tokens,
            "cost": self.cost,
        }


@dataclass
class LLMError:
    """Canonical normalized error payload for provider/runtime failures."""

    message: str
    category: ErrorCategory = ErrorCategory.UNKNOWN
    retryable: bool = False
    retry_after_seconds: Optional[float] = None
    status_code: Optional[int] = None
    provider: Optional[str] = None
    model: Optional[str] = None
    finish_reason: Optional[FinishReason] = None
    provider_data: Dict[str, Any] = field(default_factory=dict)


class LLMProviderError(RuntimeError):
    """Structured provider/runtime failure that carries canonical error metadata."""

    def __init__(self, error: LLMError):
        super().__init__(error.message)
        self.error = error

    @property
    def category(self) -> ErrorCategory:
        return self.error.category

    @property
    def retryable(self) -> bool:
        return self.error.retryable

    @property
    def retry_after_seconds(self) -> Optional[float]:
        return self.error.retry_after_seconds

    @property
    def status_code(self) -> Optional[int]:
        return self.error.status_code

    @property
    def provider(self) -> Optional[str]:
        return self.error.provider

    @property
    def model(self) -> Optional[str]:
        return self.error.model

    @property
    def finish_reason(self) -> Optional[FinishReason]:
        return self.error.finish_reason


@dataclass
class LLMStreamEvent:
    """Canonical event emitted while assembling one model response."""

    type: StreamEventType
    text: str = ""
    message_type: str = "assistant"
    tool_call: Optional[LLMToolCall] = None
    finish_reason: Optional[FinishReason] = None
    usage: Optional[LLMUsage] = None
    error: Optional[LLMError] = None
    provider_data: Dict[str, Any] = field(default_factory=dict)


@dataclass
class LLMResult:
    """Canonical final result shape produced by one provider call."""

    text: str = ""
    reasoning: str = ""
    finish_reason: FinishReason = FinishReason.UNKNOWN
    usage: LLMUsage = field(default_factory=LLMUsage)
    tool_calls: List[LLMToolCall] = field(default_factory=list)
    provider_data: Dict[str, Any] = field(default_factory=dict)


@dataclass
class LLMRequest:
    """Provider-agnostic request shape for completions/streaming."""

    messages: List[Dict[str, Any]]
    max_output_tokens: Optional[int] = None
    temperature: Optional[float] = None
    stream: bool = False
    stream_callback: Optional[StreamCallback] = None
    tools: List[Dict[str, Any]] = field(default_factory=list)
    tool_choice: Optional[Union[str, Dict[str, Any]]] = None
    provider_options: Dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class ProviderRuntime(Protocol):
    """Minimal runtime interface existing handlers should converge on."""

    provider: str

    async def get_response(
        self,
        messages: List[Dict[str, Any]],
        max_output_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        stream: bool = False,
        stream_callback: Optional[StreamCallback] = None,
        **kwargs: Any,
    ) -> str: ...

    def count_tokens(self, content: Union[str, List[Any], Dict[str, Any]]) -> int: ...


@runtime_checkable
class UsageReportingRuntime(Protocol):
    """Optional runtime extension for normalized usage access."""

    def get_last_usage(self) -> Dict[str, Any]: ...


@runtime_checkable
class ToolCallRuntime(Protocol):
    """Optional runtime extension for tool-call interrupts."""

    def has_pending_tool_call(self) -> bool: ...

    def get_and_clear_last_tool_call(self) -> Optional[Dict[str, Any]]: ...

    def get_and_clear_pending_tool_calls(self) -> List[Dict[str, Any]]: ...


@runtime_checkable
class ErrorReportingRuntime(Protocol):
    """Optional runtime extension for canonical error reporting."""

    def get_last_error(self) -> Optional[LLMError]: ...


@runtime_checkable
class ResultMetadataRuntime(Protocol):
    """Optional runtime extension for normalized finish/reasoning state."""

    def get_last_finish_reason(self) -> FinishReason: ...

    def get_last_reasoning(self) -> str: ...


__all__ = [
    "ErrorCategory",
    "ErrorReportingRuntime",
    "FinishReason",
    "LLMError",
    "LLMProviderError",
    "LLMRequest",
    "LLMResult",
    "LLMStreamEvent",
    "LLMToolCall",
    "LLMUsage",
    "ProviderRuntime",
    "ResultMetadataRuntime",
    "StreamCallback",
    "StreamEventType",
    "ToolCallRuntime",
    "UsageReportingRuntime",
]
