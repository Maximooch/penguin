# Import other adapters as they're implemented
import logging

__all__ = [
    "AnthropicAdapter",
    "BaseAdapter",
    "OllamaAdapter",
    "OpenAIAdapter",
    "OpenAICompatibleAdapter",
    "get_adapter",
]

from ..provider_transform import normalize_provider_name
from .base import BaseAdapter
# Lazy import the heavy adapters to avoid import time overhead
# from .anthropic import AnthropicAdapter
# from .ollama import OllamaAdapter


def get_adapter(provider: str, model_config):
    """
    Get the appropriate adapter for the provider.
    Uses client_preference to determine whether to use native adapter or generic one.
    """
    provider = normalize_provider_name(provider)

    # Try to import native adapter first if client_preference is 'native'
    try:
        # Map provider names to module & class names
        provider_mapping = {
            "anthropic": ("anthropic", "AnthropicAdapter"),
            "ollama": ("ollama", "OllamaAdapter"),
            "openai": ("openai", "OpenAIAdapter"),
            "openai_compatible": ("openai_compatible", "OpenAICompatibleAdapter"),
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

    raise ValueError(
        f"No native adapter found for provider '{provider}'. "
        "Use a first-class native adapter, openrouter, litellm, or openai_compatible path instead."
    )
