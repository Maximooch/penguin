"""Session-scoped model preferences for Telegram requests."""

from __future__ import annotations

import os
import tempfile
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from penguin.core_runtime.opencode_bridge import (
    SESSION_MODEL_ID_KEY,
    SESSION_PROVIDER_ID_KEY,
    SESSION_VARIANT_KEY,
)
from penguin.core_runtime.session_lookup import iter_session_managers
from penguin.llm.model_config import normalize_openai_service_tier
from penguin.llm.runtime import apply_reasoning_variant_override
from penguin.system.state import Session

SESSION_SERVICE_TIER_KEY = "_penguin_service_tier_v1"


class _UnchangedValue:
    """Sentinel type for omitted preference updates."""

    __slots__ = ()


UNCHANGED: Final = _UnchangedValue()


@dataclass(frozen=True)
class SessionRuntimePreferences:
    """Credential-free model preferences persisted on one Penguin session."""

    provider_id: str | None = None
    model_id: str | None = None
    reasoning_variant: str | None = None
    service_tier: str | None = None

    def __post_init__(self) -> None:
        provider_id = _normalize_optional_string(self.provider_id, lowercase=True)
        model_id = _normalize_optional_string(self.model_id)
        if provider_id and model_id:
            prefix, separator, remainder = model_id.partition("/")
            if separator and prefix.lower() == provider_id and remainder.strip():
                model_id = remainder.strip()
        if bool(provider_id) != bool(model_id):
            raise ValueError("provider_id and model_id must be set or cleared together")

        reasoning_variant = _normalize_optional_string(
            self.reasoning_variant,
            lowercase=True,
        )
        service_tier = _normalize_service_tier(self.service_tier)
        object.__setattr__(self, "provider_id", provider_id)
        object.__setattr__(self, "model_id", model_id)
        object.__setattr__(self, "reasoning_variant", reasoning_variant)
        object.__setattr__(self, "service_tier", service_tier)

    @property
    def qualified_model_id(self) -> str | None:
        """Return the provider-qualified model selector for core resolution."""

        if self.provider_id is None or self.model_id is None:
            return None
        return f"{self.provider_id}/{self.model_id}"

    @property
    def has_overrides(self) -> bool:
        """Return whether this session changes any request runtime setting."""

        return any(
            value is not None
            for value in (
                self.provider_id,
                self.model_id,
                self.reasoning_variant,
                self.service_tier,
            )
        )


@dataclass(frozen=True)
class _FileSnapshot:
    """Exact pre-save state for one session persistence artifact."""

    path: Path
    content: bytes | None
    mode: int | None


def load_session_runtime_preferences(
    core: Any,
    session_id: str,
) -> SessionRuntimePreferences | None:
    """Load runtime preferences for an existing session."""

    session, _manager = _find_session_without_activation(core, session_id)
    if session is None:
        return None
    metadata = getattr(session, "metadata", None)
    if not isinstance(metadata, dict):
        metadata = {}
    return SessionRuntimePreferences(
        provider_id=metadata.get(SESSION_PROVIDER_ID_KEY),
        model_id=metadata.get(SESSION_MODEL_ID_KEY),
        reasoning_variant=metadata.get(SESSION_VARIANT_KEY),
        service_tier=metadata.get(SESSION_SERVICE_TIER_KEY),
    )


def update_session_runtime_preferences(
    core: Any,
    session_id: str,
    *,
    provider_id: str | _UnchangedValue | None = UNCHANGED,
    model_id: str | _UnchangedValue | None = UNCHANGED,
    reasoning_variant: str | _UnchangedValue | None = UNCHANGED,
    service_tier: str | _UnchangedValue | None = UNCHANGED,
) -> SessionRuntimePreferences | None:
    """Update selected preferences, preserving fields left ``UNCHANGED``."""

    session, manager = _find_session_without_activation(core, session_id)
    if session is None or manager is None:
        return None
    original_metadata = getattr(session, "metadata", UNCHANGED)
    metadata = (
        deepcopy(original_metadata) if isinstance(original_metadata, dict) else {}
    )

    current = SessionRuntimePreferences(
        provider_id=metadata.get(SESSION_PROVIDER_ID_KEY),
        model_id=metadata.get(SESSION_MODEL_ID_KEY),
        reasoning_variant=metadata.get(SESSION_VARIANT_KEY),
        service_tier=metadata.get(SESSION_SERVICE_TIER_KEY),
    )
    updated = SessionRuntimePreferences(
        provider_id=_updated_value(current.provider_id, provider_id),
        model_id=_updated_value(current.model_id, model_id),
        reasoning_variant=_updated_value(
            current.reasoning_variant,
            reasoning_variant,
        ),
        service_tier=_updated_value(current.service_tier, service_tier),
    )
    if updated == current:
        return updated

    original_last_active = getattr(session, "last_active", UNCHANGED)
    original_current_session = getattr(manager, "current_session", UNCHANGED)
    original_cache_entry = _cached_entry(manager, session_id)
    original_index_entry = _session_index_entry(manager, session_id)
    original_files = _snapshot_session_files(manager, session_id)
    session.metadata = metadata
    _store_optional(metadata, SESSION_PROVIDER_ID_KEY, updated.provider_id)
    _store_optional(metadata, SESSION_MODEL_ID_KEY, updated.model_id)
    _store_optional(metadata, SESSION_VARIANT_KEY, updated.reasoning_variant)
    _store_optional(metadata, SESSION_SERVICE_TIER_KEY, updated.service_tier)
    try:
        manager.mark_session_modified(session.id)
        if manager.save_session(session) is False:
            raise RuntimeError(
                f"Unable to persist runtime preferences for {session.id}"
            )
    except Exception:
        _restore_attribute(session, "metadata", original_metadata)
        _restore_attribute(session, "last_active", original_last_active)
        _restore_cached_entry(manager, session_id, original_cache_entry)
        _restore_session_index_entry(manager, session_id, original_index_entry)
        try:
            _restore_session_files(original_files)
        except Exception as rollback_error:
            raise RuntimeError(
                f"Unable to roll back runtime preferences for {session.id}"
            ) from rollback_error
        raise
    finally:
        _restore_attribute(manager, "current_session", original_current_session)
    if original_cache_entry is UNCHANGED:
        _restore_cached_entry(manager, session_id, original_cache_entry)
    return updated


