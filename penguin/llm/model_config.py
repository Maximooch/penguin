import os
import warnings
from dataclasses import dataclass, field
from typing import Any, Dict, Literal, Optional

from penguin.constants import get_default_max_history_tokens


CONTEXT_WINDOW_SAFETY_FRACTION = max(
    min(float(os.getenv("PENGUIN_CONTEXT_SAFETY_FRACTION", "0.85")), 0.95),
    0.5,
)


def safe_context_window(context_length: Optional[int]) -> Optional[int]:
    """Return a buffered context window to leave headroom for prompts/responses."""
    if context_length is None or context_length <= 0:
        return None
    return max(int(context_length * CONTEXT_WINDOW_SAFETY_FRACTION), 1)


@dataclass
class ModelConfig:
    """Configuration for a model."""
    model: str
    provider: str
    client_preference: Literal['native', 'litellm', 'openrouter'] = 'native'
    api_base: Optional[str] = None
    api_key: Optional[str] = None
    api_version: Optional[str] = None
    # Max tokens the model may generate in a single response (output cap).
    max_output_tokens: Optional[int] = None
    # Model context window size (input capacity) in tokens, before safety buffer.
    max_context_window_tokens: Optional[int] = None
    max_history_tokens: Optional[int] = None
    temperature: float = 0.7
    use_assistants_api: bool = False
    streaming_enabled: bool = False
    enable_token_counting: bool = True
    vision_enabled: Optional[bool] = None
    
    # Responses API / streaming interrupt controls
    use_responses_api: bool = False
    interrupt_on_action: bool = True
    interrupt_on_tool_call: bool = False
    
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

        if self.max_history_tokens is None:
            if self.max_context_window_tokens is not None:
                self.max_history_tokens = safe_context_window(self.max_context_window_tokens)
            else:
                self.max_history_tokens = get_default_max_history_tokens()
        
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

    @property
    def max_tokens(self) -> Optional[int]:
        """Backward-compatible alias for `max_output_tokens`. Deprecated."""
        warnings.warn(
            "ModelConfig.max_tokens is deprecated. Use max_output_tokens instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        return self.max_output_tokens

    @max_tokens.setter
    def max_tokens(self, value: Optional[int]) -> None:
        warnings.warn(
            "ModelConfig.max_tokens is deprecated. Use max_output_tokens instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        self.max_output_tokens = value

    def _detect_reasoning_support(self) -> bool:
        """Auto-detect if the model supports reasoning tokens."""
        model_lower = self.model.lower()

        # DeepSeek R1 models
        if "deepseek" in model_lower and ("r1" in model_lower or "reasoning" in model_lower):
            return True

        # OpenAI o-series and GPT-5+ models (reasoning is MANDATORY for GPT-5.2+)
        # See: https://openrouter.ai/openai/gpt-5.2/api - "Mandatory reasoning"
        if any(pattern in model_lower for pattern in ["o1", "o3", "openai/o", "gpt-5", "gpt-6"]):
            return True
            
        # Gemini thinking models and Gemini 2.5 Pro
        if "gemini" in model_lower and ("thinking" in model_lower or "2.5" in model_lower or "2-5" in model_lower):
            return True
            
        # Anthropic models with reasoning (Claude 3.7+ with reasoning support)
        if "anthropic" in model_lower and "claude" in model_lower:
            # Newer Claude models support reasoning
            if any(version in model_lower for version in ["3.7", "claude-4", "sonnet-4", "opus-4"]):
                return True
                
        # Grok models
        if "grok" in model_lower:
            return True
            
        return False
    
    def _uses_effort_style(self) -> bool:
        """Check if model uses effort-style reasoning configuration."""
        model_lower = self.model.lower()
        # OpenAI reasoning models use effort-style (low/medium/high)
        return any(
            pattern in model_lower
            for pattern in [
                "o1",
                "o3",
                "grok",
                "openai/o",
                "gpt-5",
                "gpt-6",
            ]
        )
    
    def _uses_max_tokens_style(self) -> bool:
        """Check if model uses max_tokens-style reasoning configuration."""
        model_lower = self.model.lower()
        return any(pattern in model_lower for pattern in ["gemini", "anthropic", "claude", "thinking"])

    def get_reasoning_config(self) -> Optional[Dict[str, Any]]:
        """Get the reasoning configuration for API requests."""
        if not self.reasoning_enabled or not self.supports_reasoning:
            return None
            
        config = {}

        if self._uses_effort_style():
            config["effort"] = self.reasoning_effort or "high"
        elif self._uses_max_tokens_style():
            if self.reasoning_max_tokens is not None:
                config["max_tokens"] = self.reasoning_max_tokens
            else:
                config["max_tokens"] = 16000
        elif self.reasoning_effort:
            config["effort"] = self.reasoning_effort
        elif self.reasoning_max_tokens is not None:
            config["max_tokens"] = self.reasoning_max_tokens
            
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
            "use_responses_api": self.use_responses_api,
            "interrupt_on_action": self.interrupt_on_action,
            "interrupt_on_tool_call": self.interrupt_on_tool_call,
        }
        if self.api_base:
            config["api_base"] = self.api_base
        if self.max_output_tokens is not None:
            config["max_output_tokens"] = self.max_output_tokens
        if self.max_context_window_tokens is not None:
            config["max_context_window_tokens"] = self.max_context_window_tokens
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

        max_output_env = os.getenv("PENGUIN_MAX_OUTPUT_TOKENS") or os.getenv("PENGUIN_MAX_TOKENS") # TODO: renaming Penguin env vars
        max_context_env = os.getenv("PENGUIN_MAX_CONTEXT_WINDOW_TOKENS") or os.getenv("PENGUIN_CONTEXT_WINDOW")

        return cls(
            model=default_model,
            provider=provider,
            client_preference=client_pref,
            api_base=os.getenv("PENGUIN_API_BASE"),
            max_output_tokens=int(max_output_env) if max_output_env else None,
            max_context_window_tokens=int(max_context_env) if max_context_env else None,
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
            use_responses_api=os.getenv("PENGUIN_USE_RESPONSES_API", "false").lower() == "true",
            interrupt_on_action=os.getenv("PENGUIN_INTERRUPT_ON_ACTION", "true").lower() != "false",
            interrupt_on_tool_call=os.getenv("PENGUIN_INTERRUPT_ON_TOOL_CALL", "false").lower() == "true",
        )
    
    @classmethod
    def for_model(
        cls,
        model_name: str,
        provider: Optional[str] = None,
        client_preference: Optional[str] = None,
        model_configs: Optional[Dict[str, Dict[str, Any]]] = None,
    ):
        """Create ModelConfig for a specific model, dynamically resolving from model_configs.
        
        Args:
            model_name: The model identifier (e.g., "openai/gpt-5")
            provider: Provider override (if None, extracted from model_name or model_configs)
            client_preference: Client preference override
            model_configs: Dict of model-specific configs from config.yml
        
        Returns:
            ModelConfig instance with model-specific settings applied
        """
        # Load model_configs from config if not provided
        if model_configs is None:
            from penguin.config import load_config
            config_data = load_config()
            model_configs = config_data.get("model_configs", {})
        
        # Look up model-specific config
        model_specific = model_configs.get(model_name, {})
        
        # Extract provider from model name if not provided
        if provider is None:
            if "/" in model_name:
                provider = model_name.split("/")[0]
            else:
                provider = model_specific.get("provider", "openrouter")
        
        # Determine client preference
        if client_preference is None:
            client_preference = model_specific.get("client_preference", provider)
        
        # Build ModelConfig with model-specific settings
        return cls(
            model=model_name,
            provider=provider,
            client_preference=client_preference,
            api_base=model_specific.get("api_base") or os.getenv("PENGUIN_API_BASE"),
            max_output_tokens=model_specific.get("max_output_tokens")
            or model_specific.get("max_tokens")
            or (
                int(os.getenv("PENGUIN_MAX_OUTPUT_TOKENS") or os.getenv("PENGUIN_MAX_TOKENS"))
                if (os.getenv("PENGUIN_MAX_OUTPUT_TOKENS") or os.getenv("PENGUIN_MAX_TOKENS"))
                else None
            ),
            max_context_window_tokens=model_specific.get("max_context_window_tokens")
            or model_specific.get("context_window")
            or (
                int(os.getenv("PENGUIN_MAX_CONTEXT_WINDOW_TOKENS") or os.getenv("PENGUIN_CONTEXT_WINDOW"))
                if (os.getenv("PENGUIN_MAX_CONTEXT_WINDOW_TOKENS") or os.getenv("PENGUIN_CONTEXT_WINDOW"))
                else None
            ),
            temperature=model_specific.get("temperature") or (
                float(os.getenv("PENGUIN_TEMPERATURE")) if os.getenv("PENGUIN_TEMPERATURE") else 0.7
            ),
            streaming_enabled=model_specific.get("streaming_enabled", True),
            vision_enabled=model_specific.get("vision_enabled"),
            max_history_tokens=model_specific.get("max_history_tokens") or (
                int(os.getenv("PENGUIN_MAX_HISTORY_TOKENS")) if os.getenv("PENGUIN_MAX_HISTORY_TOKENS") else None
            ),
            reasoning_enabled=model_specific.get("reasoning", {}).get("enabled", False)
            if isinstance(model_specific.get("reasoning"), dict)
            else False,
            reasoning_effort=model_specific.get("reasoning", {}).get("effort")
            if isinstance(model_specific.get("reasoning"), dict)
            else None,
            reasoning_max_tokens=model_specific.get("reasoning", {}).get("max_tokens")
            if isinstance(model_specific.get("reasoning"), dict)
            else None,
            reasoning_exclude=model_specific.get("reasoning", {}).get("exclude", False)
            if isinstance(model_specific.get("reasoning"), dict)
            else False,
        )
