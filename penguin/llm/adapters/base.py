from abc import ABC, abstractmethod
from typing import Any, Callable, Dict, List, Optional, Tuple

from ..contracts import (
    FinishReason,
    LLMError,
    LLMPreparedRequest,
    LLMProviderCapabilities,
    LLMRequestLifecycle,
)


class BaseAdapter(ABC):
    """Base adapter interface for LLM providers"""

    @property
    @abstractmethod
    def provider(self) -> str:
        """Return the provider name"""
        pass

    @abstractmethod
    def format_messages(self, messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Format messages for the specific provider"""
        pass

    @abstractmethod
    def process_response(self, response: Any) -> Tuple[str, List[Any]]:
        """Process the raw model response into a standardized format"""
        pass

    @abstractmethod
    def count_tokens(self, content: Any) -> int:
        """
        Count tokens in the given text or structured content.

        Args:
            content: Text string or structured content to count tokens for

        Returns:
            Approximate token count
        """
        pass

    @abstractmethod
    async def create_completion(
        self,
        messages: List[Dict[str, Any]],
        max_output_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        stream: bool = False,
        stream_callback: Optional[Callable[[str], None]] = None,
        **kwargs: Any,
    ) -> Any:
        """Create a completion request with optional streaming"""
        pass

    @abstractmethod
    async def get_response(
        self,
        messages: List[Dict[str, Any]],
        max_output_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        stream: bool = False,
        stream_callback: Optional[Callable[[str], None]] = None,
        **kwargs: Any,
    ) -> str:
        """
        Get a response from the provider's LLM.

        Args:
            messages: List of message dictionaries (standard format).
            max_tokens: Max tokens for the response.
            temperature: Sampling temperature.
            stream: Whether to stream the response.
            stream_callback: Callback for streaming chunks.

        Returns:
            The complete response string.
        """
        pass

    def supports_system_messages(self) -> bool:
        """Whether this provider supports system messages"""
        return True

    def supports_vision(self) -> bool:
        """Whether this provider supports vision/images"""
        return False

    def get_last_usage(self) -> Dict[str, Any]:
        """Return normalized usage from the most recent request when available."""
        return {}

    def get_capabilities(self) -> LLMProviderCapabilities:
        """Return provider/model capability metadata for orchestration layers."""

        model_config = getattr(self, "model_config", None)
        return LLMProviderCapabilities(
            provider=self.provider,
            model=str(getattr(model_config, "model", "") or ""),
            streaming=bool(getattr(model_config, "streaming_enabled", True)),
            vision=self.supports_vision(),
            max_context_tokens=getattr(model_config, "max_context_window_tokens", None),
            max_output_tokens=getattr(model_config, "max_output_tokens", None),
        )

    async def prepare_request(
        self,
        messages: List[Dict[str, Any]],
        max_output_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        stream: bool = False,
        **kwargs: Any,
    ) -> LLMPreparedRequest:
        """Prepare a provider-native request without sending it."""

        legacy_max_tokens = kwargs.pop("max_tokens", None)
        if max_output_tokens is None and legacy_max_tokens is not None:
            max_output_tokens = legacy_max_tokens

        model_config = getattr(self, "model_config", None)
        body: Dict[str, Any] = {
            "model": str(getattr(model_config, "model", "") or ""),
            "messages": self.format_messages(messages),
            "stream": stream,
            **kwargs,
        }
        effective_max_tokens = max_output_tokens or getattr(
            model_config,
            "max_output_tokens",
            None,
        )
        if effective_max_tokens is not None:
            body["max_output_tokens"] = effective_max_tokens
        effective_temperature = (
            temperature
            if temperature is not None
            else getattr(model_config, "temperature", None)
        )
        if effective_temperature is not None:
            body["temperature"] = effective_temperature

        return LLMPreparedRequest(
            provider=self.provider,
            model=str(getattr(model_config, "model", "") or ""),
            protocol="generic_messages",
            route=f"{self.provider}.messages",
            body={key: value for key, value in body.items() if value is not None},
            transport="sdk_stream" if stream else "sdk",
            capabilities=self.get_capabilities(),
            diagnostics={
                "message_count": len(messages),
                "formatted_message_count": len(body.get("messages", [])),
            },
        )

    def has_pending_tool_call(self) -> bool:
        """Return whether a tool call is waiting to execute."""
        return False

    def get_and_clear_last_tool_call(self) -> Optional[Dict[str, Any]]:
        """Return the last captured tool call when supported by the provider."""
        return None

    def get_and_clear_pending_tool_calls(self) -> List[Dict[str, Any]]:
        """Return all captured tool calls when supported by the provider."""
        tool_call = self.get_and_clear_last_tool_call()
        return [tool_call] if isinstance(tool_call, dict) else []

    def get_last_error(self) -> Optional[LLMError]:
        """Return canonical error metadata from the latest request when available."""
        return None

    def get_last_request_lifecycle(self) -> Optional[LLMRequestLifecycle]:
        """Return lifecycle metadata from the latest provider request when available."""
        return None

    def get_last_finish_reason(self) -> FinishReason:
        """Return the canonical finish reason from the latest request."""
        return FinishReason.UNKNOWN

    def get_last_reasoning(self) -> str:
        """Return the latest accumulated reasoning text when available."""
        return ""
