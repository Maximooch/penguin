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
        """
        Process response from LiteLLM, handling different response formats
        """
        try:
            # Handle dictionary response
            if isinstance(response, dict):
                if 'choices' in response:
                    return response['choices'][0]['message']['content'], []
                return response.get('content', str(response)), []
            
            # Handle LiteLLM response object
            if hasattr(response, 'choices') and len(response.choices) > 0:
                if hasattr(response.choices[0], 'message'):
                    return response.choices[0].message.content, []
                if hasattr(response.choices[0], 'text'):
                    return response.choices[0].text, []
            
            # Handle string response (some providers like Deepseek might return direct string)
            if isinstance(response, str):
                return response, []
                
            # If we can't handle the response format, convert to string
            return str(response), []
            
        except Exception as e:
            logging.error(f"Error processing LiteLLM response: {str(e)}")
            # Return the raw response as string if we can't process it
            return str(response), []

class AnthropicAdapter(ProviderAdapter):
    def format_messages(self, messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Format messages for Anthropic API - combines multiple content parts into a single string
        to ensure compatibility with Anthropic's API requirements through LiteLLM.
        """
        formatted_messages = []
        for message in messages:
            content = message.get('content', '')
            role = message.get('role', 'user')
            
            # Handle image path in message
            if 'image_path' in message:
                import base64
                # Read and encode image
                with open(message['image_path'], 'rb') as img_file:
                    encoded_image = base64.b64encode(img_file.read()).decode('utf-8')
                
                formatted_content = [
                    {"type": "text", "text": content},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/jpeg;base64,{encoded_image}"
                        }
                    }
                ]
                formatted_messages.append({
                    'role': role,
                    'content': formatted_content
                })
            
            # Handle list-type content (for existing image URLs)
            elif isinstance(content, list):
                formatted_content = []
                for part in content:
                    if isinstance(part, dict):
                        if part.get('type') == 'text':
                            formatted_content.append({
                                "type": "text",
                                "text": part.get('text', '')
                            })
                        elif part.get('type') == 'image_url':
                            formatted_content.append(part)
                    else:
                        formatted_content.append({
                            "type": "text",
                            "text": str(part)
                        })
                formatted_messages.append({
                    'role': role,
                    'content': formatted_content
                })
            else:
                # Handle plain text content
                formatted_messages.append({
                    'role': role,
                    'content': [{"type": "text", "text": str(content)}]
                })
        
        return formatted_messages

    def process_response(self, response: Any) -> tuple[str, List[Any]]:
        """Process Anthropic API response"""
        if isinstance(response, dict):
            if 'choices' in response and len(response['choices']) > 0:
                message = response['choices'][0].get('message', {})
                return message.get('content', ''), []
        return str(response), []

class OllamaAdapter(ProviderAdapter):
    def format_messages(self, messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        # Ollama's LLaVA models accept the same format as OpenAI
        return messages

    def process_response(self, response: Any) -> tuple[str, List[Any]]:
        return response['message']['content'], []

class DeepseekAdapter(ProviderAdapter):
    def format_messages(self, messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Format messages for Deepseek API - uses OpenAI-compatible format
        """
        formatted_messages = []
        for message in messages:
            content = message.get('content', '')
            
            # Handle list-type content (like image messages)
            if isinstance(content, list):
                # Ensure each content part has proper format
                formatted_content = []
                for part in content:
                    if isinstance(part, dict):
                        if part.get('type') == 'text':
                            formatted_content.append(part.get('text', ''))
                        elif part.get('type') == 'image_url':
                            # Deepseek supports image URLs in OpenAI format
                            formatted_content.append({
                                "type": "image_url",
                                "image_url": {
                                    "url": part.get('image_url', {}).get('url', '')
                                }
                            })
                content = formatted_content
            
            formatted_messages.append({
                'role': message.get('role', 'user'),
                'content': content
            })
        
        return formatted_messages

    def process_response(self, response: Any) -> tuple[str, List[Any]]:
        """
        Process Deepseek API response - follows OpenAI format
        """
        if isinstance(response, dict):
            if 'choices' in response:
                return response['choices'][0]['message']['content'], []
            return response.get('content', ''), []
        return str(response), []

def get_provider_adapter(provider: str, model_config: ModelConfig) -> ProviderAdapter:
    adapters = {
        "openai": OpenAIAdapter(model_config),
        "litellm": LiteLLMAdapter(model_config),
        "anthropic": AnthropicAdapter(model_config),
        "ollama": OllamaAdapter(model_config),
        "deepseek": DeepseekAdapter(model_config),
    }
    return adapters.get(provider.lower(), LiteLLMAdapter(model_config))  # Default to LiteLLMAdapter if provider not found