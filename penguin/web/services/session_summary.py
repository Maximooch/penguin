"""Session summary/title generation helpers for OpenCode-compatible routes."""

from __future__ import annotations

import logging
import re
from typing import Any, Optional

from penguin.llm.api_client import APIClient
from penguin.llm.model_config import ModelConfig
from penguin.web.services.session_view import (
    get_session_info,
    get_session_metadata_title,
    get_session_messages,
    update_session_info,
)

logger = logging.getLogger(__name__)

_TITLE_PROMPT = (
    "Generate a concise title for this coding session. "
    "Use plain text only, no quotes. Keep it under 80 characters."
)

_REJECTED_TITLE_SUBSTRINGS = (
    "model processed the request but returned empty content",
    "try rephrasing",
    "returned empty content",
)


def _normalize_model_name(*, model: str, provider: str, client_preference: str) -> str:
    """Normalize model identifier for the selected client style."""
    candidate = model.strip()
    if client_preference != "native":
        return candidate

    prefix = f"{provider}/"
    if candidate.startswith(prefix):
        return candidate[len(prefix) :]
    return candidate


def _resolve_title_model_config(
    core: Any,
    *,
    provider_id: Optional[str],
    model_id: Optional[str],
) -> Optional[ModelConfig]:
    """Build a lightweight model config for one-off title generation."""
    current = getattr(core, "model_config", None)

    provider = provider_id or getattr(current, "provider", None)
    model = model_id or getattr(current, "model", None)
    if not isinstance(provider, str) or not provider.strip():
        return None
    if not isinstance(model, str) or not model.strip():
        return None

    provider = provider.strip()
    model = model.strip()

    if provider_id:
        if provider == "openrouter":
            client_preference = "openrouter"
        elif provider == "litellm":
            client_preference = "litellm"
        else:
            client_preference = "native"
    else:
        raw_preference = getattr(current, "client_preference", "native")
        if raw_preference in {"native", "litellm", "openrouter"}:
            client_preference = raw_preference
        elif provider == "openrouter":
            client_preference = "openrouter"
        else:
            client_preference = "native"

    normalized_model = _normalize_model_name(
        model=model,
        provider=provider,
        client_preference=client_preference,
    )

    return ModelConfig(
        model=normalized_model,
        provider=provider,
        client_preference=client_preference,
        api_base=getattr(current, "api_base", None),
        max_output_tokens=64,
        max_context_window_tokens=getattr(current, "max_context_window_tokens", None),
        max_history_tokens=getattr(current, "max_history_tokens", None),
        temperature=0.1,
        use_assistants_api=False,
        streaming_enabled=False,
        reasoning_enabled=False,
        reasoning_effort=None,
        reasoning_max_tokens=None,
        reasoning_exclude=True,
    )


def _extract_user_snippets(rows: list[dict[str, Any]]) -> list[str]:
    """Extract concise user text snippets from OpenCode-shaped session rows."""
    snippets: list[str] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        info = row.get("info")
        if not isinstance(info, dict) or info.get("role") != "user":
            continue

        parts = row.get("parts")
        if not isinstance(parts, list):
            continue

        for part in parts:
            if not isinstance(part, dict):
                continue
            if str(part.get("type", "")).strip().lower() != "text":
                continue
            text = part.get("text")
            if not isinstance(text, str):
                continue
            cleaned = " ".join(text.split())
            if cleaned:
                snippets.append(cleaned)
                break

        if len(snippets) >= 3:
            break

    return snippets


def _clean_generated_title(raw: Any) -> Optional[str]:
    """Normalize model output to a single safe title line."""
    if not isinstance(raw, str):
        return None

    cleaned = re.sub(r"<think>[\s\S]*?</think>", " ", raw, flags=re.IGNORECASE)
    cleaned = cleaned.strip()
    if not cleaned:
        return None

    lines = [line.strip() for line in cleaned.splitlines() if line.strip()]
    if not lines:
        return None

    title = lines[0].strip().strip('"`')
    title = re.sub(r"^title\s*:\s*", "", title, flags=re.IGNORECASE)
    title = " ".join(title.split())
    if not title:
        return None

    if len(title) > 80:
        title = title[:77].rstrip() + "..."

    lowered = title.lower()
    if lowered.startswith("[note:"):
        return None
    if any(fragment in lowered for fragment in _REJECTED_TITLE_SUBSTRINGS):
        return None

    return title


