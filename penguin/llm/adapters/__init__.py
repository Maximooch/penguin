from .base import BaseAdapter
from .anthropic import AnthropicAdapter
# Import other adapters as they're implemented

def get_adapter(provider: str, model_config) -> BaseAdapter:
    """Factory function to create the appropriate adapter"""
    provider = provider.lower()
    
    if provider == "anthropic":
        return AnthropicAdapter(model_config)
    # Add other provider-specific adapters as implemented
    else:
        # Fallback to LiteLLM adapter for other providers
        from .litellm import LiteLLMAdapter
        return LiteLLMAdapter(model_config) 