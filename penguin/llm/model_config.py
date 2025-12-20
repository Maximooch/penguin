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

    # OpenRouter debug mode - echoes upstream request body (development only)
    debug_upstream: bool = False

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
            "debug_upstream": self.debug_upstream,
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
            debug_upstream=os.getenv("OPENROUTER_DEBUG", "").lower() == "true",
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


# =============================================================================
# MODEL SPECS SERVICE - Cached OpenRouter API fetching
# =============================================================================

import asyncio
import json
import logging
import time
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class ModelSpecs:
    """Specifications for an LLM model from OpenRouter."""
    model_id: str
    name: str
    context_length: int
    max_output_tokens: int
    provider: str
    pricing_prompt: Optional[float] = None  # per 1M tokens
    pricing_completion: Optional[float] = None  # per 1M tokens
    supports_vision: bool = False
    supports_reasoning: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "model_id": self.model_id,
            "name": self.name,
            "context_length": self.context_length,
            "max_output_tokens": self.max_output_tokens,
            "provider": self.provider,
            "pricing_prompt": self.pricing_prompt,
            "pricing_completion": self.pricing_completion,
            "supports_vision": self.supports_vision,
            "supports_reasoning": self.supports_reasoning,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ModelSpecs":
        return cls(
            model_id=data["model_id"],
            name=data["name"],
            context_length=data["context_length"],
            max_output_tokens=data["max_output_tokens"],
            provider=data["provider"],
            pricing_prompt=data.get("pricing_prompt"),
            pricing_completion=data.get("pricing_completion"),
            supports_vision=data.get("supports_vision", False),
            supports_reasoning=data.get("supports_reasoning", False),
        )


@dataclass
class _CacheEntry:
    """Cache entry with TTL."""
    specs: ModelSpecs
    fetched_at: float

    def is_expired(self, ttl_seconds: float) -> bool:
        return (time.time() - self.fetched_at) > ttl_seconds