def _heuristic_title(snippets: list[str], session_id: str) -> str:
    """Generate deterministic fallback title when model generation fails."""
    if snippets:
        title = snippets[0]
        if len(title) > 80:
            title = title[:77].rstrip() + "..."
        return title
    return f"Session {session_id[-8:]}"


def _normalize_fallback_text(raw: Optional[str]) -> Optional[str]:
    """Normalize request-provided fallback text used for title generation."""
    if not isinstance(raw, str):
        return None
    cleaned = " ".join(raw.split()).strip()
    if not cleaned:
        return None
    return cleaned


async def _generate_title_with_model(
    core: Any,
    *,
    snippets: list[str],
    provider_id: Optional[str],
    model_id: Optional[str],
) -> Optional[str]:
    """Try to generate a title with one dedicated backend model call."""
    if not snippets:
        return None

    model_config = _resolve_title_model_config(
        core,
        provider_id=provider_id,
        model_id=model_id,
    )
    if model_config is None:
        return None

    summary_source = "\n".join(f"- {item[:280]}" for item in snippets)
    prompt = f"{_TITLE_PROMPT}\n\nSession excerpts:\n{summary_source}\n\nTitle:"
    messages = [{"role": "user", "content": prompt}]

    try:
        client = APIClient(model_config=model_config)
        result = await client.get_response(
            messages=messages,
            max_output_tokens=64,
            temperature=0.1,
            stream=False,
        )
    except Exception:
        logger.debug("Session title generation failed", exc_info=True)
        return None

    return _clean_generated_title(result)


async def summarize_session_title(
    core: Any,
    session_id: str,
    *,
    provider_id: Optional[str] = None,
    model_id: Optional[str] = None,
    fallback_text: Optional[str] = None,
) -> Optional[dict[str, Any]]:
    """Generate/update session title and return operation details.

    Returns:
        None when session does not exist.
        Otherwise: {changed, title, source, info, snippet_count, used_fallback_text}
    """
    existing = get_session_info(core, session_id)
    if existing is None:
        return None

    effective_provider_id = provider_id
    if not isinstance(effective_provider_id, str) or not effective_provider_id.strip():
        session_provider = (
            existing.get("providerID") if isinstance(existing, dict) else None
        )
        effective_provider_id = (
            session_provider if isinstance(session_provider, str) else None
        )

    effective_model_id = model_id
    if not isinstance(effective_model_id, str) or not effective_model_id.strip():
        session_model = existing.get("modelID") if isinstance(existing, dict) else None
        effective_model_id = session_model if isinstance(session_model, str) else None

    explicit_title = get_session_metadata_title(core, session_id)
    if explicit_title is None:
        return None

    rows = get_session_messages(core, session_id) or []
    snippets = _extract_user_snippets(rows)
    used_fallback_text = False
    if not snippets:
        fallback = _normalize_fallback_text(fallback_text)
        if fallback:
            snippets = [fallback]
            used_fallback_text = True

    generated = await _generate_title_with_model(
        core,
        snippets=snippets,
        provider_id=effective_provider_id,
        model_id=effective_model_id,
    )
    source = "generated" if generated else "heuristic"
    title = generated or _heuristic_title(snippets, session_id)

    current_title = explicit_title
    changed = bool(title and title != current_title)

    info = existing
    if changed:
        updated = update_session_info(core, session_id, title=title)
        if updated is not None:
            info = updated
        else:
            changed = False
            source = "existing"

    return {
        "changed": changed,
        "title": title,
        "source": source,
        "info": info,
        "snippet_count": len(snippets),
        "used_fallback_text": used_fallback_text,
    }
