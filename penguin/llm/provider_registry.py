from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Optional

from .model_config import ModelConfig
from .provider_transform import (
    apply_model_config_transforms,
    is_openai_compatible_provider,
    normalize_client_preference,
)

logger = logging.getLogger(__name__)


NativeAdapterFactory = Callable[[str, ModelConfig], Any]
LiteLLMGatewayLoader = Callable[[str], Any]


@dataclass(frozen=True)
class ProviderContext:
    """Transport/runtime context passed into provider resolution."""

    base_url: Optional[str] = None
    extra_headers: Dict[str, str] = field(default_factory=dict)


class ProviderRegistry:
    """Centralized resolver for native, gateway, and compatible handlers."""

    def __init__(
        self,
        *,
        native_adapter_factory: NativeAdapterFactory,
        litellm_gateway_loader: LiteLLMGatewayLoader,
    ) -> None:
        self._native_adapter_factory = native_adapter_factory
        self._litellm_gateway_loader = litellm_gateway_loader

    def prepare_model_config(self, model_config: ModelConfig) -> ModelConfig:
        """Apply shared provider/model normalization before resolution."""

        return apply_model_config_transforms(model_config)

    def create_handler(
        self,
        model_config: ModelConfig,
        *,
        base_url: Optional[str] = None,
        extra_headers: Optional[Dict[str, str]] = None,
    ) -> Any:
        """Create a handler for the requested provider/runtime path."""

        prepared = self.prepare_model_config(model_config)
        context = ProviderContext(
            base_url=base_url,
            extra_headers=dict(extra_headers or {}),
        )
        preference = normalize_client_preference(prepared.client_preference)

        if preference == "openrouter":
            handler = self._create_openrouter_handler(prepared, context)
        elif preference == "litellm":
            handler = self._create_litellm_handler(prepared, context)
        elif preference == "native":
            handler = self._create_native_handler(prepared, context)
        else:
            raise ValueError(
                "Invalid client_preference: "
                f"{prepared.client_preference}. Must be 'native', 'litellm', or 'openrouter'."
            )

        self._apply_extra_headers(handler, context.extra_headers)
        return handler

    def _create_openrouter_handler(
        self,
        model_config: ModelConfig,
        context: ProviderContext,
    ) -> Any:
        from .openrouter_gateway import OpenRouterGateway

        return OpenRouterGateway(
            model_config,
            base_url=context.base_url,
            extra_headers=context.extra_headers or None,
        )

    def _create_litellm_handler(
        self,
        model_config: ModelConfig,
        context: ProviderContext,
    ) -> Any:
        LiteLLMGateway = self._litellm_gateway_loader("client_preference='litellm'")
        if context.base_url and not model_config.api_base:
            model_config.api_base = context.base_url
        handler = LiteLLMGateway(model_config)
        if context.extra_headers:
            setattr(handler, "extra_headers", dict(context.extra_headers))
        return handler

    def _create_native_handler(
        self,
        model_config: ModelConfig,
        context: ProviderContext,
    ) -> Any:
        if context.base_url and not model_config.api_base:
            model_config.api_base = context.base_url

        if is_openai_compatible_provider(model_config.provider):
            from .adapters.openai_compatible import OpenAICompatibleAdapter

            return OpenAICompatibleAdapter(model_config)

        return self._native_adapter_factory(model_config.provider, model_config)

    def _apply_extra_headers(
        self,
        handler: Any,
        extra_headers: Dict[str, str],
    ) -> None:
        """Best-effort header injection for transport-aware wrappers like Link."""

        if not extra_headers:
            return

        existing_headers = getattr(handler, "extra_headers", None)
        if isinstance(existing_headers, dict):
            existing_headers.update(extra_headers)
            return

        if existing_headers is None and hasattr(handler, "extra_headers"):
            setattr(handler, "extra_headers", dict(extra_headers))
            return

        client = getattr(handler, "client", None)
        if client is None:
            return

        default_headers = getattr(client, "default_headers", None)
        if isinstance(default_headers, dict):
            default_headers.update(extra_headers)
            return

        if default_headers is None:
            try:
                setattr(client, "default_headers", dict(extra_headers))
            except Exception:
                logger.debug(
                    "ProviderRegistry could not attach default_headers to %s",
                    type(handler).__name__,
                )


__all__ = ["ProviderContext", "ProviderRegistry"]
