from abc import ABC, abstractmethod
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

from ..contracts import FinishReason, LLMError


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

    def get_last_finish_reason(self) -> FinishReason:
        """Return the canonical finish reason from the latest request."""
        return FinishReason.UNKNOWN

    def get_last_reasoning(self) -> str:
        """Return the latest accumulated reasoning text when available."""
        return ""
