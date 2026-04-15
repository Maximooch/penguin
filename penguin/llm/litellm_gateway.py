"""Compatibility shim for the LiteLLM gateway.

The implementation now lives under `penguin.llm.adapters.litellm`.
"""

from __future__ import annotations

from .adapters.litellm import LiteLLMGateway

__all__ = ["LiteLLMGateway"]
