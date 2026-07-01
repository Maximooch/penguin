"""OpenCode-shaped session and message view adapters."""

from __future__ import annotations

import logging
import os
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from penguin import __version__
from penguin.core_runtime import session_lookup
from penguin.web.services.provider_catalog import canonical_model_id

TRANSCRIPT_KEY = "_opencode_transcript_v1"
USAGE_KEY = "_opencode_usage_v1"
TODO_KEY = "_opencode_todo_v1"
AGENT_MODE_KEY = "_opencode_agent_mode_v1"
REVERT_KEY = "_opencode_revert_v1"
SUMMARY_KEY = "_opencode_summary_v1"
REVERT_SNAPSHOT_KEY = "_opencode_revert_snapshot_v1"
MODEL_ID_KEY = "_opencode_model_id_v1"
PROVIDER_ID_KEY = "_opencode_provider_id_v1"
VARIANT_KEY = "_opencode_variant_v1"
TITLE_SOURCE_KEY = "_penguin_title_source_v1"
DIRECTORY_MISSING_KEY = "_penguin_directory_missing_v1"
TITLE_SOURCE_AUTO = "auto"
TITLE_SOURCE_MANUAL = "manual"

_TODO_STATUS_VALUES = {"pending", "in_progress", "completed", "cancelled"}
_TODO_PRIORITY_VALUES = {"high", "medium", "low"}
_TITLE_SOURCE_VALUES = {TITLE_SOURCE_AUTO, TITLE_SOURCE_MANUAL}

logger = logging.getLogger(__name__)


def _normalize_agent_mode(value: Any) -> Optional[str]:
    if not isinstance(value, str):
        return None
    normalized = value.strip().lower()
    if normalized in {"plan", "build"}:
        return normalized
    return None


def _normalize_non_empty_string(value: Any) -> Optional[str]:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


def _normalize_provider_id(value: object) -> Optional[str]:
    """Normalize a provider identifier.

    Args:
        value: Candidate provider identifier.

    Returns:
        Lowercased non-empty provider id, or None when value is not a string.
    """
    normalized = _normalize_non_empty_string(value)
    return normalized.lower() if normalized else None


def _normalize_model_id(provider_id: Optional[str], value: object) -> Optional[str]:
    """Normalize a model identifier for a provider.

    Args:
        provider_id: Optional normalized provider identifier.
        value: Candidate model identifier.

    Returns:
        Canonical model id, lowercased for providers with case-insensitive
        catalog ids, or None when value is not a non-empty string.
    """
    normalized = _normalize_non_empty_string(value)
    if not normalized:
        return None

    model_id = canonical_model_id(provider_id or "", normalized)
    if (provider_id or "").lower() in {
        "anthropic",
        "google",
        "ollama",
        "openai",
        "openrouter",
    }:
        return model_id.lower()
    return model_id


def _normalize_title_source(value: Any) -> Optional[str]:
    if not isinstance(value, str):
        return None
    normalized = value.strip().lower()
    if normalized in _TITLE_SOURCE_VALUES:
        return normalized
    return None


def _first_non_empty_with_source(
    *candidates: tuple[Any, str],
) -> tuple[Optional[str], Optional[str]]:
    """Return the first non-empty string and its origin label."""
    for value, source in candidates:
        normalized = _normalize_non_empty_string(value)
        if normalized:
            return normalized, source
    return None, None


def _model_selection_source(
    *,
    provider_id: Optional[str],
    provider_source: Optional[str],
    model_id: Optional[str],
    model_source: Optional[str],
    variant: Optional[str] = None,
    variant_source: Optional[str] = None,
) -> str:
    """Resolve a compact source label for a provider/model/variant selection."""
    sources: set[str] = set()
    if provider_id and provider_source:
        sources.add(provider_source)
    if model_id and model_source:
        sources.add(model_source)
    if variant and variant_source:
        sources.add(variant_source)
    if not sources:
        return "missing"
    if len(sources) == 1:
        return next(iter(sources))
    if "message" in sources:
        return "message"
    if "session" in sources:
        return "session"
    return "mixed"


def _build_model_selection_payload(
    model_state: dict[str, Optional[str] | bool],
) -> dict[str, Any]:
    """Build explicit model hydration metadata for OpenCode-shaped sessions."""
    provider_id = model_state.get("providerID")
    model_id = model_state.get("modelID")
    variant = model_state.get("variant")
    payload: dict[str, Any] = {
        "ready": bool(provider_id and model_id),
        "sessionScoped": bool(model_state.get("sessionScoped")),
        "source": model_state.get("source") or "missing",
    }
    if isinstance(provider_id, str) and provider_id:
        payload["providerID"] = provider_id
    if isinstance(model_id, str) and model_id:
        payload["modelID"] = model_id
    if (
        isinstance(provider_id, str)
        and provider_id
        and isinstance(model_id, str)
        and model_id
    ):
        payload["qualifiedID"] = f"{provider_id}/{model_id}"
    if isinstance(variant, str) and variant:
        payload["variant"] = variant

    for key in ("providerSource", "modelSource", "variantSource"):
        value = model_state.get(key)
        if isinstance(value, str) and value:
            payload[key] = value
    return payload


def _apply_model_selection(
    payload: dict[str, Any],
    model_state: dict[str, Optional[str] | bool],
) -> None:
    """Attach compatibility model fields and explicit hydration metadata."""
    provider_id = model_state.get("providerID")
    model_id = model_state.get("modelID")
    variant = model_state.get("variant")
    if isinstance(provider_id, str) and provider_id:
        payload["providerID"] = provider_id
    if isinstance(model_id, str) and model_id:
        payload["modelID"] = model_id
    if isinstance(variant, str) and variant:
        payload["variant"] = variant
    payload["modelSelection"] = _build_model_selection_payload(model_state)


def _resolve_session_model_state(
    core: Any,
    session: Any,
    message: Any | None = None,
) -> dict[str, Optional[str] | bool]:
    """Resolve model/provider/variant from message, session, then global fallback."""
    session_meta_raw = getattr(session, "metadata", None)
    session_meta = session_meta_raw if isinstance(session_meta_raw, dict) else {}
    message_meta_raw = (
        getattr(message, "metadata", None) if message is not None else None
    )
    message_meta = message_meta_raw if isinstance(message_meta_raw, dict) else {}
    message_model = message_meta.get("model")
    message_model_dict = message_model if isinstance(message_model, dict) else {}

    provider_raw, provider_source = _first_non_empty_with_source(
        (message_meta.get("providerID"), "message"),
        (message_meta.get("provider_id"), "message"),
        (message_model_dict.get("providerID"), "message"),
        (session_meta.get(PROVIDER_ID_KEY), "session"),
        (session_meta.get("providerID"), "session"),
        (session_meta.get("provider_id"), "session"),
        (getattr(getattr(core, "model_config", None), "provider", None), "global"),
    )
    provider_id = _normalize_provider_id(provider_raw)
    model_raw, model_source = _first_non_empty_with_source(
        (message_meta.get("modelID"), "message"),
        (message_meta.get("model_id"), "message"),
        (message_model_dict.get("modelID"), "message"),
        (session_meta.get(MODEL_ID_KEY), "session"),
        (session_meta.get("modelID"), "session"),
        (session_meta.get("model_id"), "session"),
        (getattr(getattr(core, "model_config", None), "model", None), "global"),
    )
    model_id = _normalize_model_id(provider_id, model_raw)
    variant, variant_source = _first_non_empty_with_source(
        (message_meta.get("variant"), "message"),
        (session_meta.get(VARIANT_KEY), "session"),
        (session_meta.get("variant"), "session"),
    )
    session_scoped = (
        provider_source in {"message", "session"}
        or model_source in {"message", "session"}
        or variant_source in {"message", "session"}
    )
    return {
        "providerID": provider_id,
        "modelID": model_id,
        "variant": variant,
        "providerSource": provider_source,
        "modelSource": model_source,
        "variantSource": variant_source,
        "source": _model_selection_source(
            provider_id=provider_id,
            provider_source=provider_source,
            model_id=model_id,
            model_source=model_source,
            variant=variant,
            variant_source=variant_source,
        ),
        "sessionScoped": session_scoped,
    }


