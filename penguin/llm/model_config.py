import os
from typing import Any, Dict, Optional, Literal, Union
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
    
    # Reasoning tokens support
    reasoning_enabled: bool = False
    reasoning_effort: Optional[Literal['low', 'medium', 'high']] = None
    reasoning_max_tokens: Optional[int] = None
    reasoning_exclude: bool = False
    supports_reasoning: Optional[bool] = None

    def __post_init__(self):
        if self.api_key is None and self.provider:
            self.api_key = os.getenv(f"{self.provider.upper()}_API_KEY")

        if self.client_preference == 'litellm' and "/" not in self.model:
            print(f"Warning: Model '{self.model}' for LiteLLM preference lacks provider prefix. Assuming '{self.provider}/{self.model}'.")
            self.model = f"{self.provider}/{self.model}"

        self.max_history_tokens = self.max_history_tokens or 200000
        
        # TODO: move this to the gateway. 
        # Auto-detect vision support 
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

        # Auto-detect reasoning support
        if self.supports_reasoning is None:
            self.supports_reasoning = self._detect_reasoning_support()
        
        # Set default reasoning configuration for reasoning-capable models
        if self.supports_reasoning and not self.reasoning_enabled:
            # Only auto-enable if user hasn't explicitly configured reasoning
            if (self.reasoning_effort is None and 
                self.reasoning_max_tokens is None and 
                not self.reasoning_exclude):
                self.reasoning_enabled = True
                # Set default reasoning effort based on model type
                if self._uses_effort_style():
                    self.reasoning_effort = "medium"
                elif self._uses_max_tokens_style():
                    self.reasoning_max_tokens = 2000

        self.supports_vision = self.vision_enabled
        self.streaming_enabled = self.streaming_enabled

    # TODO: move this to the gateway. 
    def _detect_reasoning_support(self) -> bool:
        """Auto-detect if the model supports reasoning tokens."""
        model_lower = self.model.lower()
        
        # DeepSeek R1 models
        if "deepseek" in model_lower and ("r1" in model_lower or "reasoning" in model_lower):
            return True
            
        # OpenAI o-series and GPT-5+ models
        if any(pattern in model_lower for pattern in ["o1", "o3", "openai/o", "gpt-5", "gpt-6"]):
            return True
            
        # Gemini thinking models and Gemini 2.5 Pro
        if "gemini" in model_lower and ("thinking" in model_lower or "2.5" in model_lower or "2-5" in model_lower):
            return True
            
        # Anthropic models with reasoning (Claude 3.7+ with reasoning support)
        if "anthropic" in model_lower and "claude" in model_lower:
            # Newer Claude models support reasoning
            if any(version in model_lower for version in ["3.7", "4.", "sonnet-4", "opus-4"]):
                return True
                
        # Grok models
        if "grok" in model_lower:
            return True
            
        return False
    
    def _uses_effort_style(self) -> bool:
        """Check if model uses effort-style reasoning configuration."""
        model_lower = self.model.lower()
        return any(pattern in model_lower for pattern in ["o1", "o3", "grok", "openai/o"])
    
    def _uses_max_tokens_style(self) -> bool:
        """Check if model uses max_tokens-style reasoning configuration."""
        model_lower = self.model.lower()
        return any(pattern in model_lower for pattern in ["gemini", "anthropic", "claude", "thinking"])

    def get_reasoning_config(self) -> Optional[Dict[str, Any]]:
        """Get the reasoning configuration for API requests."""
        if not self.reasoning_enabled or not self.supports_reasoning:
            return None
            
        config = {}
        
        if self.reasoning_effort:
            config["effort"] = self.reasoning_effort
        elif self.reasoning_max_tokens:
            config["max_tokens"] = self.reasoning_max_tokens
        else:
            # Default configuration
            config["enabled"] = True
            
        if self.reasoning_exclude:
            config["exclude"] = True
            
        return config

    def get_config(self) -> Dict[str, Any]:
        config = {
            "model": self.model,
            "provider": self.provider,
            "client_preference": self.client_preference,
            "supports_vision": self.supports_vision,
            "vision_enabled": self.vision_enabled,
            "streaming_enabled": self.streaming_enabled,
            "supports_reasoning": self.supports_reasoning,
            "reasoning_enabled": self.reasoning_enabled,
        }
        if self.api_base:
            config["api_base"] = self.api_base
        if self.max_tokens:
            config["max_tokens"] = self.max_tokens
        if self.temperature is not None:
            config["temperature"] = self.temperature
        if self.max_history_tokens is not None:
            config["max_history_tokens"] = self.max_history_tokens
        
        # Add reasoning config if enabled
        reasoning_config = self.get_reasoning_config()
        if reasoning_config:
            config["reasoning_config"] = reasoning_config
            
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

        # Parse reasoning configuration from environment
        reasoning_enabled = os.getenv("PENGUIN_REASONING_ENABLED", "").lower() == "true"
        reasoning_effort = os.getenv("PENGUIN_REASONING_EFFORT")
        reasoning_max_tokens = os.getenv("PENGUIN_REASONING_MAX_TOKENS")
        reasoning_exclude = os.getenv("PENGUIN_REASONING_EXCLUDE", "").lower() == "true"

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
            reasoning_enabled=reasoning_enabled,
            reasoning_effort=reasoning_effort if reasoning_effort in ['low', 'medium', 'high'] else None,
            reasoning_max_tokens=int(reasoning_max_tokens) if reasoning_max_tokens else None,
            reasoning_exclude=reasoning_exclude,
        )
