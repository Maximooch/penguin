from abc import ABC, abstractmethod
from typing import List, Dict, Any
from utils.diagnostics import diagnostics
from litellm import completion 
import time
from .openai_assistant import OpenAIAssistantManager
from .model_config import ModelConfig
import logging

class ProviderAdapter(ABC):
    def __init__(self, model_config: ModelConfig):
        self.model_config = model_config

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

#TODO: implement streaming abstraction

class OpenAIAdapter(ProviderAdapter):
    def format_messages(self, messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        formatted_messages = []
        for message in messages:
            content = message.get('content', '')
            
            # Handle list-type content (like image messages)
            if isinstance(content, list):
                # Ensure each content part has proper format
                formatted_content = []
                for part in content:
                    if isinstance(part, dict):
                        if 'image_url' in part:
                            # Ensure image_url format is consistent
                            formatted_content.append({
                                "type": "image_url",
                                "image_url": {
                                    "url": part['image_url']['url']
                                }
                            })
                        else:
                            formatted_content.append(part)
                    else:
                        formatted_content.append({
                            "type": "text",
                            "text": str(part)
                        })
                formatted_messages.append({
                    "role": message['role'],
                    "content": formatted_content
                })
            else:
                # Handle string content
                formatted_messages.append({
                    "role": message['role'],
                    "content": [{"type": "text", "text": str(content)}]
                })
        
        return formatted_messages

    def process_response(self, response: Any) -> tuple[str, List[Any]]:
        if self.model_config.use_assistants_api:
            return response, []
        else:
            return response['choices'][0]['message']['content'], []

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
        formatted_messages = []
        for message in messages:
            content = message.get('content', '')
            
            # Convert list-type content to string
            if isinstance(content, list):
                text_parts = []
                for part in content:
                    if isinstance(part, dict):
                        if part.get('type') == 'text':
                            text_parts.append(part.get('text', ''))
                        elif part.get('type') == 'image_url':
                            # Handle image URLs according to Anthropic's format
                            text_parts.append(f"[Image: {part.get('image_url', {}).get('url', '')}]")
                content = ' '.join(text_parts)
            elif isinstance(content, dict):
                content = str(content)
                
            formatted_messages.append({
                'role': message.get('role', 'user'),
                'content': content  # Anthropic expects a simple string
            })
        
        return formatted_messages

    def process_response(self, response: Any) -> tuple[str, List[Any]]:
        if isinstance(response, dict):
            return response.get('content', ''), []
        return str(response), []

class OllamaAdapter(ProviderAdapter):
    def format_messages(self, messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        # Ollama's LLaVA models accept the same format as OpenAI
        return messages

    def process_response(self, response: Any) -> tuple[str, List[Any]]:
        return response['message']['content'], []

def get_provider_adapter(provider: str, model_config: ModelConfig) -> ProviderAdapter:
    adapters = {
        "openai": OpenAIAdapter(model_config),
        "litellm": LiteLLMAdapter(model_config),
        "anthropic": AnthropicAdapter(model_config),
        "ollama": OllamaAdapter(model_config),
    }
    return adapters.get(provider.lower(), LiteLLMAdapter(model_config))  # Default to LiteLLMAdapter if provider not found