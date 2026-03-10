"""Provider-aware reasoning variant helpers.

These helpers intentionally implement conservative variant exposure for native
providers to avoid sending unsupported effort values.
"""

from __future__ import annotations

import re
from typing import Any

_WIDELY_SUPPORTED_EFFORTS = ("low", "medium", "high")
_OPENAI_GPT51_EFFORTS = ("none", "low", "medium", "high")
_OPENAI_FULL_EFFORTS = ("none", "minimal", "low", "medium", "high", "xhigh")
_ANTHROPIC_STANDARD_EFFORTS = ("low", "medium", "high")
_ANTHROPIC_MAX_EFFORTS = ("low", "medium", "high", "max")


def _normalized_model_key(model_id: str) -> str:
    value = str(model_id or "").strip().lower()
    if not value:
        return ""
    return re.sub(r"[^a-z0-9]+", "-", value).strip("-")


def openai_reasoning_efforts(model_id: str) -> tuple[str, ...]:
    """Return conservative OpenAI effort variants for a model id."""
    key = _normalized_model_key(model_id)
    if not key:
        return ()

    if re.search(r"gpt-5(?:-[0-9]+)?-pro", key):
        return ("high",)

    if re.search(r"gpt-5-(?:[2-9]|[1-9][0-9])", key) or re.search(
        r"gpt-[6-9](?:-|$)",
        key,
    ):
        return _OPENAI_FULL_EFFORTS

    if "gpt-5-1" in key:
        return _OPENAI_GPT51_EFFORTS

    if "gpt-5" in key or re.match(r"o[1-9](?:-|$)", key):
        return _WIDELY_SUPPORTED_EFFORTS

    return ("high",)


def anthropic_reasoning_efforts(model_id: str) -> tuple[str, ...]:
    """Return conservative Anthropic effort variants for a model id."""
    key = _normalized_model_key(model_id)
    if not key:
        return ()

    if "claude-opus-4-6" in key:
        return _ANTHROPIC_MAX_EFFORTS

    if "claude-sonnet-4-6" in key or "claude-opus-4-5" in key:
        return _ANTHROPIC_STANDARD_EFFORTS

    return ()


def native_reasoning_efforts(provider_id: str, model_id: str) -> tuple[str, ...]:
    """Return supported effort variants for native OpenAI/Anthropic models."""
    provider = str(provider_id or "").strip().lower()
    if provider == "openai":
        return openai_reasoning_efforts(model_id)
    if provider == "anthropic":
        return anthropic_reasoning_efforts(model_id)
    return ()


def native_reasoning_variants(
    provider_id: str,
    model_id: str,
    reasoning_enabled: bool,
) -> dict[str, dict[str, Any]] | None:
    """Return OpenCode-style variant payload for native provider models."""
    if not reasoning_enabled:
        return None
    efforts = native_reasoning_efforts(provider_id, model_id)
    if not efforts:
        return None
    return {effort: {"reasoning": {"effort": effort}} for effort in efforts}
