# Import other adapters as they're implemented
import logging

__all__ = [
    "AnthropicAdapter",
    "BaseAdapter", 
    "OllamaAdapter",
    "get_adapter",
]

from ..provider_adapters import get_provider_adapter
from .base import BaseAdapter
# Lazy import the heavy adapters to avoid import time overhead
# from .anthropic import AnthropicAdapter
# from .ollama import OllamaAdapter


def get_adapter(provider: str, model_config):
    """
    Get the appropriate adapter for the provider.
    Uses client_preference to determine whether to use native adapter or generic one.
    """
    # Try to import native adapter first if client_preference is 'native'
    try:
        # Map provider names to module & class names
        provider_mapping = {
            "anthropic": ("anthropic", "AnthropicAdapter"),
            "ollama": ("ollama", "OllamaAdapter"),
            # "openai": ("openai", "OpenAIAdapter"), # TODO: Add OpenAI adapter
            # Add more mappings as needed
        }

        # Check if we should use native adapter based on client_preference
        if (
            getattr(model_config, "client_preference", "native") == "native"
            and provider in provider_mapping
        ):
            module_name, class_name = provider_mapping[provider]
            # Dynamic import to avoid import-time overhead
            adapter_module = __import__(
                f"penguin.llm.adapters.{module_name}", fromlist=[class_name]
            )
            adapter_class = getattr(adapter_module, class_name)
            logging.info(f"Using native {provider} adapter")
            return adapter_class(model_config)
    except (ImportError, AttributeError) as e:
        logging.warning(f"Native adapter for {provider} not available: {e}")

    # Fall back to provider_adapters.py implementation
    logging.info(f"Using generic adapter for {provider} via provider_adapters")
    return get_provider_adapter(provider, model_config)
