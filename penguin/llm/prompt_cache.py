"""Stable, privacy-safe provider prompt-cache affinity helpers."""

from __future__ import annotations

import hashlib


def build_prompt_cache_key(
    *,
    session_id: str | None,
    provider: str | None,
    model: str | None,
    variant: str | None = None,
) -> str | None:
    """Build a bounded cache key stable for one session/model boundary.

    The raw session identifier is never sent to the provider. A model or
    variant change produces a different affinity key, while tool-loop turns in
    the same session keep the same key and therefore a stable prompt prefix.
    """

    normalized_session = str(session_id or "").strip()
    if not normalized_session:
        return None
    scope = ":".join(
        (
            str(provider or "unknown").strip().lower() or "unknown",
            str(model or "unknown").strip() or "unknown",
            str(variant or "default").strip().lower() or "default",
            normalized_session,
        )
    )
    digest = hashlib.sha256(scope.encode("utf-8")).hexdigest()
    return f"penguin_{digest[:48]}"


__all__ = ["build_prompt_cache_key"]
