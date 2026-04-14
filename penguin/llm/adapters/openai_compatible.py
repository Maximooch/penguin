from __future__ import annotations

from .openai import OpenAIAdapter


class OpenAICompatibleAdapter(OpenAIAdapter):
    """Native adapter for OpenAI-compatible endpoints with custom `api_base`."""

    @property
    def provider(self) -> str:
        return "openai_compatible"


__all__ = ["OpenAICompatibleAdapter"]
