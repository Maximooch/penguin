from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Tuple, AsyncIterator, Callable, Union

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
    def count_tokens(self, text: str) -> int:
        """
        Count tokens in the given text or structured content.
        
        Args:
            text: Text string or structured content to count tokens for
            
        Returns:
            Approximate token count
        """
        pass
    
    @abstractmethod
    async def create_completion(
        self,
        messages: List[Dict[str, Any]],
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        stream: bool = False,
        stream_callback: Optional[Callable[[str], None]] = None
    ) -> Any:
        """Create a completion request with optional streaming"""
        pass
    
    @abstractmethod
    async def get_response(
        self,
        messages: List[Dict[str, Any]],
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        stream: bool = False,
        stream_callback: Optional[Callable[[str], None]] = None,
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