class ModelSpecsService:
    """Service for fetching and caching model specifications from OpenRouter.

    Features:
    - In-memory cache with configurable TTL
    - Disk cache for persistence across restarts
    - Async batch fetching from OpenRouter API
    """

    DEFAULT_TTL_SECONDS = 3600  # 1 hour
    CACHE_FILE_NAME = "model_specs_cache.json"
    API_URL = "https://openrouter.ai/api/v1/models"
    API_TIMEOUT = 10.0

    def __init__(
        self,
        cache_dir: Optional[Path] = None,
        ttl_seconds: float = DEFAULT_TTL_SECONDS,
        enable_disk_cache: bool = True,
    ):
        self.ttl_seconds = ttl_seconds
        self.enable_disk_cache = enable_disk_cache
        self._cache: Dict[str, _CacheEntry] = {}
        self._all_models: list[Dict[str, Any]] = []  # Raw API data for model_selector
        self._all_models_fetched = False
        self._fetch_lock = asyncio.Lock()

        if cache_dir:
            self._cache_dir = cache_dir
        else:
            self._cache_dir = Path.home() / ".penguin" / "cache"

        if enable_disk_cache:
            self._load_disk_cache()

    async def get_specs(self, model_id: str, force_refresh: bool = False) -> Optional[ModelSpecs]:
        """Get specifications for a model."""
        if not force_refresh:
            cached = self._cache.get(model_id)
            if cached and not cached.is_expired(self.ttl_seconds):
                return cached.specs

        specs = await self._fetch_single(model_id)
        if specs:
            self._cache[model_id] = _CacheEntry(specs=specs, fetched_at=time.time())
            if self.enable_disk_cache:
                self._save_disk_cache()
        return specs

    async def get_specs_dict(self, model_id: str, force_refresh: bool = False) -> Dict[str, Any]:
        """Get specifications as a dictionary (for backwards compatibility)."""
        specs = await self.get_specs(model_id, force_refresh)
        if specs:
            return {
                "context_length": specs.context_length,
                "max_output_tokens": specs.max_output_tokens,
                "name": specs.name,
                "provider": specs.provider,
            }
        return {}

    async def get_all_models(self, force_refresh: bool = False) -> list[Dict[str, Any]]:
        """Get all models from OpenRouter (for model_selector UI)."""
        if not force_refresh and self._all_models_fetched and self._all_models:
            return self._all_models

        await self.preload_all()
        return self._all_models

    async def preload_all(self) -> int:
        """Preload all model specs from OpenRouter API."""
        async with self._fetch_lock:
            if self._all_models_fetched:
                return len(self._cache)

            try:
                import httpx

                async with httpx.AsyncClient() as client:
                    response = await client.get(self.API_URL, timeout=self.API_TIMEOUT)
                    response.raise_for_status()
                    data = response.json()
                    models = data.get("data", [])

                    self._all_models = models  # Store raw data for model_selector
                    now = time.time()
                    for model in models:
                        model_id = model.get("id")
                        if not model_id:
                            continue
                        specs = self._parse_api_model(model)
                        if specs:
                            self._cache[model_id] = _CacheEntry(specs=specs, fetched_at=now)

                    self._all_models_fetched = True
                    if self.enable_disk_cache:
                        self._save_disk_cache()

                    logger.info(f"Preloaded {len(self._cache)} model specs from OpenRouter")
                    return len(self._cache)

            except Exception as e:
                logger.warning(f"Failed to preload model specs: {e}")
                return len(self._cache)

    def get_cached_specs(self, model_id: str) -> Optional[ModelSpecs]:
        """Get specs from cache only (no API call)."""
        cached = self._cache.get(model_id)
        if cached and not cached.is_expired(self.ttl_seconds):
            return cached.specs
        return None

    def list_cached_models(self) -> list[str]:
        """List all cached model IDs."""
        return list(self._cache.keys())

    def clear_cache(self) -> None:
        """Clear all cached specs."""
        self._cache.clear()
        self._all_models = []
        self._all_models_fetched = False
        if self.enable_disk_cache:
            cache_file = self._cache_dir / self.CACHE_FILE_NAME
            if cache_file.exists():
                cache_file.unlink()

    async def _fetch_single(self, model_id: str) -> Optional[ModelSpecs]:
        """Fetch specs for a single model from API."""
        async with self._fetch_lock:
            try:
                import httpx

                async with httpx.AsyncClient() as client:
                    response = await client.get(self.API_URL, timeout=self.API_TIMEOUT)
                    response.raise_for_status()
                    data = response.json()
                    models = data.get("data", [])

                    for model in models:
                        if model.get("id") == model_id:
                            return self._parse_api_model(model)

                    logger.debug(f"Model {model_id} not found in OpenRouter API")
                    return None

            except Exception as e:
                logger.debug(f"Failed to fetch specs for {model_id}: {e}")
                return None

    def _parse_api_model(self, model: Dict[str, Any]) -> Optional[ModelSpecs]:
        """Parse OpenRouter API model response into ModelSpecs."""
        model_id = model.get("id")
        if not model_id:
            return None

        context_length = model.get("context_length", 0)
        max_output = model.get("top_provider", {}).get("max_completion_tokens")
        if not max_output:
            max_output = model.get("max_output_tokens")
        if not max_output:
            max_output = context_length // 4 if context_length else 4096

        provider = model_id.split("/")[0] if "/" in model_id else "unknown"

        pricing = model.get("pricing", {})
        pricing_prompt = pricing_completion = None
        try:
            if pricing.get("prompt"):
                pricing_prompt = float(pricing["prompt"]) * 1_000_000
            if pricing.get("completion"):
                pricing_completion = float(pricing["completion"]) * 1_000_000
        except (ValueError, TypeError):
            pass

        architecture = model.get("architecture", {})
        modality = architecture.get("modality", "")
        supports_vision = "image" in modality or "multimodal" in modality.lower()

        model_lower = model_id.lower()
        supports_reasoning = any(pattern in model_lower for pattern in [
            "o1", "o3", "r1", "thinking", "reasoning", "gpt-5",
            "claude-3.7", "claude-4", "gemini-2.5", "deepseek-r1",
        ])

        return ModelSpecs(
            model_id=model_id,
            name=model.get("name", model_id),
            context_length=context_length,
            max_output_tokens=max_output,
            provider=provider,
            pricing_prompt=pricing_prompt,
            pricing_completion=pricing_completion,
            supports_vision=supports_vision,
            supports_reasoning=supports_reasoning,
        )

    def _load_disk_cache(self) -> None:
        """Load cache from disk."""
        cache_file = self._cache_dir / self.CACHE_FILE_NAME
        if not cache_file.exists():
            return

        try:
            with open(cache_file, "r") as f:
                data = json.load(f)

            for model_id, entry_data in data.items():
                try:
                    specs = ModelSpecs.from_dict(entry_data["specs"])
                    fetched_at = entry_data.get("fetched_at", 0)
                    self._cache[model_id] = _CacheEntry(specs=specs, fetched_at=fetched_at)
                except (KeyError, TypeError) as e:
                    logger.debug(f"Skipping invalid cache entry for {model_id}: {e}")

            logger.debug(f"Loaded {len(self._cache)} model specs from disk cache")

        except Exception as e:
            logger.debug(f"Failed to load disk cache: {e}")

    def _save_disk_cache(self) -> None:
        """Save cache to disk."""
        try:
            self._cache_dir.mkdir(parents=True, exist_ok=True)
            cache_file = self._cache_dir / self.CACHE_FILE_NAME

            data = {}
            for model_id, entry in self._cache.items():
                data[model_id] = {
                    "specs": entry.specs.to_dict(),
                    "fetched_at": entry.fetched_at,
                }

            with open(cache_file, "w") as f:
                json.dump(data, f, indent=2)

        except Exception as e:
            logger.debug(f"Failed to save disk cache: {e}")


# Global singleton instance
_specs_service: Optional[ModelSpecsService] = None


def get_model_specs_service() -> ModelSpecsService:
    """Get the global ModelSpecsService instance."""
    global _specs_service
    if _specs_service is None:
        _specs_service = ModelSpecsService()
    return _specs_service


async def fetch_model_specs(model_id: str) -> Dict[str, Any]:
    """Convenience function to fetch model specs."""
    service = get_model_specs_service()
    return await service.get_specs_dict(model_id)
