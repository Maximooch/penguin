import os
from typing import Any, Dict, Optional


class ModelConfig:
    def __init__(
        self,
        model: str,
        provider: str,
        api_base: str = None,
        max_tokens: int = None,
        temperature: float = None,
        use_assistants_api: bool = False,
        supports_vision: bool = None,
        use_native_adapter: bool = True,
        streaming_enabled: bool = True,
        # Add token counting config
        enable_token_counting: bool = True,
        # api_key: str = None,
        vision_enabled: bool = None,
    ):
        self.model = model
        self.provider = provider
        self.api_base = api_base
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.max_history_tokens: Optional[int] = None
        self.use_assistants_api = (
            os.getenv("PENGUIN_ASSISTANT_ID") if use_assistants_api else False
        )
        
        # Set vision capability
        self.vision_enabled = vision_enabled
        if vision_enabled is None:
            # Automatically detect vision capability based on model name
            if provider == "anthropic" and "claude-3" in model:
                self.vision_enabled = True
            elif provider == "openai" and ("gpt-4" in model and "vision" in model):
                self.vision_enabled = True
            else:
                self.vision_enabled = False
        
        # This is for backward compatibility
        self.supports_vision = self.vision_enabled
        
        # Enable token counting by default
        self.enable_token_counting = enable_token_counting
        
        # Store API key
        # self.api_key = api_key
        # if not self.api_key and provider:
        #     # Try to get from environment if not provided
        #     self.api_key = os.getenv(f"{provider.upper()}_API_KEY")
            
        self.use_native_adapter = use_native_adapter
        self.streaming_enabled = streaming_enabled

    def get_config(self) -> Dict[str, Any]:
        config = {
            "model": self.model,
            "provider": self.provider,
            "supports_vision": self.supports_vision,
        }
        if self.api_base:
            config["api_base"] = self.api_base
        if self.max_tokens:
            config["max_tokens"] = self.max_tokens
        if self.temperature is not None:
            config["temperature"] = self.temperature
        if self.max_history_tokens is not None:
            config["max_history_tokens"] = self.max_history_tokens
        config["use_assistants_api"] = self.use_assistants_api
        return config

    @classmethod
    def from_env(cls):
        return cls(
            model=os.getenv("PENGUIN_MODEL"),
            provider=os.getenv("PENGUIN_PROVIDER"),
            api_base=os.getenv("PENGUIN_API_BASE"),
            max_tokens=int(os.getenv("PENGUIN_MAX_TOKENS"))
            if os.getenv("PENGUIN_MAX_TOKENS")
            else None,
            temperature=float(os.getenv("PENGUIN_TEMPERATURE"))
            if os.getenv("PENGUIN_TEMPERATURE")
            else None,
            max_history_tokens=int(os.getenv("PENGUIN_MAX_HISTORY_TOKENS"))
            if os.getenv("PENGUIN_MAX_HISTORY_TOKENS")
            else None,
            use_assistants_api=os.getenv("PENGUIN_USE_ASSISTANTS_API", "false").lower()
            == "true",
            supports_vision=os.getenv("PENGUIN_SUPPORTS_VISION", "false").lower()
            == "true",
            use_native_adapter=os.getenv("PENGUIN_USE_NATIVE_ADAPTER", "false").lower()
            == "true",
            streaming_enabled=os.getenv("PENGUIN_STREAMING_ENABLED", "false").lower()
            == "true",
            # api_key=os.getenv(f"{os.getenv('PENGUIN_PROVIDER', '').upper()}_API_KEY"),
            vision_enabled=os.getenv("PENGUIN_VISION_ENABLED", "").lower() == "true"
            if os.getenv("PENGUIN_VISION_ENABLED")
            else None,
        )
