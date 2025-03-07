import abc
import logging
import os
from typing import Any, Dict, List, Optional, Callable
from .model_config import ModelConfig

class ProviderAdapter(abc.ABC):
    def __init__(self, model_config: ModelConfig):
        self.model_config = model_config
        self.logger = logging.getLogger(__name__)

    @abc.abstractmethod
    def format_messages(self, messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Format messages for provider-specific API"""
        pass

    @abc.abstractmethod
    def process_response(self, response: Any) -> tuple[str, List[Any]]:
        """Process raw API response into standardized format"""
        pass

    @abc.abstractmethod
    async def create_completion(
        self,
        messages: List[Dict[str, Any]],
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        stream_callback: Optional[Callable[[str], None]] = None
    ) -> Any:
        """Execute actual API call"""
        pass

    @property
    @abc.abstractmethod
    def provider(self) -> str:
        """Return provider identifier string"""
        pass

    def supports_conversation_id(self) -> bool:
        """Whether provider supports conversation IDs"""
        return False

    def format_messages_with_id(
        self, conversation_id: str, message: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """Format messages with conversation ID"""
        raise NotImplementedError("Conversation IDs not supported by this provider")

    def get_conversation_id(self, response: Any) -> str:
        """Extract conversation ID from response"""
        raise NotImplementedError("Conversation IDs not supported by this provider")

    def count_tokens(self, text: str) -> int:
        """Count tokens using provider's tokenizer"""
        # Default implementation using basic word count
        return len(text.split())

    def supports_system_messages(self) -> bool:
        """Whether provider natively supports system messages"""
        return True

    def validate_environment(self):
        """Validate required environment variables"""
        if not os.getenv(f"{self.provider.upper()}_API_KEY"):
            raise EnvironmentError(
                f"Missing required environment variable: {self.provider.upper()}_API_KEY"
            ) 