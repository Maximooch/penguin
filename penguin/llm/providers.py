from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional
from litellm import completion, RateLimitError, ServiceUnavailableError, BadRequestError, AuthenticationError, InvalidRequestError
from anthropic import Anthropic
from .model_config import ModelConfig
import os

class AIClient(ABC):
    @abstractmethod
    def create_message(self, messages, max_tokens=None, temperature=None):
        pass

    @abstractmethod
    def process_response(self, response):
        pass

class LiteLLMClient(AIClient):
    def __init__(self, api_key: str, model_config: ModelConfig):
        self.api_key = api_key
        self.model_config = model_config

    def create_message(self, messages, max_tokens=None, temperature=None):
        try:
            response = completion(
                model_name=self.model_config.model,
                messages=messages,
                max_tokens=max_tokens or self.model_config.max_tokens,
                temperature=temperature or self.model_config.temperature,
                api_key=self.api_key
            )
            return response
        except (RateLimitError, ServiceUnavailableError, BadRequestError, AuthenticationError, InvalidRequestError) as e:
            raise Exception(f"LiteLLM API error: {str(e)}")
        except Exception as e:
            raise Exception(f"Unexpected error calling LLM API: {str(e)}")
    
    def process_response(self, response):
        assistant_response = response.choices[0].message.content
        return assistant_response, []  # LiteLLM doesn't provide tool uses directly

"""
This module provides a client for interacting with the Anthropic Claude API.

The ClaudeAPIClient class is the main interface for making API requests and processing responses.
It handles tasks such as creating messages, encoding images, and counting tokens.

Example usage:
    model_config = ModelConfig()
    api_client = ClaudeAPIClient("your-api-key-here", model_config)
    response = api_client.create_message(
        model=model_config.model,
        max_tokens=model_config.max_tokens,
        system="You are a helpful AI assistant.",
        messages=[{"role": "user", "content": "Hello, how are you?"}],
        tools=[],
        tool_choice={"type": "auto"}
    )
    assistant_response, tool_uses = api_client.process_response(response)
    print(assistant_response)
    print(tool_uses)
"""


class ClaudeAPIClient(AIClient):
    def __init__(self, api_key: str, model_config: ModelConfig):
        self.client = Anthropic(api_key=api_key)
        self.model_config = model_config

    def create_message(self, messages, max_tokens=None, temperature=None):
        try:
            response = self.client.messages.create(
                model=self.model_config.model,
                max_tokens=max_tokens or self.model_config.max_tokens,
                temperature=temperature or self.model_config.temperature,
                messages=messages
            )
            return response.content[0].text
        except Exception as e:
            raise Exception(f"Error calling Claude API: {str(e)}")

    def process_response(self, response):
        assistant_response = ""
        tool_uses = []
        for content_block in response.content:
            if content_block.type == "text":
                assistant_response += content_block.text
            elif content_block.type == "tool_use":
                tool_uses.append({
                    "name": content_block.name,
                    "input": content_block.input,
                    "id": content_block.id
                })
        return assistant_response, tool_uses

# You can add more provider classes as needed

def get_ai_client(api_key: str, model_config: ModelConfig, provider: str) -> AIClient:
    if provider == "litellm":
        return LiteLLMClient(api_key, model_config)
    elif provider == "claude":
        return ClaudeAPIClient(api_key, model_config)
    else:
        raise ValueError(f"Unsupported provider: {provider}")

class OllamaClient(AIClient):
    def __init__(self, model_config: ModelConfig):
        self.model_config = model_config
        self.api_base = os.environ.get("OLLAMA_API_BASE", "http://localhost:11434")

    def create_message(self, messages, max_tokens=None, temperature=None):
        try:
            response = completion(
                model=self.model_config.model,
                messages=messages,
                max_tokens=max_tokens or self.model_config.max_tokens,
                temperature=temperature or self.model_config.temperature,
                api_base=self.api_base
            )
            return response
        except (RateLimitError, ServiceUnavailableError, BadRequestError, AuthenticationError, InvalidRequestError) as e:
            raise Exception(f"Ollama API error: {str(e)}")
        except Exception as e:
            raise Exception(f"Unexpected error calling Ollama API: {str(e)}")

    def process_response(self, response):
        assistant_response = response.choices[0].message.content
        return assistant_response, []  # Ollama doesn't provide tool uses