from abc import ABC, abstractmethod
from typing import List, Dict, Any
from utils.diagnostics import diagnostics
from litellm import completion, get_assistants, create_thread, add_message, run_thread
import time

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

class LiteLLMAdapter(ProviderAdapter):
    def format_messages(self, messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        return [{**msg, 'content': str(msg['content'])} for msg in messages]

    def process_response(self, response: Any) -> tuple[Any, List[Any]]:
        # Return the full response structure
        return response, []
    
    def supports_conversation_id(self) -> bool:
        return False

class OpenAIAdapter(ProviderAdapter):
    def __init__(self):
        self.thread_id = None
        self.assistant_id = None
        self._initialize_assistant()

    def _initialize_assistant(self):
        assistants = get_assistants(custom_llm_provider="openai")
        if assistants.data:
            self.assistant_id = assistants.data[0].id
        else:
            # Create a new assistant if none exists
            timestamp = int(time.time())
            assistant_name = f"Penguin-{timestamp}-Assistant"
            assistant = create_assistant(
                custom_llm_provider="openai",
                model="gpt-4-turbo",
                instructions="You are a helpful AI assistant.",
                name=assistant_name,
            )
            self.assistant_id = assistant.id

    def supports_conversation_id(self) -> bool:
        return True

    def format_messages(self, messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        if not self.thread_id:
            thread = create_thread(custom_llm_provider="openai")
            self.thread_id = thread.id

        for message in messages:
            add_message(thread_id=self.thread_id, custom_llm_provider="openai", **message)

        return messages

    def format_messages_with_id(self, conversation_id: str, message: Dict[str, Any]) -> List[Dict[str, Any]]:
        self.thread_id = conversation_id
        add_message(thread_id=self.thread_id, custom_llm_provider="openai", **message)
        return [message]

    def process_response(self, response: Any) -> tuple[Any, List[Any]]:
        run = run_thread(custom_llm_provider="openai", thread_id=self.thread_id, assistant_id=self.assistant_id)
        return run.response, []

    def get_conversation_id(self, response: Any) -> str:
        return self.thread_id

def get_provider_adapter(provider: str) -> ProviderAdapter:
    adapters = {
        "litellm": LiteLLMAdapter(),
        "openai": OpenAIAdapter(),
        # Add more adapters as needed
    }
    return adapters.get(provider.lower(), LiteLLMAdapter())  # Default to LiteLLMAdapter if provider not found
    # TODO: Add more adapters as needed
    # TODO: Add a way to dynamically load these adapters from a config file
    # TODO: Default to ollama if provider is not found
