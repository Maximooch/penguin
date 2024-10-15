from abc import ABC, abstractmethod
from typing import List, Dict, Any
from utils.diagnostics import diagnostics
from litellm import completion
# from litellm import get_assistants, create_thread, add_message, run_thread
import time
# from .openai_assistant import OpenAIAssistantManager
from .model_config import ModelConfig

class ProviderAdapter(ABC):
    @abstractmethod
    def format_messages(self, messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        pass

    @abstractmethod
    def process_response(self, response: Any) -> tuple[str, List[Any]]:
        pass

    def supports_conversation_id(self) -> bool:
        return False

    def format_messages_with_id(self, conversation_id: str, message: Dict[str, Any]) -> List[Dict[str, Any]]:
        raise NotImplementedError("This adapter does not support conversation IDs")

    def get_conversation_id(self, response: Any) -> str:
        raise NotImplementedError("This adapter does not support conversation IDs")

    def count_tokens(self, text: str) -> int:
        return diagnostics.count_tokens(text)

class OpenAIAdapter(ProviderAdapter):
    def __init__(self, model_config: ModelConfig):
        self.model_config = model_config

    def format_messages(self, messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        return messages  # For now, just return the messages as-is

    def process_response(self, response: Any) -> tuple[str, List[Any]]:
        # Assume response is in the standard OpenAI format
        return response['choices'][0]['message']['content'], []

    # Commented out assistant/threads support methods
    """
    def initialize_assistant(self):
        pass

    def create_thread(self):
        pass

    def add_message_to_thread(self, content: str):
        pass

    def run_assistant(self):
        pass

    def get_assistant_response(self):
        pass
    """

class LiteLLMAdapter(ProviderAdapter):
    def format_messages(self, messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        return [{**msg, 'content': str(msg['content'])} for msg in messages]

    def process_response(self, response: Any) -> tuple[str, List[Any]]:
        if isinstance(response, dict) and 'choices' in response:
            return response['choices'][0]['message']['content'], []
        elif hasattr(response, 'choices') and len(response.choices) > 0:
            return response.choices[0].message.content, []
        elif isinstance(response, str):
            return response, []
        else:
            raise AttributeError(f"Unexpected response structure from LiteLLM API: {response}")

class AnthropicAdapter(ProviderAdapter):
    def format_messages(self, messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        # Anthropic uses a different format, so we need to convert
        formatted_messages = []
        for msg in messages:
            if msg['role'] == 'system':
                formatted_messages.append({"role": "human", "content": f"System: {msg['content']}"})
            else:
                formatted_messages.append(msg)
        return formatted_messages

    def process_response(self, response: Any) -> tuple[str, List[Any]]:
        # Assume response is in the Anthropic format
        return response['completion'], []

class OllamaAdapter(ProviderAdapter):
    def format_messages(self, messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        # Ollama uses a simple format, so we can just return the messages as-is
        return messages

    def process_response(self, response: Any) -> tuple[str, List[Any]]:
        # Assume response is in the Ollama format
        return response['message']['content'], []

def get_provider_adapter(provider: str, model_config: ModelConfig) -> ProviderAdapter:
    adapters = {
        "openai": OpenAIAdapter(model_config),
        "litellm": LiteLLMAdapter(),
        "anthropic": AnthropicAdapter(),
        "ollama": OllamaAdapter(),
    }
    return adapters.get(provider.lower(), LiteLLMAdapter())  # Default to LiteLLMAdapter if provider not found