async def resolve_session_request_runtime(
    core: Any,
    session_id: str,
) -> tuple[Any, Any] | None:
    """Build fresh request-owned model overrides for one existing session."""

    preferences = load_session_runtime_preferences(core, session_id)
    if preferences is None or not preferences.has_overrides:
        return None

    resolver = getattr(core, "resolve_request_runtime", None)
    if not callable(resolver):
        raise RuntimeError("Penguin core cannot resolve a request runtime")
    model_config, api_client = await resolver(preferences.qualified_model_id)
    if model_config is getattr(core, "model_config", None):
        raise RuntimeError("Request runtime resolver returned the global model config")
    if api_client is getattr(core, "api_client", None):
        raise RuntimeError("Request runtime resolver returned the global API client")

    if preferences.reasoning_variant is not None:
        supported_efforts: Any = None
        capabilities_getter = getattr(api_client, "get_provider_capabilities", None)
        if callable(capabilities_getter):
            capabilities = capabilities_getter()
            supported_efforts = getattr(capabilities, "reasoning_efforts", None)
        apply_reasoning_variant_override(
            model_config,
            preferences.reasoning_variant,
            supported_efforts=supported_efforts,
        )
    if preferences.service_tier is not None:
        provider_id = str(getattr(model_config, "provider", "") or "").lower()
        if provider_id != "openai":
            raise ValueError("Fast mode is available only for OpenAI models")
        model_config.service_tier = _normalize_service_tier(preferences.service_tier)
    return model_config, api_client


def service_tier_for_fast_mode(enabled: bool | None) -> str | None:
    """Map Telegram's fast-mode switch to an explicit request service tier."""

    if enabled is None:
        return None
    return "priority" if enabled else "default"


def read_session_file_without_activation(
    manager: Any,
    session_id: str,
) -> Session | None:
    """Read and validate one exact primary session without manager activation."""

    if not _is_exact_session_id(session_id):
        return None
    path = _session_file_path(manager, session_id)
    if path is None:
        return None
    return _read_session_file(path, session_id)


def _updated_value(
    current: str | None,
    update: str | _UnchangedValue | None,
) -> str | None:
    if update is UNCHANGED:
        return current
    return update


def _store_optional(metadata: dict[str, Any], key: str, value: str | None) -> None:
    if value is None:
        metadata.pop(key, None)
    else:
        metadata[key] = value


def _normalize_optional_string(
    value: Any,
    *,
    lowercase: bool = False,
) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    if not normalized:
        return None
    return normalized.lower() if lowercase else normalized


def _normalize_service_tier(value: Any) -> str | None:
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    normalized = normalize_openai_service_tier(value)
    if normalized is None:
        raise ValueError(f"Unsupported OpenAI service tier: {value!r}")
    return normalized


def _find_session_without_activation(
    core: Any,
    session_id: Any,
) -> tuple[Any | None, Any | None]:
    """Find an exact session without calling the activating manager loader."""

    if not _is_exact_session_id(session_id):
        return None, None
    conversation_manager = getattr(core, "conversation_manager", core)
    for manager in iter_session_managers(conversation_manager):
        cached = getattr(manager, "sessions", {})
        if isinstance(cached, dict) and session_id in cached:
            entry = cached[session_id]
            session = entry[0] if isinstance(entry, tuple) and entry else entry
            if getattr(session, "id", None) == session_id:
                return session, manager
            return None, None

        current_session = getattr(manager, "current_session", None)
        if getattr(current_session, "id", None) == session_id:
            return current_session, manager

        path = _session_file_path(manager, session_id)
        if path is None:
            continue
        session = _read_session_file(path, session_id)
        if session is not None:
            return session, manager
        return None, None
    return None, None


