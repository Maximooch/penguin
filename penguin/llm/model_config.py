import os
from typing import Dict, Any, Optional

class ModelConfig:
    def __init__(self, model: str, provider: str, api_base: str = None, max_tokens: int = None, temperature: float = None, use_assistants_api: bool = False):
        self.model = model
        self.provider = provider
        self.api_base = api_base
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.max_history_tokens: Optional[int] = None
        self.use_assistants_api = os.getenv("PENGUIN_ASSISTANT_ID") if use_assistants_api else False


# "asst_ZyOhqU2AkTEZSLJagk6l9eIQ" # use_assistants_api

    def get_config(self) -> Dict[str, Any]:
        config = {
            "model": self.model,
            "provider": self.provider,
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
            max_tokens=int(os.getenv("PENGUIN_MAX_TOKENS")) if os.getenv("PENGUIN_MAX_TOKENS") else None,
            temperature=float(os.getenv("PENGUIN_TEMPERATURE")) if os.getenv("PENGUIN_TEMPERATURE") else None,
            max_history_tokens=int(os.getenv("PENGUIN_MAX_HISTORY_TOKENS")) if os.getenv("PENGUIN_MAX_HISTORY_TOKENS") else None,
            use_assistants_api=os.getenv("PENGUIN_USE_ASSISTANTS_API", "false").lower() == "true"
        )