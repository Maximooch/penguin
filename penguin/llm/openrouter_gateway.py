"""Compatibility shim for the OpenRouter gateway.

The implementation now lives under `penguin.llm.adapters.openrouter`.
"""

from __future__ import annotations

from .adapters.openrouter import OpenRouterGateway

__all__ = ["OpenRouterGateway"]
