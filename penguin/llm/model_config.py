import os
from typing import Any, Dict, Optional, Literal
from dataclasses import dataclass, field


@dataclass
class ModelConfig:
    """Configuration for a model."""
    model: str
    provider: str
    client_preference: Literal['native', 'litellm', 'openrouter'] = 'native'
    api_base: Optional[str] = None
    api_key: Optional[str] = None
    api_version: Optional[str] = None
    max_tokens: Optional[int] = None
    max_history_tokens: Optional[int] = None
    temperature: float = 0.7
    use_assistants_api: bool = False
    streaming_enabled: bool = False
    enable_token_counting: bool = True
    vision_enabled: Optional[bool] = None

    def __post_init__(self):
        if self.api_key is None and self.provider:
            self.api_key = os.getenv(f"{self.provider.upper()}_API_KEY")

        if self.client_preference == 'litellm' and "/" not in self.model:
            print(f"Warning: Model '{self.model}' for LiteLLM preference lacks provider prefix. Assuming '{self.provider}/{self.model}'.")
            self.model = f"{self.provider}/{self.model}"

        self.max_history_tokens = self.max_history_tokens or 200000
        
        if self.vision_enabled is None:
            model_lower = self.model.lower()
            if self.provider == "anthropic" and "claude-3" in model_lower:
                self.vision_enabled = True
            elif self.provider == "openai" and (("gpt-4" in model_lower and ("vision" in model_lower or "o" in model_lower))):
                self.vision_enabled = True
            elif self.provider == "google" and "gemini" in model_lower and "nano" not in model_lower:
                self.vision_enabled = True
            elif self.client_preference == 'litellm' and 'llava' in model_lower:
                self.vision_enabled = True
            else:
                self.vision_enabled = False

        self.supports_vision = self.vision_enabled
        
        self.streaming_enabled = self.streaming_enabled

    def get_config(self) -> Dict[str, Any]:
        config = {
            "model": self.model,
            "provider": self.provider,
            "client_preference": self.client_preference,
            "supports_vision": self.supports_vision,
            "vision_enabled": self.vision_enabled,
            "streaming_enabled": self.streaming_enabled,
        }
        if self.api_base:
            config["api_base"] = self.api_base
        if self.max_tokens:
            config["max_tokens"] = self.max_tokens
        if self.temperature is not None:
            config["temperature"] = self.temperature
        if self.max_history_tokens is not None:
            config["max_history_tokens"] = self.max_history_tokens
        return config

    @classmethod
    def from_env(cls):
        provider = os.getenv("PENGUIN_PROVIDER", "anthropic")
        client_pref = os.getenv("PENGUIN_CLIENT_PREFERENCE", "native")
        
        default_model = "anthropic/claude-3-5-sonnet-20240620"
        if client_pref == 'litellm':
            default_model = os.getenv("PENGUIN_MODEL", f"{provider}/claude-3-5-sonnet-20240620")
        elif client_pref == 'openrouter':
            # OpenRouter models are typically prefixed with the provider, e.g. "openai/gpt-4o"
            default_model = os.getenv("PENGUIN_MODEL", "openai/gpt-4o")
        else:
            default_model = os.getenv("PENGUIN_MODEL", "claude-3-5-sonnet-20240620")

        return cls(
            model=default_model,
            provider=provider,
            client_preference=client_pref,
            api_base=os.getenv("PENGUIN_API_BASE"),
            max_tokens=int(os.getenv("PENGUIN_MAX_TOKENS"))
            if os.getenv("PENGUIN_MAX_TOKENS")
            else None,
            temperature=float(os.getenv("PENGUIN_TEMPERATURE"))
            if os.getenv("PENGUIN_TEMPERATURE")
            else 0.7,
            max_history_tokens=int(os.getenv("PENGUIN_MAX_HISTORY_TOKENS"))
            if os.getenv("PENGUIN_MAX_HISTORY_TOKENS")
            else None,
            vision_enabled=os.getenv("PENGUIN_VISION_ENABLED", "").lower() == "true"
            if os.getenv("PENGUIN_VISION_ENABLED") != "" else None,
            streaming_enabled=os.getenv("PENGUIN_STREAMING_ENABLED", "true").lower()
            == "true",
        )