def _session_file_path(manager: Any, session_id: str) -> Path | None:
    """Resolve an exact primary session path contained by its manager root."""

    path = _session_artifact_path(manager, session_id)
    if path is None or not path.is_file():
        return None
    return path


def _session_artifact_path(
    manager: Any,
    session_id: str,
    *,
    suffix: str = "",
) -> Path | None:
    """Resolve one path-confined persistence artifact, whether present or absent."""

    base_path = getattr(manager, "base_path", None)
    if base_path is None or getattr(manager, "format", "json") != "json":
        return None
    try:
        root = Path(base_path).resolve()
        candidate = root / f"{session_id}.json{suffix}"
        if candidate.is_symlink():
            return None
        resolved_parent = candidate.parent.resolve()
    except (OSError, TypeError):
        return None
    if resolved_parent != root:
        return None
    return candidate


def _read_session_file(path: Path, session_id: str) -> Session | None:
    """Read one primary session file without touching manager runtime state."""

    try:
        session = Session.from_json(path.read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError):
        return None
    if session.id != session_id or not session.validate():
        return None
    return session


def _is_exact_session_id(value: Any) -> bool:
    return (
        isinstance(value, str)
        and bool(value)
        and value == value.strip()
        and len(value) <= 512
    )


def _cached_entry(manager: Any, session_id: str) -> Any:
    cached = getattr(manager, "sessions", None)
    if not isinstance(cached, dict):
        return UNCHANGED
    return cached.get(session_id, UNCHANGED)


def _restore_cached_entry(manager: Any, session_id: str, entry: Any) -> None:
    cached = getattr(manager, "sessions", None)
    if not isinstance(cached, dict):
        return
    if entry is UNCHANGED:
        cached.pop(session_id, None)
    else:
        cached[session_id] = entry


def _session_index_entry(manager: Any, session_id: str) -> Any:
    index = getattr(manager, "session_index", None)
    if not isinstance(index, dict) or session_id not in index:
        return UNCHANGED
    return deepcopy(index[session_id])


def _restore_session_index_entry(
    manager: Any,
    session_id: str,
    entry: Any,
) -> None:
    index = getattr(manager, "session_index", None)
    if not isinstance(index, dict):
        return
    if entry is UNCHANGED:
        index.pop(session_id, None)
    else:
        index[session_id] = entry


def _restore_attribute(owner: Any, name: str, value: Any) -> None:
    if value is UNCHANGED:
        if hasattr(owner, name):
            delattr(owner, name)
    else:
        setattr(owner, name, value)


def _snapshot_session_files(
    manager: Any,
    session_id: str,
) -> tuple[_FileSnapshot, ...]:
    """Snapshot primary and backup files before a potentially partial save."""

    primary = _session_artifact_path(manager, session_id)
    backup = _session_artifact_path(manager, session_id, suffix=".bak")
    if primary is None or backup is None:
        return ()
    return (_snapshot_file(primary), _snapshot_file(backup))


def _snapshot_file(path: Path) -> _FileSnapshot:
    if not path.exists():
        return _FileSnapshot(path=path, content=None, mode=None)
    if not path.is_file():
        raise RuntimeError(f"Session persistence path is not a file: {path}")
    try:
        return _FileSnapshot(
            path=path,
            content=path.read_bytes(),
            mode=path.stat().st_mode & 0o777,
        )
    except OSError as exc:
        raise RuntimeError(f"Unable to snapshot session persistence: {path}") from exc


def _restore_session_files(snapshots: tuple[_FileSnapshot, ...]) -> None:
    for snapshot in snapshots:
        _restore_file(snapshot)


def _restore_file(snapshot: _FileSnapshot) -> None:
    path = snapshot.path
    if snapshot.content is None:
        if path.exists() or path.is_symlink():
            if not path.is_file() and not path.is_symlink():
                raise RuntimeError(f"Cannot remove non-file session artifact: {path}")
            path.unlink()
            _sync_directory(path.parent)
        return

    descriptor, temporary_name = tempfile.mkstemp(
        dir=str(path.parent),
        prefix=f".{path.name}.telegram-rollback-",
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(snapshot.content)
            handle.flush()
            os.fsync(handle.fileno())
        if snapshot.mode is not None:
            temporary_path.chmod(snapshot.mode)
        os.replace(temporary_path, path)
        _sync_directory(path.parent)
    finally:
        if temporary_path.exists():
            temporary_path.unlink()


def _sync_directory(directory: Path) -> None:
    descriptor = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


__all__ = [
    "SESSION_SERVICE_TIER_KEY",
    "UNCHANGED",
    "SessionRuntimePreferences",
    "load_session_runtime_preferences",
    "read_session_file_without_activation",
    "resolve_session_request_runtime",
    "service_tier_for_fast_mode",
    "update_session_runtime_preferences",
]
