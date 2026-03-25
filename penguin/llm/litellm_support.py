from __future__ import annotations

import importlib
from typing import Any


LITELLM_INSTALL_HINT = (
    "LiteLLM support is not installed. Install with "
    '`pip install "penguin-ai[llm_litellm]"` or switch '
    'client_preference to "openrouter" or "native".'
)


def _format_feature_message(feature: str) -> str:
    feature_text = str(feature or "LiteLLM support").strip()
    if not feature_text:
        feature_text = "LiteLLM support"
    return f"{feature_text} is unavailable. {LITELLM_INSTALL_HINT}"


def load_litellm_module(feature: str = "LiteLLM support") -> Any:
    """Import LiteLLM lazily and raise a clear error when unavailable."""
    try:
        return importlib.import_module("litellm")
    except ModuleNotFoundError as exc:
        if exc.name == "litellm":
            raise RuntimeError(_format_feature_message(feature)) from exc
        raise


def load_litellm_gateway_class(feature: str = "LiteLLM support") -> Any:
    """Import LiteLLM gateway lazily with a clear missing-extra error."""
    try:
        module = importlib.import_module("penguin.llm.litellm_gateway")
        return module.LiteLLMGateway
    except ModuleNotFoundError as exc:
        if exc.name == "litellm":
            raise RuntimeError(_format_feature_message(feature)) from exc
        raise