def _iso_to_ms(value: Optional[str]) -> int:
    """Convert ISO timestamp to epoch milliseconds."""
    if not value:
        return 0
    try:
        return int(datetime.fromisoformat(value).timestamp() * 1000)
    except Exception:
        return 0


def _iter_session_managers(core: Any) -> list[Any]:
    """Return unique session manager instances across default + agents."""
    conversation_manager = getattr(core, "conversation_manager", None)
    return session_lookup.iter_session_managers(conversation_manager)


def _session_file_ids(manager: Any) -> list[str]:
    """Return session ids found on disk for a manager."""
    base_path = getattr(manager, "base_path", None)
    if not base_path:
        return []

    try:
        root = Path(base_path)
    except TypeError:
        return []
    if not root.exists() or not root.is_dir():
        return []

    session_format = getattr(manager, "format", "json")
    if not isinstance(session_format, str) or not session_format.strip():
        session_format = "json"

    ids: list[str] = []
    for path in root.glob(f"*.{session_format}"):
        if path.name == f"session_index.{session_format}":
            continue
        ids.append(path.stem)
    return ids


def _manager_session_ids(manager: Any) -> list[str]:
    """Return unique cached, indexed, and file-backed session ids."""
    ids: list[str] = []
    seen: set[str] = set()
    sources = (
        getattr(manager, "sessions", {}),
        getattr(manager, "session_index", {}),
        _session_file_ids(manager),
    )

    for source in sources:
        if isinstance(source, dict):
            values = source.keys()
        elif isinstance(source, list):
            values = source
        else:
            continue
        for value in values:
            session_id = str(value)
            if not session_id or session_id in seen:
                continue
            seen.add(session_id)
            ids.append(session_id)
    return ids


def _session_index(manager: Any) -> dict[str, dict[str, Any]]:
    index = getattr(manager, "session_index", {})
    if not isinstance(index, dict):
        return {}
    return {
        str(session_id): metadata
        for session_id, metadata in index.items()
        if isinstance(metadata, dict)
    }


def _indexed_session_updated(metadata: dict[str, Any]) -> int:
    value = metadata.get("last_active")
    if isinstance(value, str):
        return _iso_to_ms(value)
    return 0


def _indexed_session_directory(metadata: dict[str, Any]) -> str:
    value = metadata.get("directory")
    if isinstance(value, str) and value.strip():
        return _normalize_existing_directory(value)
    return ""


def _session_file_updated_ms(manager: Any, session_id: str) -> int:
    base_path = getattr(manager, "base_path", None)
    if not base_path:
        return 0
    session_format = getattr(manager, "format", "json")
    if not isinstance(session_format, str) or not session_format.strip():
        session_format = "json"
    try:
        path = Path(base_path) / f"{session_id}.{session_format}"
        return int(path.stat().st_mtime * 1000)
    except (OSError, TypeError, ValueError):
        return 0


def _session_index_updated_ms(
    manager: Any,
    index: dict[str, dict[str, Any]],
    session_id: str,
) -> int:
    metadata = index.get(session_id)
    if metadata is not None:
        return _indexed_session_updated(metadata)
    return _session_file_updated_ms(manager, session_id)


def _index_entry_from_session(session: Any) -> dict[str, Any]:
    metadata_raw = getattr(session, "metadata", {})
    metadata = metadata_raw if isinstance(metadata_raw, dict) else {}
    messages = getattr(session, "messages", [])
    message_count = len(messages) if isinstance(messages, list) else 0
    entry: dict[str, Any] = {
        "created_at": getattr(session, "created_at", None),
        "last_active": getattr(session, "last_active", None),
        "message_count": message_count,
        "title": _infer_title(session),
        "display_message_count": _display_message_count(session),
        "fallback_title": _has_fallback_title(session),
    }
    for key in (
        "directory",
        "title_source",
        TITLE_SOURCE_KEY,
        AGENT_MODE_KEY,
        "agent_mode",
        "parentID",
        "parent_id",
        "continued_from",
        "agent_id",
        "agentID",
        "parent_agent_id",
        "parentAgentID",
        PROVIDER_ID_KEY,
        MODEL_ID_KEY,
        VARIANT_KEY,
        "providerID",
        "modelID",
        "variant",
        "archived_at_ms",
    ):
        value = metadata.get(key)
        if isinstance(value, str) and value.strip():
            entry[key] = value.strip()
        elif isinstance(value, int):
            entry[key] = value
    permission = metadata.get("permission")
    if isinstance(permission, list):
        entry["permission"] = permission
    return entry


def _hydrate_index_entry_from_session(
    core: Any,
    manager: Any,
    index: dict[str, dict[str, Any]],
    session_id: str,
) -> dict[str, Any] | None:
    session = _load_session_view_only(manager, session_id)
    if session is None:
        return None
    entry = _index_entry_from_session(session)
    explicit_directory, _directory_source = _explicit_session_directory(core, session)
    if explicit_directory.strip():
        entry["directory"] = explicit_directory.strip()
    else:
        entry[DIRECTORY_MISSING_KEY] = True
    manager_index = getattr(manager, "session_index", None)
    if isinstance(manager_index, dict):
        manager_index[session_id] = entry
    index[session_id] = entry
    return entry


def _indexed_limited_session_ids(
    core: Any,
    manager: Any,
    *,
    session_ids: list[str],
    limit: Optional[int],
    start: Optional[int],
    normalized_directory: str,
) -> list[str] | None:
    if limit is None or limit <= 0:
        return None

    index = _session_index(manager)
    if not index:
        return None

    ranked = sorted(
        (
            session_id
            for session_id in session_ids
            if start is None
            or _session_index_updated_ms(manager, index, session_id) >= start
        ),
        key=lambda session_id: _session_index_updated_ms(manager, index, session_id),
        reverse=True,
    )
    if not normalized_directory:
        selected = ranked[:limit]
        index_dirty = False
        for session_id in selected:
            if session_id in index:
                continue
            if _hydrate_index_entry_from_session(core, manager, index, session_id):
                index_dirty = True
        if index_dirty:
            save_index = getattr(manager, "_save_index", None)
            manager_index = getattr(manager, "session_index", index)
            if callable(save_index) and isinstance(manager_index, dict):
                save_index(manager_index)
        return selected

    selected: list[str] = []
    index_dirty = False
    for session_id in ranked:
        metadata = index.get(session_id)
        if metadata is None:
            metadata = _hydrate_index_entry_from_session(
                core,
                manager,
                index,
                session_id,
            )
            if metadata is None:
                continue
            index_dirty = True
        session_directory = _indexed_session_directory(metadata)
        if not session_directory and metadata.get(DIRECTORY_MISSING_KEY) is True:
            continue
        if not session_directory:
            metadata = _hydrate_index_entry_from_session(
                core,
                manager,
                index,
                session_id,
            )
            if metadata is None:
                continue
            session_directory = _indexed_session_directory(metadata)
            index_dirty = True
        if not session_directory:
            continue
        if not _directory_matches(session_directory, normalized_directory):
            continue
        selected.append(session_id)
        if len(selected) >= limit:
            break

    if index_dirty:
        save_index = getattr(manager, "_save_index", None)
        manager_index = getattr(manager, "session_index", index)
        if callable(save_index) and isinstance(manager_index, dict):
            save_index(manager_index)
    return selected


def _metadata_string(metadata: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = metadata.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _metadata_int(metadata: dict[str, Any], key: str) -> int:
    value = metadata.get(key)
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return 0


def _build_index_session_info(
    core: Any,
    session_id: str,
    metadata: dict[str, Any],
) -> dict[str, Any]:
    """Build a lightweight Session.Info payload from session index metadata."""
    runtime = getattr(core, "runtime_config", None)
    runtime_dir = getattr(runtime, "active_root", None) or getattr(
        runtime,
        "project_root",
        None,
    )
    directory = _metadata_string(metadata, "directory")
    if not directory and runtime_dir:
        directory = str(runtime_dir)
    if not directory:
        directory = str(Path.cwd())

    created = _iso_to_ms(metadata.get("created_at"))
    updated = _iso_to_ms(metadata.get("last_active"))
    now = int(datetime.now().timestamp() * 1000)
    if created <= 0:
        created = now
    if updated <= 0:
        updated = created

    fallback_title = f"Session {session_id[-8:]}"
    title = _metadata_string(metadata, "title") or fallback_title
    message_count = _metadata_int(metadata, "message_count")
    display_count = _metadata_int(metadata, "display_message_count")
    if "display_message_count" not in metadata:
        display_count = message_count
    raw_fallback_title = metadata.get("fallback_title")
    has_fallback_title = (
        raw_fallback_title
        if isinstance(raw_fallback_title, bool)
        else title == fallback_title and display_count == 0
    )

    payload: dict[str, Any] = {
        "id": session_id,
        "slug": session_id,
        "projectID": "penguin",
        "directory": directory,
        "agent_mode": "build",
        "title": title,
        "message_count": message_count,
        "display_message_count": display_count,
        "fallback_title": has_fallback_title,
        "version": __version__,
        "time": {
            "created": created,
            "updated": updated,
        },
    }

    agent_mode = _normalize_agent_mode(
        metadata.get(AGENT_MODE_KEY) or metadata.get("agent_mode")
    )
    if agent_mode:
        payload["agent_mode"] = agent_mode

    parent_id = _metadata_string(metadata, "parentID", "parent_id", "continued_from")
    if parent_id:
        payload["parentID"] = parent_id
    agent_id = _metadata_string(metadata, "agent_id", "agentID")
    if agent_id:
        payload["agent_id"] = agent_id
    parent_agent_id = _metadata_string(metadata, "parent_agent_id", "parentAgentID")
    if parent_agent_id:
        payload["parent_agent_id"] = parent_agent_id

    provider_id = _normalize_provider_id(
        _metadata_string(metadata, PROVIDER_ID_KEY, "providerID", "provider_id")
    )
    model_id = _normalize_model_id(
        provider_id,
        _metadata_string(metadata, MODEL_ID_KEY, "modelID", "model_id"),
    )
    variant = _normalize_non_empty_string(
        _metadata_string(metadata, VARIANT_KEY, "variant")
    )
    _apply_model_selection(
        payload,
        {
            "providerID": provider_id,
            "modelID": model_id,
            "variant": variant,
            "providerSource": "session" if provider_id else None,
            "modelSource": "session" if model_id else None,
            "variantSource": "session" if variant else None,
            "source": _model_selection_source(
                provider_id=provider_id,
                provider_source="session" if provider_id else None,
                model_id=model_id,
                model_source="session" if model_id else None,
                variant=variant,
                variant_source="session" if variant else None,
            ),
            "sessionScoped": bool(provider_id or model_id or variant),
        },
    )

    archived_ms = _metadata_int(metadata, "archived_at_ms")
    if archived_ms > 0:
        payload["time"]["archived"] = archived_ms
    permission_rules = metadata.get("permission")
    if isinstance(permission_rules, list):
        payload["permission"] = permission_rules

    return payload


def _find_session(core: Any, session_id: str) -> tuple[Optional[Any], Optional[Any]]:
    """Find a session and its manager by id."""
    return session_lookup.find_session_store(
        core,
        session_id,
        load_session=_load_session_view_only,
    )


def _load_session_view_only(manager: Any, session_id: str) -> Optional[Any]:
    """Load a session for inspection without changing shared current_session."""
    previous = getattr(manager, "current_session", None)
    try:
        session = manager.load_session(session_id)
        loaded_id = str(getattr(session, "id", "")) if session is not None else ""
        if session is not None and loaded_id != str(session_id):
            logger.debug(
                "session.view.load_mismatch requested=%s returned=%s manager=%s",
                session_id,
                loaded_id,
                hex(id(manager)),
            )
            return None
        return session
    except Exception:
        logger.warning(
            "session.view.load_failed session=%s manager=%s",
            session_id,
            hex(id(manager)),
            exc_info=True,
        )
        return None
    finally:
        if hasattr(manager, "current_session"):
            manager.current_session = previous


def _infer_title(session: Any) -> str:
    """Derive a usable title for a session."""
    metadata = getattr(session, "metadata", {})
    if isinstance(metadata, dict) and isinstance(metadata.get("title"), str):
        title = metadata["title"].strip()
        if title:
            return title

    messages = getattr(session, "messages", [])
    for item in messages:
        if getattr(item, "role", None) != "user":
            continue
        content = getattr(item, "content", "")
        if isinstance(content, str):
            line = content.split("\n", 1)[0].strip()
            if line:
                return line[:64]
    return f"Session {str(getattr(session, 'id', 'unknown'))[-8:]}"


def _has_fallback_title(session: Any) -> bool:
    """Return whether session title falls back to its id suffix."""
    metadata = getattr(session, "metadata", {})
    if isinstance(metadata, dict) and isinstance(metadata.get("title"), str):
        if metadata["title"].strip():
            return False

    messages = getattr(session, "messages", [])
    for item in messages:
        if getattr(item, "role", None) != "user":
            continue
        content = getattr(item, "content", "")
        if isinstance(content, str) and content.split("\n", 1)[0].strip():
            return False
    return True


def _display_message_count(session: Any) -> int:
    """Count messages expected to produce visible TUI session rows."""
    metadata = getattr(session, "metadata", {})
    transcript = metadata.get(TRANSCRIPT_KEY) if isinstance(metadata, dict) else None
    transcript_count = 0

    if isinstance(transcript, dict):
        messages = transcript.get("messages")
        order = transcript.get("order")
        if isinstance(messages, dict) and isinstance(order, list):
            for message_id in order:
                entry = messages.get(message_id)
                if not isinstance(entry, dict):
                    continue
                parts = entry.get("parts")
                part_order = entry.get("part_order")
                if isinstance(parts, dict) and isinstance(part_order, list):
                    if any(
                        isinstance(parts.get(part_id), dict) for part_id in part_order
                    ):
                        transcript_count += 1

    legacy_count = sum(
        1
        for message in getattr(session, "messages", [])
        if getattr(message, "role", "") in {"user", "assistant", "tool"}
    )
    return max(transcript_count, legacy_count)


def _explicit_session_directory(core: Any, session: Any) -> tuple[str, str]:
    """Return a persisted or in-memory session directory, without runtime fallback."""
    metadata = getattr(session, "metadata", {})
    session_dirs = getattr(core, "_opencode_session_directories", {})

    if isinstance(metadata, dict):
        raw_directory = metadata.get("directory")
        if isinstance(raw_directory, str) and raw_directory.strip():
            return raw_directory, "metadata"

    if isinstance(session_dirs, dict):
        mapped = session_dirs.get(str(getattr(session, "id", "")))
        if isinstance(mapped, str) and mapped.strip():
            return mapped, "session_map"

    return "", "missing"


def _build_session_info(core: Any, session: Any, manager: Any) -> dict[str, Any]:
    """Build OpenCode-compatible Session.Info payload."""
    runtime = getattr(core, "runtime_config", None)
    runtime_dir = getattr(runtime, "active_root", None) or getattr(
        runtime, "project_root", None
    )
    metadata = getattr(session, "metadata", {})

    directory, directory_source = _explicit_session_directory(core, session)
    if not directory and runtime_dir:
        directory = str(runtime_dir)
        directory_source = "runtime"
    if not directory:
        directory = str(Path.cwd())
        directory_source = "cwd"

    if directory_source in {"runtime", "cwd"}:
        logger.debug(
            "session.view.directory_fallback "
            "session=%s source=%s resolved=%s manager=%s",
            getattr(session, "id", "unknown"),
            directory_source,
            directory,
            hex(id(manager)),
        )

    created = _iso_to_ms(getattr(session, "created_at", None))
    updated = _iso_to_ms(getattr(session, "last_active", None))
    now = int(datetime.now().timestamp() * 1000)

    if created <= 0:
        created = now
    if updated <= 0:
        updated = created

    messages = getattr(session, "messages", [])
    payload: dict[str, Any] = {
        "id": str(session.id),
        "slug": str(session.id),
        "projectID": "penguin",
        "directory": directory,
        "agent_mode": "build",
        "title": _infer_title(session),
        "message_count": len(messages) if isinstance(messages, list) else 0,
        "display_message_count": _display_message_count(session),
        "fallback_title": _has_fallback_title(session),
        "version": __version__,
        "time": {
            "created": created,
            "updated": updated,
        },
    }

    model_state = _resolve_session_model_state(core, session)
    _apply_model_selection(payload, model_state)

    if isinstance(metadata, dict):
        metadata_agent_mode = _normalize_agent_mode(
            metadata.get(AGENT_MODE_KEY) or metadata.get("agent_mode")
        )
        if metadata_agent_mode:
            payload["agent_mode"] = metadata_agent_mode

        parent_id = (
            metadata.get("parentID")
            or metadata.get("parent_id")
            or metadata.get("continued_from")
        )
        if isinstance(parent_id, str) and parent_id.strip():
            payload["parentID"] = parent_id.strip()

        agent_id = metadata.get("agent_id") or metadata.get("agentID")
        if isinstance(agent_id, str) and agent_id.strip():
            payload["agent_id"] = agent_id.strip()

        parent_agent_id = metadata.get("parent_agent_id") or metadata.get(
            "parentAgentID"
        )
        if isinstance(parent_agent_id, str) and parent_agent_id.strip():
            payload["parent_agent_id"] = parent_agent_id.strip()

        archived_raw = metadata.get("archived") or metadata.get("archived_at_ms")
        archived_ms: int | None = None
        if isinstance(archived_raw, int):
            archived_ms = archived_raw
        elif isinstance(archived_raw, str) and archived_raw.strip().isdigit():
            archived_ms = int(archived_raw.strip())
        if archived_ms and archived_ms > 0:
            payload["time"]["archived"] = archived_ms

        permission_rules = metadata.get("permission")
        if isinstance(permission_rules, list):
            payload["permission"] = permission_rules

        usage_snapshot = metadata.get(USAGE_KEY)
        if isinstance(usage_snapshot, dict):
            payload["usage"] = {
                "current_total_tokens": usage_snapshot.get("current_total_tokens", 0),
                "max_context_window_tokens": usage_snapshot.get(
                    "max_context_window_tokens"
                ),
                "available_tokens": usage_snapshot.get("available_tokens", 0),
                "percentage": usage_snapshot.get("percentage", 0),
                "categories": usage_snapshot.get("categories", {}),
                "truncations": usage_snapshot.get("truncations", {}),
            }

        summary_snapshot = metadata.get(SUMMARY_KEY)
        if isinstance(summary_snapshot, dict):
            summary_payload: dict[str, Any] = {
                "additions": int(summary_snapshot.get("additions", 0) or 0),
                "deletions": int(summary_snapshot.get("deletions", 0) or 0),
                "files": int(summary_snapshot.get("files", 0) or 0),
            }
            diffs = summary_snapshot.get("diffs")
            if isinstance(diffs, list):
                summary_payload["diffs"] = diffs
            payload["summary"] = summary_payload

        revert_snapshot = metadata.get(REVERT_KEY)
        if isinstance(revert_snapshot, dict):
            revert: dict[str, Any] = {}
            for key in ("messageID", "partID", "snapshot", "diff"):
                value = revert_snapshot.get(key)
                if isinstance(value, str) and value.strip():
                    revert[key] = value.strip()
            hidden_ids = revert_snapshot.get("hiddenMessageIDs")
            if isinstance(hidden_ids, list):
                normalized = [
                    str(item).strip()
                    for item in hidden_ids
                    if isinstance(item, str) and item.strip()
                ]
                if normalized:
                    revert["hiddenMessageIDs"] = normalized
            if isinstance(revert.get("messageID"), str):
                payload["revert"] = revert

    return payload


def _manager_for_new_session(core: Any, parent_id: str | None = None) -> Any:
    """Resolve owning session manager for new session creation."""
    if parent_id:
        _session, parent_manager = _find_session(core, parent_id)
        if parent_manager is not None:
            return parent_manager

    conversation_manager = getattr(core, "conversation_manager", None)
    if conversation_manager is None:
        return None

    current_agent_id = getattr(conversation_manager, "current_agent_id", "default")
    agent_managers = getattr(conversation_manager, "agent_session_managers", {})
    if isinstance(agent_managers, dict):
        manager = agent_managers.get(current_agent_id)
        if manager is not None:
            return manager

    return getattr(conversation_manager, "session_manager", None)


def create_session_info(
    core: Any,
    *,
    title: str | None = None,
    parent_id: str | None = None,
    directory: str | None = None,
    permission: list[dict[str, Any]] | None = None,
    agent_mode: str | None = None,
    provider_id: str | None = None,
    model_id: str | None = None,
    variant: str | None = None,
) -> dict[str, Any]:
    """Create a session and return OpenCode Session.Info payload."""
    manager = _manager_for_new_session(core, parent_id=parent_id)
    if manager is None:
        raise ValueError("Session manager is not available")

    session = manager.create_session()
    metadata = getattr(session, "metadata", None)
    if not isinstance(metadata, dict):
        metadata = {}
        session.metadata = metadata

    if isinstance(title, str) and title.strip():
        metadata["title"] = title.strip()
        metadata[TITLE_SOURCE_KEY] = TITLE_SOURCE_MANUAL
    if isinstance(parent_id, str) and parent_id.strip():
        metadata["parentID"] = parent_id.strip()
    if isinstance(directory, str) and directory.strip():
        metadata["directory"] = directory.strip()
    if isinstance(permission, list):
        metadata["permission"] = permission
    normalized_agent_mode = _normalize_agent_mode(agent_mode)
    if normalized_agent_mode:
        metadata[AGENT_MODE_KEY] = normalized_agent_mode
    normalized_provider = _normalize_non_empty_string(provider_id)
    if normalized_provider:
        metadata[PROVIDER_ID_KEY] = normalized_provider
    normalized_model = _normalize_non_empty_string(model_id)
    if normalized_model:
        metadata[MODEL_ID_KEY] = normalized_model
    normalized_variant = _normalize_non_empty_string(variant)
    if normalized_variant:
        metadata[VARIANT_KEY] = normalized_variant

    manager.mark_session_modified(session.id)
    manager.save_session(session)

    return _build_session_info(core, session, manager)


def update_session_info(
    core: Any,
    session_id: str,
    *,
    title: str | None = None,
    title_source: str | None = None,
    archived: int | None = None,
    agent_mode: str | None = None,
    provider_id: str | None = None,
    model_id: str | None = None,
    variant: str | None = None,
) -> Optional[dict[str, Any]]:
    """Update a session and return OpenCode Session.Info payload."""
    session, manager = _find_session(core, session_id)
    if session is None or manager is None:
        return None

    metadata = getattr(session, "metadata", None)
    if not isinstance(metadata, dict):
        metadata = {}
        session.metadata = metadata

    if isinstance(title, str):
        stripped_title = title.strip()
        if stripped_title:
            metadata["title"] = stripped_title
            metadata[TITLE_SOURCE_KEY] = (
                _normalize_title_source(title_source) or TITLE_SOURCE_MANUAL
            )
        elif "title" in metadata:
            metadata.pop("title", None)
            metadata.pop(TITLE_SOURCE_KEY, None)

    if archived is not None:
        if archived > 0:
            metadata["archived_at_ms"] = int(archived)
        else:
            metadata.pop("archived_at_ms", None)

    normalized_agent_mode = _normalize_agent_mode(agent_mode)
    if normalized_agent_mode:
        metadata[AGENT_MODE_KEY] = normalized_agent_mode
    normalized_provider = _normalize_non_empty_string(provider_id)
    if normalized_provider:
        metadata[PROVIDER_ID_KEY] = normalized_provider
    normalized_model = _normalize_non_empty_string(model_id)
    if normalized_model:
        metadata[MODEL_ID_KEY] = normalized_model
    if variant is not None:
        normalized_variant = _normalize_non_empty_string(variant)
        if normalized_variant:
            metadata[VARIANT_KEY] = normalized_variant
        else:
            metadata.pop(VARIANT_KEY, None)

    manager.mark_session_modified(session.id)
    manager.save_session(session)

    refreshed, refreshed_manager = _find_session(core, session_id)
    if refreshed is None or refreshed_manager is None:
        return None
    return _build_session_info(core, refreshed, refreshed_manager)


def remove_session_info(core: Any, session_id: str) -> bool:
    """Delete a session by id."""
    _session, manager = _find_session(core, session_id)
    if manager is None:
        return False
    deleted = bool(manager.delete_session(session_id))
    if deleted:
        session_dirs = getattr(core, "_opencode_session_directories", None)
        if isinstance(session_dirs, dict):
            session_dirs.pop(session_id, None)
    return deleted


def list_session_statuses(core: Any) -> dict[str, dict[str, Any]]:
    """Return OpenCode SessionStatus map for all known sessions."""
    statuses: dict[str, dict[str, Any]] = {}

    for info in list_session_infos(core):
        statuses[str(info["id"])] = {"type": "idle"}

    stream_states = getattr(core, "_opencode_stream_states", None)
    if isinstance(stream_states, dict):
        for session_id, state in stream_states.items():
            if not isinstance(state, dict):
                continue
            is_active = bool(state.get("active"))
            statuses[str(session_id)] = {"type": "busy" if is_active else "idle"}

    adapters = getattr(core, "_tui_adapters", None)
    if isinstance(adapters, dict):
        for session_id, adapter in adapters.items():
            adapter_status = getattr(adapter, "_session_status", None)
            if adapter_status in {"busy", "idle"}:
                statuses[str(session_id)] = {"type": adapter_status}

    active_requests = getattr(core, "_opencode_active_requests", None)
    if isinstance(active_requests, dict):
        for session_id, count in active_requests.items():
            if isinstance(count, int) and count > 0:
                statuses[str(session_id)] = {"type": "busy"}

    for session_id in list(statuses.keys()):
        messages = get_session_messages(core, session_id, limit=1)
        if not messages:
            continue
        last = messages[-1]
        info = last.get("info") if isinstance(last, dict) else None
        if not isinstance(info, dict):
            continue
        role = info.get("role")
        raw_time = info.get("time")
        time_data: dict[str, Any] = raw_time if isinstance(raw_time, dict) else {}
        completed = time_data.get("completed")
        if role == "assistant" and not completed:
            statuses[session_id] = {"type": "busy"}

    return statuses


def _line_counts(diff_text: str) -> tuple[int, int]:
    additions = 0
    deletions = 0
    for line in diff_text.splitlines():
        if line.startswith("+++") or line.startswith("---"):
            continue
        if line.startswith("+"):
            additions += 1
        elif line.startswith("-"):
            deletions += 1
    return additions, deletions


def _extract_file_from_diff(diff_text: str) -> str | None:
    for line in diff_text.splitlines():
        if line.startswith("+++ b/"):
            return line[6:].strip()
        if line.startswith("+++ "):
            candidate = line[4:].strip()
            if candidate != "/dev/null":
                return candidate
    return None


def _infer_file_path(part: dict[str, Any], state: dict[str, Any]) -> str:
    raw_input = state.get("input")
    input_data: dict[str, Any] = raw_input if isinstance(raw_input, dict) else {}
    raw_metadata = state.get("metadata")
    metadata: dict[str, Any] = raw_metadata if isinstance(raw_metadata, dict) else {}

    for key in ("filePath", "path", "file", "target"):
        value = input_data.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()

    for key in ("filePath", "path", "file"):
        value = metadata.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()

    tool_name = part.get("tool")
    if isinstance(tool_name, str) and tool_name.strip() == "write":
        value = input_data.get("file")
        if isinstance(value, str) and value.strip():
            return value.strip()

    return ""


def _build_file_diff(
    *,
    file_path: str,
    before: str,
    after: str,
    additions: int,
    deletions: int,
) -> dict[str, Any]:
    return {
        "file": file_path,
        "before": before,
        "after": after,
        "additions": max(additions, 0),
        "deletions": max(deletions, 0),
    }


def _normalize_file_diff(diff: dict[str, Any]) -> dict[str, Any] | None:
    file_path = _normalize_non_empty_string(diff.get("file"))
    if not file_path:
        return None

    before = diff.get("before")
    after = diff.get("after")
    additions = diff.get("additions")
    deletions = diff.get("deletions")

    return _build_file_diff(
        file_path=file_path,
        before=before if isinstance(before, str) else "",
        after=after if isinstance(after, str) else "",
        additions=additions if isinstance(additions, int) else 0,
        deletions=deletions if isinstance(deletions, int) else 0,
    )


def _merge_file_diffs(diffs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_file: dict[str, dict[str, Any]] = {}
    for diff in diffs:
        normalized = _normalize_file_diff(diff)
        if normalized is None:
            continue
        file_path = normalized["file"]
        existing = by_file.get(file_path)
        if existing is None:
            by_file[file_path] = normalized
            continue
        by_file[file_path] = {
            "file": file_path,
            "before": existing["before"] or normalized["before"],
            "after": normalized["after"] or existing["after"],
            "additions": existing["additions"] + normalized["additions"],
            "deletions": existing["deletions"] + normalized["deletions"],
        }

    return [by_file[file_path] for file_path in sorted(by_file)]


def _diffs_from_tool_part(part: dict[str, Any]) -> list[dict[str, Any]]:
    state = part.get("state")
    if not isinstance(state, dict):
        return []
    if state.get("status") not in {"completed", "error"}:
        return []

    raw_metadata = state.get("metadata")
    metadata: dict[str, Any] = raw_metadata if isinstance(raw_metadata, dict) else {}
    raw_diff = metadata.get("diff")
    diff_text = raw_diff if isinstance(raw_diff, str) else ""
    file_path = _infer_file_path(part, state)

    if diff_text:
        additions, deletions = _line_counts(diff_text)
        if not file_path:
            file_path = _extract_file_from_diff(diff_text) or "unknown"
        return [
            _build_file_diff(
                file_path=file_path,
                before="",
                after=diff_text,
                additions=additions,
                deletions=deletions,
            )
        ]

    raw_input = state.get("input")
    input_data: dict[str, Any] = raw_input if isinstance(raw_input, dict) else {}
    content = input_data.get("content")
    if isinstance(file_path, str) and file_path and isinstance(content, str):
        additions = len(content.splitlines())
        return [
            _build_file_diff(
                file_path=file_path,
                before="",
                after=content,
                additions=additions,
                deletions=0,
            )
        ]

    output = state.get("output")
    if isinstance(output, str) and "\n" in output and file_path:
        additions, deletions = _line_counts(output)
        if additions > 0 or deletions > 0:
            return [
                _build_file_diff(
                    file_path=file_path,
                    before="",
                    after=output,
                    additions=additions,
                    deletions=deletions,
                )
            ]

    return []


def _run_git(args: list[str], cwd: str) -> str:
    try:
        proc = subprocess.run(
            ["git", *args],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
    except Exception:
        return ""
    if proc.returncode != 0:
        return ""
    return proc.stdout.strip()


def _normalize_existing_directory(directory: Any) -> Optional[str]:
    """Return resolved directory path when it exists, else None."""
    if not isinstance(directory, str) or not directory.strip():
        return None
    try:
        resolved = Path(directory).expanduser().resolve()
    except Exception:
        return None
    if not resolved.exists() or not resolved.is_dir():
        return None
    return str(resolved)


def _directory_matches(left: str, right: str) -> bool:
    """Check whether two directory paths reference the same directory."""
    if left == right:
        return True
    try:
        return Path(left).samefile(right)
    except Exception:
        return False


def _session_directory(core: Any, session: Any) -> str:
    metadata = getattr(session, "metadata", {})
    if isinstance(metadata, dict):
        raw_directory = metadata.get("directory")
        if isinstance(raw_directory, str) and raw_directory.strip():
            return str(Path(raw_directory).expanduser())

    session_dirs = getattr(core, "_opencode_session_directories", {})
    if isinstance(session_dirs, dict):
        mapped = session_dirs.get(str(getattr(session, "id", "")))
        if isinstance(mapped, str) and mapped.strip():
            return mapped

    runtime = getattr(core, "runtime_config", None)
    runtime_dir = getattr(runtime, "active_root", None) or getattr(
        runtime, "project_root", None
    )
    if isinstance(runtime_dir, str) and runtime_dir.strip():
        return runtime_dir

    env_dir = os.getenv("PENGUIN_CWD")
    if isinstance(env_dir, str) and env_dir.strip():
        return env_dir

    return str(Path.cwd())


def _git_fallback_diffs(directory: str) -> list[dict[str, Any]]:
    worktree = _run_git(["rev-parse", "--show-toplevel"], directory)
    if not worktree:
        return []

    changed = _run_git(["diff", "--name-only"], worktree)
    files = [line.strip() for line in changed.splitlines() if line.strip()]
    diffs: list[dict[str, Any]] = []
    for relative_path in files:
        patch = _run_git(["diff", "--", relative_path], worktree)
        additions, deletions = _line_counts(patch)
        diffs.append(
            _build_file_diff(
                file_path=relative_path,
                before="",
                after=patch,
                additions=additions,
                deletions=deletions,
            )
        )

    untracked = _run_git(["ls-files", "--others", "--exclude-standard"], worktree)
    for relative_path in (
        line.strip() for line in untracked.splitlines() if line.strip()
    ):
        file_path = Path(worktree) / relative_path
        if not file_path.is_file():
            continue
        try:
            content = file_path.read_text(encoding="utf-8")
        except OSError:
            continue
        except UnicodeDecodeError:
            content = ""
        additions = len(content.splitlines()) if content else 0
        diffs.append(
            _build_file_diff(
                file_path=relative_path,
                before="",
                after=content,
                additions=additions,
                deletions=0,
            )
        )

    return _merge_file_diffs(diffs)


def get_session_diff(
    core: Any,
    session_id: str,
    *,
    message_id: str | None = None,
) -> Optional[list[dict[str, Any]]]:
    """Return OpenCode FileDiff[] derived from persisted message/tool transcript."""
    session, _manager = _find_session(core, session_id)
    if session is None:
        return None

    rows = get_session_messages(core, session_id)
    if rows is None:
        return None

    selected_rows: list[dict[str, Any]] = []
    if isinstance(message_id, str) and message_id.strip():
        for row in rows:
            info = row.get("info") if isinstance(row, dict) else None
            if isinstance(info, dict) and info.get("id") == message_id:
                selected_rows.append(row)
    else:
        selected_rows = [row for row in rows if isinstance(row, dict)]

    diffs: list[dict[str, Any]] = []
    for row in selected_rows:
        parts = row.get("parts")
        if not isinstance(parts, list):
            continue
        for part in parts:
            if not isinstance(part, dict) or part.get("type") != "tool":
                continue
            diffs.extend(_diffs_from_tool_part(part))

    merged_diffs = _merge_file_diffs(diffs)
    if merged_diffs:
        return merged_diffs

    fallback_diffs = _git_fallback_diffs(_session_directory(core, session))
    logger.warning(
        "session.view.diff_git_fallback session=%s message_id=%s diff_count=%s",
        session_id,
        message_id or "",
        len(fallback_diffs),
    )
    return fallback_diffs


def list_session_infos(
    core: Any,
    *,
    start: Optional[int] = None,
    search: Optional[str] = None,
    limit: Optional[int] = None,
    directory: Optional[str] = None,
    roots: bool = False,
) -> list[dict[str, Any]]:
    """List sessions in OpenCode Session.Info shape."""
    results: list[dict[str, Any]] = []
    lowered_search = search.lower() if search else None
    normalized_directory = _normalize_existing_directory(directory)

    for manager in _iter_session_managers(core):
        session_ids = _manager_session_ids(manager)
        indexed_ids: list[str] | None = None
        if not lowered_search and not roots:
            indexed_ids = _indexed_limited_session_ids(
                core,
                manager,
                session_ids=session_ids,
                limit=limit,
                start=start,
                normalized_directory=normalized_directory,
            )
        if indexed_ids is not None:
            index = _session_index(manager)
            for session_id in indexed_ids:
                metadata = index.get(session_id)
                if not isinstance(metadata, dict):
                    continue
                results.append(
                    _build_index_session_info(
                        core,
                        session_id,
                        metadata,
                    )
                )
            continue

        for session_id in session_ids:
            session = None
            cached = getattr(manager, "sessions", {})
            if isinstance(cached, dict) and session_id in cached:
                session = cached[session_id][0]
            if session is None:
                session = _load_session_view_only(manager, session_id)
            if session is None:
                continue

            if normalized_directory:
                explicit_directory, _directory_source = _explicit_session_directory(
                    core,
                    session,
                )
                session_directory = _normalize_existing_directory(explicit_directory)
                if not session_directory:
                    continue
                if not _directory_matches(session_directory, normalized_directory):
                    continue

            info = _build_session_info(core, session, manager)

            if roots and info.get("parentID"):
                continue
            if start is not None and info["time"]["updated"] < start:
                continue
            if lowered_search and lowered_search not in info["title"].lower():
                continue

            results.append(info)

    results.sort(key=lambda item: item["time"]["updated"], reverse=True)
    if limit is not None and limit > 0:
        return results[:limit]
    return results


def get_session_info(core: Any, session_id: str) -> Optional[dict[str, Any]]:
    """Return one session in OpenCode Session.Info shape."""
    session, manager = _find_session(core, session_id)
    if session is None or manager is None:
        return None
    return _build_session_info(core, session, manager)


def get_session_metadata_title(core: Any, session_id: str) -> Optional[str]:
    """Return explicit metadata title for a session.

    Returns:
        None: session does not exist.
        "": session exists but has no explicit metadata title.
        non-empty string: explicit metadata title.
    """
    session, _manager = _find_session(core, session_id)
    if session is None:
        return None

    metadata = getattr(session, "metadata", None)
    if not isinstance(metadata, dict):
        return ""

    raw_title = metadata.get("title")
    if not isinstance(raw_title, str):
        return ""
    return raw_title.strip()


def get_session_title_source(core: Any, session_id: str) -> Optional[str]:
    """Return title ownership metadata for a session.

    Returns:
        None: session does not exist.
        "": session exists but title source is missing/legacy.
        "auto" or "manual": known title owner.
    """
    session, _manager = _find_session(core, session_id)
    if session is None:
        return None

    metadata = getattr(session, "metadata", None)
    if not isinstance(metadata, dict):
        return ""

    return _normalize_title_source(metadata.get(TITLE_SOURCE_KEY)) or ""


def _default_assistant_info(
    core: Any,
    session_id: str,
    message_id: str,
    *,
    agent_id: str | None = None,
    session: Any | None = None,
    created_ms: int | None = None,
) -> dict[str, Any]:
    """Build a minimal valid assistant info envelope."""
    now = (
        created_ms
        if isinstance(created_ms, int)
        else int(datetime.now().timestamp() * 1000)
    )
    cwd = str(Path.cwd())
    model_state = _resolve_session_model_state(core, session or object())
    return {
        "id": message_id,
        "sessionID": session_id,
        "role": "assistant",
        "time": {"created": now},
        "parentID": "root",
        "modelID": model_state["modelID"] or "penguin-default",
        "providerID": model_state["providerID"] or "penguin",
        "mode": "chat",
        "agent": agent_id.strip()
        if isinstance(agent_id, str) and agent_id.strip()
        else "default",
        "path": {"cwd": cwd, "root": cwd},
        "cost": 0,
        "tokens": {
            "input": 0,
            "output": 0,
            "reasoning": 0,
            "cache": {"read": 0, "write": 0},
        },
        **({"variant": model_state["variant"]} if model_state["variant"] else {}),
    }


def _legacy_message_to_with_parts(
    core: Any, session: Any, message: Any
) -> dict[str, Any]:
    """Project legacy Penguin message into OpenCode MessageV2.WithParts."""
    session_id = str(session.id)
    message_id = str(getattr(message, "id", ""))
    role = getattr(message, "role", "assistant")
    created = _iso_to_ms(getattr(message, "timestamp", None))
    created = created or int(datetime.now().timestamp() * 1000)
    content = getattr(message, "content", "")
    text = content if isinstance(content, str) else str(content)
    model_state = _resolve_session_model_state(core, session, message)

    if role == "user":
        info = {
            "id": message_id,
            "sessionID": session_id,
            "role": "user",
            "time": {"created": created},
            "agent": getattr(message, "agent_id", None) or "default",
            "model": {
                "providerID": model_state["providerID"] or "penguin",
                "modelID": model_state["modelID"] or "penguin-default",
            },
            **({"variant": model_state["variant"]} if model_state["variant"] else {}),
        }
    else:
        message_agent = getattr(message, "agent_id", None)
        if not isinstance(message_agent, str) or not message_agent.strip():
            metadata = getattr(session, "metadata", {})
            if isinstance(metadata, dict):
                message_agent = metadata.get("agent_id")
        info = _default_assistant_info(
            core,
            session_id,
            message_id,
            agent_id=message_agent if isinstance(message_agent, str) else None,
            session=session,
        )
        info["time"] = {"created": created, "completed": created}
        if model_state["providerID"]:
            info["providerID"] = model_state["providerID"]
        if model_state["modelID"]:
            info["modelID"] = model_state["modelID"]
        if model_state["variant"]:
            info["variant"] = model_state["variant"]

    part = {
        "id": f"part_{message_id}_0",
        "sessionID": session_id,
        "messageID": message_id,
        "type": "text",
        "text": text,
    }
    return {"info": info, "parts": [part]}


def _row_created_at(row: dict[str, Any]) -> int:
    """Return message creation time in milliseconds for transcript rows."""
    info = row.get("info") if isinstance(row, dict) else None
    if not isinstance(info, dict):
        return 0
    time_data = info.get("time")
    if not isinstance(time_data, dict):
        return 0
    created = time_data.get("created")
    return created if isinstance(created, int) else 0


def _normalize_text(value: str) -> str:
    """Normalize message text for loose deduplication."""
    return " ".join(value.split()).strip().lower()


def _row_text(row: dict[str, Any]) -> str:
    """Return normalized text content from transcript rows."""
    parts = row.get("parts") if isinstance(row, dict) else None
    if not isinstance(parts, list):
        return ""
    text_parts = [
        part.get("text", "")
        for part in parts
        if isinstance(part, dict)
        and part.get("type") == "text"
        and isinstance(part.get("text"), str)
    ]
    return _normalize_text("\n".join(text_parts)) if text_parts else ""


def _merge_transcript_with_legacy_users(
    rows: list[dict[str, Any]],
    legacy_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Merge older legacy user rows when a persisted transcript omitted them."""
    if not rows:
        return rows

    known_ids = {
        str(row["info"].get("id"))
        for row in rows
        if isinstance(row.get("info"), dict) and row["info"].get("id")
    }
    transcript_users_by_text: dict[str, list[int]] = {}
    for row in rows:
        info = row.get("info") if isinstance(row, dict) else None
        if not isinstance(info, dict) or info.get("role") != "user":
            continue
        text = _row_text(row)
        if not text:
            continue
        transcript_users_by_text.setdefault(text, []).append(_row_created_at(row))

    merged = list(rows)
    for row in legacy_rows:
        info = row.get("info") if isinstance(row, dict) else None
        if not isinstance(info, dict) or info.get("role") != "user":
            continue
        message_id = info.get("id")
        if isinstance(message_id, str) and message_id in known_ids:
            continue
        text = _row_text(row)
        created_at = _row_created_at(row)
        existing_times = transcript_users_by_text.get(text)
        if text and existing_times:
            if any(
                not existing_time
                or not created_at
                or abs(existing_time - created_at) <= 30_000
                for existing_time in existing_times
            ):
                continue
        merged.append(row)

    merged.sort(
        key=lambda row: (
            _row_created_at(row),
            str((row.get("info") or {}).get("id") or ""),
        )
    )
    return merged


def _normalize_todo_items(raw: Any) -> list[dict[str, str]]:
    """Normalize todo payloads to OpenCode-compatible Todo[] shape."""
    if not isinstance(raw, list):
        return []

    normalized: list[dict[str, str]] = []
    seen_ids: set[str] = set()
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            continue

        content_raw = item.get("content")
        if isinstance(content_raw, str):
            content = content_raw.strip()
        elif content_raw is None:
            content = ""
        else:
            content = str(content_raw).strip()
        if not content:
            continue

        status_raw = item.get("status", "pending")
        status = (
            status_raw.strip().lower()
            if isinstance(status_raw, str)
            else str(status_raw).strip().lower()
        )
        if status not in _TODO_STATUS_VALUES:
            status = "pending"

        priority_raw = item.get("priority", "medium")
        priority = (
            priority_raw.strip().lower()
            if isinstance(priority_raw, str)
            else str(priority_raw).strip().lower()
        )
        if priority not in _TODO_PRIORITY_VALUES:
            priority = "medium"

        todo_id_raw = item.get("id")
        todo_id = (
            todo_id_raw.strip()
            if isinstance(todo_id_raw, str) and todo_id_raw.strip()
            else f"todo_{index + 1}"
        )
        if todo_id in seen_ids:
            suffix = 2
            candidate = f"{todo_id}_{suffix}"
            while candidate in seen_ids:
                suffix += 1
                candidate = f"{todo_id}_{suffix}"
            todo_id = candidate

        seen_ids.add(todo_id)
        normalized.append(
            {
                "id": todo_id,
                "content": content,
                "status": status,
                "priority": priority,
            }
        )

    return normalized


def get_session_todo(core: Any, session_id: str) -> Optional[list[dict[str, str]]]:
    """Return OpenCode Todo[] for a session."""
    session, _manager = _find_session(core, session_id)
    if session is None:
        return None

    metadata = getattr(session, "metadata", None)
    if not isinstance(metadata, dict):
        return []

    return _normalize_todo_items(metadata.get(TODO_KEY))


def update_session_todo(
    core: Any, session_id: str, todos: Any
) -> Optional[list[dict[str, str]]]:
    """Persist OpenCode Todo[] for a session and return normalized items."""
    session, manager = _find_session(core, session_id)
    if session is None or manager is None:
        return None

    metadata = getattr(session, "metadata", None)
    if not isinstance(metadata, dict):
        metadata = {}
        session.metadata = metadata

    normalized = _normalize_todo_items(todos)
    metadata[TODO_KEY] = normalized

    manager.mark_session_modified(session.id)
    manager.save_session(session)
    return normalized


def get_session_messages(
    core: Any, session_id: str, *, limit: Optional[int] = None
) -> Optional[list[dict[str, Any]]]:
    """Return OpenCode MessageV2.WithParts[] for a session."""
    session, _manager = _find_session(core, session_id)
    if session is None:
        return None

    metadata = getattr(session, "metadata", {})
    transcript = metadata.get(TRANSCRIPT_KEY) if isinstance(metadata, dict) else None
    rows: list[dict[str, Any]] = []

    if isinstance(transcript, dict):
        messages = transcript.get("messages")
        order = transcript.get("order")
        if isinstance(messages, dict) and isinstance(order, list):
            for order_index, message_id in enumerate(order):
                entry = messages.get(message_id)
                if not isinstance(entry, dict):
                    continue
                info = entry.get("info")
                if not isinstance(info, dict):
                    fallback_agent_id = None
                    if isinstance(metadata, dict):
                        metadata_agent_id = metadata.get("agent_id")
                        if isinstance(metadata_agent_id, str):
                            fallback_agent_id = metadata_agent_id
                    info = _default_assistant_info(
                        core,
                        session_id,
                        str(message_id),
                        agent_id=fallback_agent_id,
                        session=session,
                        created_ms=order_index + 1,
                    )

                parts_map = entry.get("parts")
                part_order = entry.get("part_order")
                parts: list[dict[str, Any]] = []
                if isinstance(parts_map, dict) and isinstance(part_order, list):
                    for part_id in part_order:
                        part = parts_map.get(part_id)
                        if isinstance(part, dict):
                            parts.append(part)
                if parts:
                    rows.append({"info": info, "parts": parts})

    legacy_rows: list[dict[str, Any]] = []
    for message in getattr(session, "messages", []):
        role = getattr(message, "role", "")
        if role not in {"user", "assistant", "tool"}:
            continue
        legacy_rows.append(_legacy_message_to_with_parts(core, session, message))

    if rows:
        rows = _merge_transcript_with_legacy_users(rows, legacy_rows)
        if limit is not None and limit > 0:
            return rows[-limit:]
        return rows

    rows = legacy_rows

    if rows:
        first_id = ""
        last_id = ""
        first_info = rows[0].get("info") if isinstance(rows[0], dict) else None
        last_info = rows[-1].get("info") if isinstance(rows[-1], dict) else None
        if isinstance(first_info, dict):
            first_id = str(first_info.get("id") or "")
        if isinstance(last_info, dict):
            last_id = str(last_info.get("id") or "")
        logger.warning(
            "session.view.messages_legacy_fallback "
            "session=%s count=%s first=%s last=%s",
            session_id,
            len(rows),
            first_id,
            last_id,
        )

    if limit is not None and limit > 0:
        return rows[-limit:]
    return rows
