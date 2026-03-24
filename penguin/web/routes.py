from typing import Any, Dict, List, Optional
from fastapi import (
    APIRouter,
    Depends,
    WebSocket,
    WebSocketDisconnect,
    HTTPException,
    BackgroundTasks,
    UploadFile,
    File,
    Form,
    Query,
)  # type: ignore
from pydantic import BaseModel  # type: ignore
from dataclasses import asdict  # type: ignore
from datetime import datetime  # type: ignore
from collections import OrderedDict
import asyncio
import base64
import copy
import json
import logging
import mimetypes
import os
from pathlib import Path
import re
import shutil
import tempfile
import time
from threading import Lock
import uuid
from urllib.parse import unquote, urlparse
import websockets
import httpx

from penguin.config import WORKSPACE_PATH
from penguin.core import PenguinCore
from penguin import __version__
from penguin.constants import get_engine_max_iterations_default
from penguin.utils.events import EventBus as UtilsEventBus
from penguin.cli.events import EventBus as CLIEventBus, EventType
from penguin.web.health import get_health_monitor
from penguin.web.services.configuration import (
    runtime_config_payload,
    settings_locations_payload,
)
from penguin.web.services.conversations import (
    create_conversation_payload,
    get_conversation_payload,
    list_conversations_payload,
)
from penguin.web.services.session_view import (
    create_session_info,
    get_session_diff,
    get_session_info,
    get_session_metadata_title,
    get_session_messages,
    get_session_todo,
    list_session_infos,
    list_session_statuses,
    remove_session_info,
    update_session_info,
)
from penguin.web.services.session_fork import fork_session
from penguin.web.services.session_revert import revert_session, unrevert_session
from penguin.web.services.session_summary import summarize_session_title
from penguin.web.services.system_status import (
    get_formatter_status,
    get_lsp_status,
    get_path_info,
    get_vcs_info,
)
from penguin.web.services.opencode_provider import (
    apply_auth_to_runtime,
    build_config_payload,
    build_config_providers_payload,
    build_provider_list_payload,
    get_provider_auth_records,
    provider_auth_methods,
    provider_oauth_authorize,
    provider_oauth_callback,
    remove_provider_auth_record,
    set_provider_auth_record,
    supported_native_reasoning_variants,
)
from penguin.system.execution_context import (
    ExecutionContext,
    execution_context_scope,
    normalize_directory,
)
from penguin.utils.errors import AgentNotFoundError, PenguinError

logger = logging.getLogger(__name__)


def _format_error_response(error: Exception, status_code: int = 500) -> HTTPException:
    """Format error as HTTPException with structured error detail."""
    if isinstance(error, PenguinError):
        return HTTPException(status_code=status_code, detail={"error": error.to_dict()})
    else:
        # Wrap non-Penguin errors
        penguin_error = PenguinError(
            message=str(error),
            code="INTERNAL_ERROR",
            recoverable=False,
            suggested_action="contact_support",
        )
        return HTTPException(
            status_code=status_code, detail={"error": penguin_error.to_dict()}
        )


MAX_IMAGES_PER_REQUEST = 10

_FIND_FILE_CACHE_TTL_SECONDS = 5.0
_FIND_FILE_CACHE_MAX_DIRECTORIES = 16
_FIND_FILE_SKIP_DIR_NAMES = {
    ".git",
    ".hg",
    ".svn",
    "node_modules",
    "dist",
    "build",
    "target",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".venv",
    "venv",
}
_FIND_FILE_INDEX_CACHE: "OrderedDict[str, Dict[str, Any]]" = OrderedDict()
_FIND_FILE_INDEX_CACHE_LOCK = Lock()


def _remember_last_scoped_directory(
    core: PenguinCore, directory: Optional[str]
) -> Optional[str]:
    """Remember the latest valid scoped directory for fallback lookups."""
    normalized = normalize_directory(directory)
    if not normalized:
        return None
    setattr(core, "_opencode_last_scoped_directory", normalized)
    return normalized


def _get_last_scoped_directory(core: PenguinCore) -> Optional[str]:
    """Return previously scoped directory if still valid."""
    return normalize_directory(getattr(core, "_opencode_last_scoped_directory", None))


def _resolve_scoped_directory_for_find(
    core: PenguinCore,
    *,
    directory: Optional[str],
    session_id: Optional[str],
    conversation_id: Optional[str],
) -> Optional[str]:
    """Resolve find scope using explicit, session, remembered, and runtime roots."""
    explicit = _remember_last_scoped_directory(core, directory)
    if explicit:
        return explicit

    effective_session = (
        session_id.strip()
        if isinstance(session_id, str) and session_id.strip()
        else (
            conversation_id.strip()
            if isinstance(conversation_id, str) and conversation_id.strip()
            else None
        )
    )
    if effective_session:
        session_dirs = _ensure_session_directory_map(core)
        mapped = normalize_directory(session_dirs.get(effective_session))
        if mapped:
            _remember_last_scoped_directory(core, mapped)
            return mapped

    remembered = _get_last_scoped_directory(core)
    if remembered:
        return remembered

    runtime = getattr(core, "runtime_config", None)
    runtime_fallback = normalize_directory(
        getattr(runtime, "active_root", None)
        or getattr(runtime, "project_root", None)
        or getattr(runtime, "workspace_root", None)
    )
    if runtime_fallback:
        _remember_last_scoped_directory(core, runtime_fallback)
        return runtime_fallback

    workspace_fallback = normalize_directory(WORKSPACE_PATH)
    if workspace_fallback:
        _remember_last_scoped_directory(core, workspace_fallback)
    return workspace_fallback


def _ensure_session_directory_map(core: PenguinCore) -> dict[str, str]:
    """Ensure core has a session->directory map and return it."""
    session_dirs = getattr(core, "_opencode_session_directories", None)
    if not isinstance(session_dirs, dict):
        session_dirs = {}
        setattr(core, "_opencode_session_directories", session_dirs)
    return session_dirs


def _bind_session_directory(
    core: PenguinCore,
    session_id: Optional[str],
    directory: Optional[str],
) -> Optional[str]:
    """Bind directory to a session id with immutable-by-default semantics."""
    if directory and not normalize_directory(directory):
        raise HTTPException(
            status_code=400,
            detail=f"Invalid directory: {directory}",
        )

    if not session_id:
        return _remember_last_scoped_directory(core, directory)

    session_dirs = _ensure_session_directory_map(core)
    existing = normalize_directory(session_dirs.get(session_id))
    requested = normalize_directory(directory)

    if existing:
        if requested and Path(existing) != Path(requested):
            try:
                if Path(existing).samefile(requested):
                    _remember_last_scoped_directory(core, existing)
                    return existing
            except Exception:
                pass
            raise HTTPException(
                status_code=409,
                detail=(
                    f"Session '{session_id}' is already bound to '{existing}' and "
                    f"cannot be reassigned to '{requested}'"
                ),
            )
        _remember_last_scoped_directory(core, existing)
        return existing

    if requested:
        session_dirs[session_id] = requested
        _remember_last_scoped_directory(core, requested)
        return requested

    return None


def _build_execution_context(
    core: PenguinCore,
    *,
    session_id: Optional[str],
    conversation_id: Optional[str],
    agent_id: Optional[str],
    agent_mode: Optional[str],
    directory: Optional[str],
) -> ExecutionContext:
    """Create request-scoped execution context for concurrent web sessions."""
    path_info = get_path_info(core, directory=directory, session_id=session_id)
    effective_directory = normalize_directory(path_info.get("directory"))
    return ExecutionContext(
        session_id=session_id,
        conversation_id=conversation_id,
        agent_id=agent_id,
        agent_mode=agent_mode,
        directory=effective_directory,
        project_root=effective_directory,
        workspace_root=effective_directory,
        request_id=str(uuid.uuid4()),
    )


def _normalize_agent_mode(value: Any) -> Optional[str]:
    if not isinstance(value, str):
        return None
    normalized = value.strip().lower()
    if normalized in {"plan", "build"}:
        return normalized
    return None


def _resolve_agent_mode(
    core: PenguinCore,
    requested_mode: Optional[str],
    session_id: Optional[str],
) -> str:
    normalized_request = _normalize_agent_mode(requested_mode)
    if normalized_request:
        return normalized_request

    if isinstance(session_id, str) and session_id:
        info = get_session_info(core, session_id)
        if isinstance(info, dict):
            normalized_session = _normalize_agent_mode(info.get("agent_mode"))
            if normalized_session:
                return normalized_session

    return "build"


async def _persist_session_agent_mode(
    core: PenguinCore,
    session_id: Optional[str],
    agent_mode: Optional[str],
) -> None:
    normalized_mode = _normalize_agent_mode(agent_mode)
    if not normalized_mode:
        return
    if not isinstance(session_id, str) or not session_id:
        return

    existing = get_session_info(core, session_id)
    if not isinstance(existing, dict):
        return
    existing_mode = _normalize_agent_mode(existing.get("agent_mode")) or "build"
    if existing_mode == normalized_mode:
        return

    updated = update_session_info(core, session_id, agent_mode=normalized_mode)
    if isinstance(updated, dict):
        await _emit_session_updated_event(core, updated)


async def _emit_session_event(
    core: PenguinCore,
    event_type: str,
    info: Dict[str, Any],
) -> None:
    """Emit an OpenCode-shaped session lifecycle event."""
    event_bus = getattr(core, "event_bus", None)
    emit = getattr(event_bus, "emit", None)
    if not callable(emit):
        return

    session_id = info.get("id") if isinstance(info, dict) else None
    properties: Dict[str, Any] = {"info": info}
    if isinstance(session_id, str) and session_id:
        properties["sessionID"] = session_id

    try:
        await emit(
            "opencode_event",
            {
                "type": event_type,
                "properties": properties,
            },
        )
    except Exception:
        logger.debug("Failed to emit %s event", event_type, exc_info=True)


async def _emit_session_created_event(core: PenguinCore, info: Dict[str, Any]) -> None:
    """Emit OpenCode-shaped session.created event."""
    await _emit_session_event(core, "session.created", info)


async def _emit_session_updated_event(core: PenguinCore, info: Dict[str, Any]) -> None:
    """Emit OpenCode-shaped session.updated event."""
    await _emit_session_event(core, "session.updated", info)


async def _emit_session_deleted_event(core: PenguinCore, info: Dict[str, Any]) -> None:
    """Emit OpenCode-shaped session.deleted event."""
    await _emit_session_event(core, "session.deleted", info)


async def _emit_session_diff_event(
    core: PenguinCore, session_id: str, diff: List[Dict[str, Any]]
) -> None:
    emit = getattr(getattr(core, "event_bus", None), "emit", None)
    if not callable(emit):
        return
    try:
        await emit(
            "opencode_event",
            {
                "type": "session.diff",
                "properties": {
                    "sessionID": session_id,
                    "diff": diff,
                },
            },
        )
    except Exception:
        logger.debug("Failed to emit session.diff event", exc_info=True)


def _title_log_info(message: str, *args: Any) -> None:
    """Log title/summarize events via app and uvicorn logger."""
    logger.info(message, *args)
    uvicorn_logger = logging.getLogger("uvicorn.error")
    if uvicorn_logger is not logger:
        uvicorn_logger.info(message, *args)


def _request_log_info(message: str, *args: Any) -> None:
    """Log request-level observability via app and uvicorn logger."""
    logger.info(message, *args)
    uvicorn_logger = logging.getLogger("uvicorn.error")
    if uvicorn_logger is not logger:
        uvicorn_logger.info(message, *args)


async def _refresh_session_title_if_default(
    core: PenguinCore,
    session_id: str,
    *,
    provider_id: Optional[str] = None,
    model_id: Optional[str] = None,
    fallback_text: Optional[str] = None,
) -> None:
    """Generate and emit a better title only for default-titled sessions."""
    max_attempts = 4
    for attempt in range(1, max_attempts + 1):
        existing = get_session_info(core, session_id)
        if not isinstance(existing, dict):
            _title_log_info(
                "session.title.auto_refresh session=%s attempt=%s status=missing_session",
                session_id,
                attempt,
            )
            return

        explicit_title = get_session_metadata_title(core, session_id)
        if isinstance(explicit_title, str) and explicit_title:
            _title_log_info(
                "session.title.auto_refresh session=%s attempt=%s status=already_titled title=%r",
                session_id,
                attempt,
                explicit_title,
            )
            return

        result = await summarize_session_title(
            core,
            session_id,
            provider_id=provider_id,
            model_id=model_id,
            fallback_text=fallback_text,
        )
        if not isinstance(result, dict):
            _title_log_info(
                "session.title.auto_refresh session=%s attempt=%s status=no_result",
                session_id,
                attempt,
            )
            return

        changed = bool(result.get("changed"))
        info = result.get("info")
        source = result.get("source")
        snippet_count = int(result.get("snippet_count", 0))
        title = result.get("title")
        used_fallback = bool(result.get("used_fallback_text"))

        if changed and isinstance(info, dict):
            await _emit_session_updated_event(core, info)
            _title_log_info(
                "session.title.auto_refresh session=%s attempt=%s status=updated source=%s snippets=%s fallback=%s title=%r",
                session_id,
                attempt,
                source,
                snippet_count,
                used_fallback,
                title,
            )
            return

        if snippet_count <= 0 and attempt < max_attempts:
            _title_log_info(
                "session.title.auto_refresh session=%s attempt=%s status=retry_no_user_snippets",
                session_id,
                attempt,
            )
            await asyncio.sleep(0.15)
            continue

        _title_log_info(
            "session.title.auto_refresh session=%s attempt=%s status=unchanged source=%s snippets=%s fallback=%s title=%r",
            session_id,
            attempt,
            source,
            snippet_count,
            used_fallback,
            title,
        )
        return


def _queue_session_title_refresh(
    core: PenguinCore,
    session_id: str,
    *,
    provider_id: Optional[str] = None,
    model_id: Optional[str] = None,
    fallback_text: Optional[str] = None,
) -> None:
    """Schedule non-blocking title refresh, deduped per session."""
    if not isinstance(session_id, str) or not session_id.strip():
        return

    tasks = getattr(core, "_opencode_title_tasks", None)
    if not isinstance(tasks, dict):
        tasks = {}
        setattr(core, "_opencode_title_tasks", tasks)

    running = tasks.get(session_id)
    if isinstance(running, asyncio.Task) and not running.done():
        _title_log_info(
            "session.title.auto_refresh session=%s status=skip_already_running",
            session_id,
        )
        return

    task = asyncio.create_task(
        _refresh_session_title_if_default(
            core,
            session_id,
            provider_id=provider_id,
            model_id=model_id,
            fallback_text=fallback_text,
        )
    )
    tasks[session_id] = task
    _title_log_info(
        "session.title.auto_refresh session=%s status=scheduled", session_id
    )

    def _done_callback(done_task: asyncio.Task[Any]) -> None:
        task_map = getattr(core, "_opencode_title_tasks", None)
        if isinstance(task_map, dict) and task_map.get(session_id) is done_task:
            task_map.pop(session_id, None)
        try:
            done_task.result()
        except Exception:
            logger.debug(
                "Background session title refresh failed for %s",
                session_id,
                exc_info=True,
            )

    task.add_done_callback(_done_callback)


class MessageRequest(BaseModel):
    text: str
    conversation_id: Optional[str] = None
    session_id: Optional[str] = None
    client_message_id: Optional[str] = None
    context: Optional[Dict[str, Any]] = None
    context_files: Optional[List[str]] = None
    streaming: Optional[bool] = True
    max_iterations: Optional[int] = None  # Uses MAX_TASK_ITERATIONS if not specified
    image_paths: Optional[List[str]] = None  # Multiple images supported (max 10)
    include_reasoning: Optional[bool] = False
    agent_id: Optional[str] = None
    agent_mode: Optional[str] = None
    directory: Optional[str] = None
    model: Optional[str] = None
    variant: Optional[str] = None
    parts: Optional[List[Dict[str, Any]]] = None


_REASONING_EFFORT_VARIANTS = {"none", "minimal", "low", "medium", "high", "xhigh"}
_REASONING_MAX_VARIANTS = {"max"}
_REASONING_DISABLE_VARIANTS = {"off"}
_INLINE_FILE_REFERENCE_PATTERN = re.compile(
    r"(?<![\w`])@(\.?[^\s`,.]*(?:\.[^\s`,.]+)*)"
)


def _apply_reasoning_variant_override(
    core: PenguinCore,
    variant: Optional[str],
) -> Optional[Dict[str, Any]]:
    model_config = getattr(core, "model_config", None)
    if model_config is None:
        return None

    value = variant.strip().lower() if isinstance(variant, str) else ""
    if not value:
        return None

    snapshot = {
        "reasoning_enabled": getattr(model_config, "reasoning_enabled", False),
        "reasoning_effort": getattr(model_config, "reasoning_effort", None),
        "reasoning_max_tokens": getattr(model_config, "reasoning_max_tokens", None),
        "reasoning_exclude": getattr(model_config, "reasoning_exclude", False),
        "supports_reasoning": getattr(model_config, "supports_reasoning", None),
        "_has_supports_reasoning": hasattr(model_config, "supports_reasoning"),
    }

    if value in _REASONING_DISABLE_VARIANTS:
        model_config.reasoning_enabled = False
        model_config.reasoning_effort = None
        model_config.reasoning_max_tokens = None
        model_config.reasoning_exclude = False
        return snapshot

    provider_id = str(getattr(model_config, "provider", "") or "").strip().lower()
    model_id = str(getattr(model_config, "model", "") or "").strip()

    if provider_id in {"openai", "anthropic"}:
        supported_native_variants = set(
            supported_native_reasoning_variants(provider_id, model_id)
        )
        if value not in supported_native_variants:
            logger.debug(
                "Ignoring unsupported native reasoning variant '%s' for %s/%s (supported=%s)",
                value,
                provider_id,
                model_id,
                sorted(supported_native_variants),
            )
            return None

        model_config.reasoning_enabled = True
        model_config.reasoning_effort = value
        model_config.reasoning_max_tokens = None
        model_config.reasoning_exclude = False
        model_config.supports_reasoning = True
        return snapshot

    if value in _REASONING_EFFORT_VARIANTS:
        model_config.reasoning_enabled = True
        model_config.reasoning_effort = value
        model_config.reasoning_max_tokens = None
        model_config.reasoning_exclude = False
        model_config.supports_reasoning = True
        return snapshot

    if value in _REASONING_MAX_VARIANTS:
        model_config.reasoning_enabled = True
        model_config.reasoning_effort = None
        model_config.reasoning_max_tokens = 32000
        model_config.reasoning_exclude = False
        model_config.supports_reasoning = True
        return snapshot

    logger.debug("Ignoring unsupported reasoning variant '%s'", value)
    return None


def _restore_reasoning_variant_override(
    core: PenguinCore,
    snapshot: Optional[Dict[str, Any]],
) -> None:
    if not isinstance(snapshot, dict):
        return

    model_config = getattr(core, "model_config", None)
    if model_config is None:
        return

    model_config.reasoning_enabled = bool(snapshot.get("reasoning_enabled", False))
    model_config.reasoning_effort = snapshot.get("reasoning_effort")
    model_config.reasoning_max_tokens = snapshot.get("reasoning_max_tokens")
    model_config.reasoning_exclude = bool(snapshot.get("reasoning_exclude", False))
    if snapshot.get("_has_supports_reasoning"):
        model_config.supports_reasoning = snapshot.get("supports_reasoning")
    elif hasattr(model_config, "supports_reasoning"):
        try:
            delattr(model_config, "supports_reasoning")
        except Exception:
            pass


def _resolve_context_file_path(
    value: Optional[str],
    *,
    directory: Optional[str],
) -> Optional[str]:
    """Resolve local file paths and file URLs to absolute existing files."""
    if not isinstance(value, str):
        return None

    candidate = value.strip()
    if not candidate:
        return None
    if candidate.startswith("data:"):
        return None

    parsed = urlparse(candidate)
    if parsed.scheme in {"http", "https"}:
        return None
    if parsed.scheme == "file":
        if not parsed.path:
            return None
        candidate = unquote(parsed.path)
    elif "://" in candidate:
        return None

    candidate = candidate.split("#", 1)[0].split("?", 1)[0].strip()
    if not candidate:
        return None

    base_directory = normalize_directory(directory)
    try:
        if candidate.startswith("~/"):
            resolved = Path(candidate).expanduser().resolve()
        elif os.path.isabs(candidate):
            resolved = Path(candidate).resolve()
        elif base_directory:
            resolved = (Path(base_directory) / candidate).resolve()
        else:
            resolved = Path(candidate).resolve()
    except Exception:
        return None

    if not resolved.exists() or not resolved.is_file():
        return None
    return str(resolved)


def _normalize_context_files(
    context_files: Optional[List[str]],
    *,
    directory: Optional[str],
) -> List[str]:
    """Normalize context files through the shared file resolver."""
    normalized: List[str] = []
    seen: set[str] = set()

    for item in context_files or []:
        if not isinstance(item, str):
            continue
        raw_value = item.strip()
        if not raw_value:
            continue

        resolved = _resolve_context_file_path(raw_value, directory=directory)
        candidate = resolved or raw_value
        if candidate in seen:
            continue
        seen.add(candidate)
        normalized.append(candidate)

    return normalized


def _extract_paths_from_parts(
    parts: Optional[List[Dict[str, Any]]],
    *,
    directory: Optional[str],
) -> tuple[List[str], List[str]]:
    """Extract context file paths and image payloads from OpenCode parts."""
    if not isinstance(parts, list):
        return [], []

    context_files: List[str] = []
    image_paths: List[str] = []

    for part in parts:
        if not isinstance(part, dict):
            continue
        if str(part.get("type", "")).strip().lower() != "file":
            continue

        mime = part.get("mime")
        mime_value = mime.strip().lower() if isinstance(mime, str) else ""

        source = part.get("source")
        source_path = source.get("path") if isinstance(source, dict) else None
        source_path_value = source_path.strip() if isinstance(source_path, str) else ""

        url = part.get("url")
        url_value = url.strip() if isinstance(url, str) else ""

        source_image_selected = False
        if source_path_value:
            if mime_value.startswith("image/"):
                candidate = (
                    os.path.isabs(source_path_value)
                    or source_path_value.startswith("./")
                    or source_path_value.startswith("../")
                    or source_path_value.startswith("~/")
                )
                if (
                    candidate
                    and not source_path_value.startswith("data:")
                    and source_path_value not in image_paths
                ):
                    image_paths.append(source_path_value)
                    source_image_selected = True
            elif not source_path_value.startswith("data:"):
                resolved = _resolve_context_file_path(
                    source_path_value,
                    directory=directory,
                )
                if resolved and resolved not in context_files:
                    context_files.append(resolved)
                    continue

        if not mime_value.startswith("image/") and url_value:
            resolved_from_url = _resolve_context_file_path(
                url_value,
                directory=directory,
            )
            if resolved_from_url and resolved_from_url not in context_files:
                context_files.append(resolved_from_url)
                continue

        if source_image_selected:
            continue

        if not url_value:
            continue
        if not (mime_value.startswith("image/") or url_value.startswith("data:image/")):
            continue
        if url_value not in image_paths:
            image_paths.append(url_value)

    return context_files, image_paths


def _extract_inline_file_references(text: Optional[str]) -> List[str]:
    """Extract inline @file references using OpenCode-compatible matching."""
    if not isinstance(text, str) or not text.strip():
        return []

    references: List[str] = []
    seen: set[str] = set()
    for match in _INLINE_FILE_REFERENCE_PATTERN.finditer(text):
        candidate = (match.group(1) or "").strip()
        if not candidate or candidate in seen:
            continue
        seen.add(candidate)
        references.append(candidate)
    return references


def _resolve_inline_file_reference(
    reference: str,
    *,
    directory: Optional[str],
) -> Optional[str]:
    """Resolve an inline @file reference to an existing file path."""
    value = reference.strip()
    if not value:
        return None
    value = value.split("#", 1)[0].split("?", 1)[0].strip()
    if not value:
        return None
    return _resolve_context_file_path(value, directory=directory)


def _extract_context_files_from_text(
    text: Optional[str],
    *,
    directory: Optional[str],
) -> List[str]:
    """Resolve existing inline @file references into context file paths."""
    resolved_files: List[str] = []
    seen: set[str] = set()
    for reference in _extract_inline_file_references(text):
        resolved = _resolve_inline_file_reference(reference, directory=directory)
        if not resolved or resolved in seen:
            continue
        seen.add(resolved)
        resolved_files.append(resolved)
    return resolved_files


def _normalize_repo_relative(path_value: str) -> str:
    """Normalize a relative path to POSIX separators."""
    return path_value.replace(os.sep, "/") if os.sep != "/" else path_value


def _scan_find_file_index(directory: str) -> tuple[List[str], List[str]]:
    """Build a lightweight file/dir index for fast autocomplete searches."""
    root = Path(directory).expanduser().resolve()
    if not root.exists() or not root.is_dir():
        return [], []

    files: List[str] = []
    dirs: List[str] = []

    for current_dir, dirnames, filenames in os.walk(str(root), topdown=True):
        dirnames[:] = [
            name
            for name in dirnames
            if name not in _FIND_FILE_SKIP_DIR_NAMES and name not in {".", ".."}
        ]

        current_path = Path(current_dir)
        try:
            relative_dir = current_path.relative_to(root)
        except ValueError:
            continue

        for dirname in dirnames:
            rel = (
                (relative_dir / dirname).as_posix()
                if str(relative_dir) != "."
                else dirname
            )
            dirs.append(f"{_normalize_repo_relative(rel).rstrip('/')}/")

        for filename in filenames:
            rel = (
                (relative_dir / filename).as_posix()
                if str(relative_dir) != "."
                else filename
            )
            files.append(_normalize_repo_relative(rel).rstrip("/"))

    files.sort()
    dirs.sort()
    return files, dirs


def _get_find_file_index(directory: str) -> tuple[List[str], List[str]]:
    """Return cached file index for a directory, refreshing on TTL expiry."""
    normalized = normalize_directory(directory)
    if not normalized:
        return [], []

    now = time.monotonic()
    with _FIND_FILE_INDEX_CACHE_LOCK:
        cached = _FIND_FILE_INDEX_CACHE.get(normalized)
        if isinstance(cached, dict) and float(cached.get("expires_at", 0.0)) > now:
            _FIND_FILE_INDEX_CACHE.move_to_end(normalized)
            return list(cached.get("files") or []), list(cached.get("dirs") or [])

    files, dirs = _scan_find_file_index(normalized)

    with _FIND_FILE_INDEX_CACHE_LOCK:
        _FIND_FILE_INDEX_CACHE[normalized] = {
            "expires_at": now + _FIND_FILE_CACHE_TTL_SECONDS,
            "files": files,
            "dirs": dirs,
        }
        _FIND_FILE_INDEX_CACHE.move_to_end(normalized)
        while len(_FIND_FILE_INDEX_CACHE) > _FIND_FILE_CACHE_MAX_DIRECTORIES:
            _FIND_FILE_INDEX_CACHE.popitem(last=False)

    return files, dirs


def _is_hidden_path(path_value: str) -> bool:
    """Return whether any segment is hidden (starts with '.')."""
    normalized = path_value.replace("\\", "/").rstrip("/")
    return any(
        segment.startswith(".") and len(segment) > 1
        for segment in normalized.split("/")
        if segment
    )


def _query_targets_hidden_paths(query: str) -> bool:
    """Return whether the query intentionally targets hidden paths."""
    return query.startswith(".") or "/." in query


def _sort_hidden_last(items: List[str], query: str) -> List[str]:
    """Sort hidden entries to the end unless query targets hidden paths."""
    if _query_targets_hidden_paths(query):
        return items

    visible: List[str] = []
    hidden: List[str] = []
    for item in items:
        if _is_hidden_path(item):
            hidden.append(item)
        else:
            visible.append(item)
    return [*visible, *hidden]


def _subsequence_gap(query: str, candidate: str) -> Optional[int]:
    """Return gap score if query is a subsequence of candidate."""
    cursor = 0
    last = -1
    gap = 0
    for char in query:
        found = candidate.find(char, cursor)
        if found < 0:
            return None
        if last >= 0:
            gap += max(found - last - 1, 0)
        last = found
        cursor = found + 1
    return gap


def _find_file_match_score(
    query: str, candidate: str
) -> Optional[tuple[int, int, int, str]]:
    """Compute an OpenCode-like fuzzy ranking score for path suggestions."""
    query_l = query.lower()
    candidate_l = candidate.lower()
    basename_l = candidate_l.rstrip("/").split("/")[-1]

    if candidate_l == query_l or basename_l == query_l:
        return (0, 0, len(candidate), candidate_l)
    if basename_l.startswith(query_l):
        return (1, 0, len(candidate), candidate_l)
    if candidate_l.startswith(query_l):
        return (2, 0, len(candidate), candidate_l)

    basename_idx = basename_l.find(query_l)
    if basename_idx >= 0:
        return (3, basename_idx, len(candidate), candidate_l)
    candidate_idx = candidate_l.find(query_l)
    if candidate_idx >= 0:
        return (4, candidate_idx, len(candidate), candidate_l)

    basename_gap = _subsequence_gap(query_l, basename_l)
    if basename_gap is not None:
        return (5, basename_gap, len(candidate), candidate_l)

    candidate_gap = _subsequence_gap(query_l, candidate_l)
    if candidate_gap is not None:
        return (6, candidate_gap, len(candidate), candidate_l)

    return None


def _search_find_file_items(items: List[str], query: str, limit: int) -> List[str]:
    """Search indexed file/dir items with deterministic fuzzy ranking."""
    normalized_query = query.strip().lower()
    if not normalized_query:
        return items[:limit]

    ranked: List[tuple[tuple[int, int, int, str], str]] = []
    for item in items:
        score = _find_file_match_score(normalized_query, item)
        if score is None:
            continue
        ranked.append((score, item))

    ranked.sort(key=lambda entry: entry[0])
    return [item for _, item in ranked[:limit]]


def _materialize_image_paths(
    image_paths: List[str],
    *,
    directory: Optional[str],
) -> tuple[List[str], List[str]]:
    """Convert data URLs to temporary files and return usable paths.

    Returns:
        Tuple of (resolved image paths, temp file paths to clean up).
    """
    resolved: List[str] = []
    temp_files: List[str] = []

    target_directory = normalize_directory(directory)
    temp_root = (
        Path(target_directory) / ".penguin" / "tmp_images"
        if target_directory
        else Path(tempfile.gettempdir()) / "penguin_tmp_images"
    )

    for item in image_paths:
        value = item.strip() if isinstance(item, str) else ""
        if not value:
            continue

        candidate = value
        if value.startswith("file://"):
            parsed = urlparse(value)
            candidate = unquote(parsed.path) if parsed.path else value

        if not value.startswith("data:"):
            if not os.path.isabs(candidate) and target_directory:
                candidate = str((Path(target_directory) / candidate).resolve())
            resolved.append(candidate)
            continue

        if "," not in value:
            resolved.append(value)
            continue

        header, encoded = value.split(",", 1)
        if not header.startswith("data:") or ";base64" not in header.lower():
            resolved.append(value)
            continue

        mime = header[5:].split(";", 1)[0].strip().lower() or "application/octet-stream"
        suffix = mimetypes.guess_extension(mime) or ".bin"
        if suffix == ".jpe":
            suffix = ".jpg"

        try:
            payload = base64.b64decode(encoded, validate=False)
        except Exception:
            resolved.append(value)
            continue

        try:
            temp_root.mkdir(parents=True, exist_ok=True)
            temp_path = temp_root / f"upload_{uuid.uuid4().hex}{suffix}"
            temp_path.write_bytes(payload)
            temp_str = str(temp_path)
            resolved.append(temp_str)
            temp_files.append(temp_str)
        except Exception:
            resolved.append(value)

    return resolved, temp_files


class StreamResponse(BaseModel):
    id: str
    event: str
    data: Dict[str, Any]


class ProjectRequest(BaseModel):
    name: str
    description: Optional[str] = None


class TaskRequest(BaseModel):
    name: str
    description: Optional[str] = None
    continuous: bool = False
    time_limit: Optional[int] = None


class ContextFileRequest(BaseModel):
    file_path: str


# New models for checkpoint management
class CheckpointCreateRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None


class CheckpointBranchRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None


# New models for model management
class ModelLoadRequest(BaseModel):
    model_id: str


class SystemConfigRequest(BaseModel):
    path: str


# LLM Configuration for Link integration
class LLMConfigRequest(BaseModel):
    """Request model for configuring LLM endpoint and Link integration."""

    base_url: Optional[str] = None  # LLM API endpoint (e.g., Link proxy URL)
    link_user_id: Optional[str] = None  # Link user ID for billing attribution
    link_session_id: Optional[str] = None  # Link session ID for tracking
    link_agent_id: Optional[str] = None  # Link agent ID for multi-agent scenarios
    link_workspace_id: Optional[str] = None  # Link workspace ID for org billing
    link_api_key: Optional[str] = None  # Link API key for production auth


class ProviderOAuthAuthorizeRequest(BaseModel):
    method: int


class ProviderOAuthCallbackRequest(BaseModel):
    method: int
    code: Optional[str] = None


# Memory API models
class MemoryStoreRequest(BaseModel):
    content: str
    metadata: Optional[Dict[str, Any]] = None
    categories: Optional[List[str]] = None


class MemorySearchRequest(BaseModel):
    query: str
    max_results: Optional[int] = 5
    memory_type: Optional[str] = None
    categories: Optional[List[str]] = None


# --- Security/Approval Models ---
class SecurityConfigUpdate(BaseModel):
    """Request body for updating security configuration."""

    mode: Optional[str] = None  # read_only | workspace | full
    enabled: Optional[bool] = None  # Toggle permission checks (YOLO mode)


class ApprovalAction(BaseModel):
    """Request body for approving a request."""

    scope: str = "once"  # once | session | pattern
    pattern: Optional[str] = None  # Required if scope is "pattern"


class PreApprovalRequest(BaseModel):
    """Request body for pre-approving operations."""

    operation: str  # e.g., "filesystem.write"
    pattern: Optional[str] = None  # Glob pattern for resource matching
    session_id: Optional[str] = None  # Session to apply to (None for global)
    ttl_seconds: Optional[int] = None  # Optional expiration


class PermissionReplyAction(BaseModel):
    """OpenCode-compatible permission reply payload."""

    reply: str  # once | always | reject
    message: Optional[str] = None


class QuestionReplyAction(BaseModel):
    """OpenCode-compatible question reply payload."""

    answers: List[List[str]]


# --- WebSocket Connection Manager for Approvals ---


class ApprovalWebSocketManager:
    """Manages WebSocket connections for approval notifications.

    Tracks active WebSocket connections and provides methods to
    broadcast approval events to connected clients.

    Note: The asyncio.Lock is lazily initialized on first async access
    to avoid creating it before the event loop is running.
    """

    def __init__(self):
        # Map of session_id -> list of WebSocket connections
        self._connections: Dict[str, List[WebSocket]] = {}
        # All connections (for broadcast)
        self._all_connections: List[WebSocket] = []
        # Lazy-initialized lock (created on first async access)
        self._lock: Optional[asyncio.Lock] = None

    def _get_lock(self) -> asyncio.Lock:
        """Get or create the asyncio lock (must be called within event loop)."""
        if self._lock is None:
            self._lock = asyncio.Lock()
        return self._lock

    async def connect(self, websocket: WebSocket, session_id: Optional[str] = None):
        """Register a WebSocket connection."""
        async with self._get_lock():
            self._all_connections.append(websocket)
            if session_id:
                if session_id not in self._connections:
                    self._connections[session_id] = []
                self._connections[session_id].append(websocket)
        logger.debug(
            f"WebSocket connected: session={session_id}, total={len(self._all_connections)}"
        )

    async def disconnect(self, websocket: WebSocket, session_id: Optional[str] = None):
        """Unregister a WebSocket connection."""
        async with self._get_lock():
            if websocket in self._all_connections:
                self._all_connections.remove(websocket)
            if session_id and session_id in self._connections:
                if websocket in self._connections[session_id]:
                    self._connections[session_id].remove(websocket)
                if not self._connections[session_id]:
                    del self._connections[session_id]
        logger.debug(
            f"WebSocket disconnected: session={session_id}, total={len(self._all_connections)}"
        )

    async def update_session(
        self, websocket: WebSocket, old_session_id: Optional[str], new_session_id: str
    ):
        """Atomically update a WebSocket's session mapping without disconnecting.

        This prevents missed events during session transitions by keeping
        the connection in _all_connections throughout the operation.
        """
        async with self._get_lock():
            # Remove from old session mapping (but NOT from _all_connections)
            if old_session_id and old_session_id in self._connections:
                if websocket in self._connections[old_session_id]:
                    self._connections[old_session_id].remove(websocket)
                if not self._connections[old_session_id]:
                    del self._connections[old_session_id]

            # Add to new session mapping
            if new_session_id not in self._connections:
                self._connections[new_session_id] = []
            if websocket not in self._connections[new_session_id]:
                self._connections[new_session_id].append(websocket)

        logger.debug(f"WebSocket session updated: {old_session_id} -> {new_session_id}")

    async def send_to_session(self, session_id: str, event: str, data: dict):
        """Send an event to all connections for a session."""
        async with self._get_lock():
            # Copy list to prevent race condition during iteration
            connections = list(self._connections.get(session_id, []))

        for ws in connections:
            try:
                await ws.send_json({"event": event, "data": data})
            except Exception as e:
                logger.warning(f"Failed to send to session {session_id}: {e}")

    async def broadcast(self, event: str, data: dict):
        """Broadcast an event to all connected clients."""
        async with self._get_lock():
            connections = list(self._all_connections)

        for ws in connections:
            try:
                await ws.send_json({"event": event, "data": data})
            except Exception as e:
                logger.warning(f"Failed to broadcast: {e}")

    async def send_approval_required(self, request_dict: dict):
        """Send an approval_required event."""
        session_id = request_dict.get("session_id")
        if session_id:
            await self.send_to_session(session_id, "approval_required", request_dict)
        # Also broadcast to all (for monitoring/admin UIs)
        await self.broadcast("approval_required", request_dict)

    async def send_approval_resolved(self, request_dict: dict):
        """Send an approval_resolved event."""
        session_id = request_dict.get("session_id")
        if session_id:
            await self.send_to_session(session_id, "approval_resolved", request_dict)
        await self.broadcast("approval_resolved", request_dict)


async def _emit_opencode_event(
    event_type: str,
    properties: dict[str, Any],
) -> None:
    core = getattr(router, "core", None)
    event_bus = getattr(core, "event_bus", None)
    emit = getattr(event_bus, "emit", None)
    if not callable(emit):
        return
    await emit(
        "opencode_event",
        {
            "type": event_type,
            "properties": properties,
        },
    )


def _schedule_opencode_event(event_type: str, properties: dict[str, Any]) -> None:
    async def _runner() -> None:
        try:
            await _emit_opencode_event(event_type, properties)
        except Exception:
            logger.debug("Failed to emit opencode event %s", event_type, exc_info=True)

    try:
        loop = asyncio.get_running_loop()
        loop.create_task(_runner())
        return
    except RuntimeError:
        pass

    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            loop.create_task(_runner())
        else:
            loop.run_until_complete(_runner())
    except Exception:
        logger.debug("Failed to schedule opencode event %s", event_type, exc_info=True)


def _permission_name_for_request(request_dict: dict[str, Any]) -> str:
    tool_name = request_dict.get("tool_name")
    if isinstance(tool_name, str):
        mapping = {
            "read_file": "read",
            "enhanced_read": "read",
            "list_files": "list",
            "get_file_map": "list",
            "find_file": "glob",
            "grep_search": "grep",
            "create_folder": "edit",
            "create_file": "edit",
            "write_file": "edit",
            "write_to_file": "edit",
            "enhanced_write": "edit",
            "patch_file": "edit",
            "patch_files": "edit",
            "apply_diff": "edit",
            "edit_with_pattern": "edit",
            "replace_lines": "edit",
            "insert_lines": "edit",
            "delete_lines": "edit",
            "multiedit_apply": "edit",
            "execute_command": "bash",
            "code_execution": "bash",
            "webfetch": "webfetch",
            "delegate_explore_task": "task",
            "delegate": "task",
            "spawn_sub_agent": "task",
        }
        mapped = mapping.get(tool_name.strip())
        if mapped:
            return mapped

    operation = request_dict.get("operation")
    if isinstance(operation, str):
        op = operation.strip().lower()
        if op.startswith("filesystem.read"):
            return "read"
        if op.startswith("filesystem.list"):
            return "list"
        if op.startswith("filesystem"):
            return "edit"
        if op.startswith("process"):
            return "bash"
        if op.startswith("network.fetch"):
            return "webfetch"
    return "tool"


def _approval_request_to_permission_payload(
    request_dict: dict[str, Any],
) -> dict[str, Any]:
    context = request_dict.get("context")
    context_data = context if isinstance(context, dict) else {}
    resource = request_dict.get("resource")
    patterns = [resource] if isinstance(resource, str) and resource.strip() else ["*"]

    metadata: dict[str, Any] = {
        "reason": request_dict.get("reason"),
        "operation": request_dict.get("operation"),
        "tool_name": request_dict.get("tool_name"),
        "resource": request_dict.get("resource"),
    }
    tool_input = context_data.get("tool_input")
    if isinstance(tool_input, dict):
        metadata.update(tool_input)

    payload: dict[str, Any] = {
        "id": request_dict.get("id"),
        "sessionID": request_dict.get("session_id") or "",
        "permission": _permission_name_for_request(request_dict),
        "patterns": patterns,
        "always": patterns,
        "metadata": metadata,
    }

    tool_payload = context_data.get("tool")
    if isinstance(tool_payload, dict):
        message_id = tool_payload.get("messageID")
        call_id = tool_payload.get("callID")
        if isinstance(message_id, str) and isinstance(call_id, str):
            payload["tool"] = {
                "messageID": message_id,
                "callID": call_id,
            }

    return payload


def _approval_request_to_permission_reply_payload(
    request_dict: dict[str, Any],
) -> dict[str, Any]:
    status = request_dict.get("status")
    resolution_scope = request_dict.get("resolution_scope")
    if status == "approved":
        reply = "always" if resolution_scope in {"session", "pattern"} else "once"
    else:
        reply = "reject"
    return {
        "sessionID": request_dict.get("session_id") or "",
        "requestID": request_dict.get("id"),
        "reply": reply,
    }


# Singleton instance for approval WebSocket management
_approval_ws_manager = ApprovalWebSocketManager()

# Flag to track if approval callbacks are registered
_approval_callbacks_registered = False
_question_callbacks_registered = False


def _setup_approval_websocket_callbacks():
    """Register ApprovalManager callbacks for WebSocket notifications.

    This is called lazily when the first approval-related operation occurs.
    """
    global _approval_callbacks_registered
    if _approval_callbacks_registered:
        return

    try:
        from penguin.security.approval import get_approval_manager

        manager = get_approval_manager()

        # Create async-safe callback wrappers
        def on_request_created(request):
            """Callback when an approval request is created."""
            try:
                request_dict = request.to_dict()
                # Schedule the coroutine in the event loop
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    asyncio.create_task(
                        _approval_ws_manager.send_approval_required(request_dict)
                    )
                else:
                    loop.run_until_complete(
                        _approval_ws_manager.send_approval_required(request_dict)
                    )

                _schedule_opencode_event(
                    "permission.asked",
                    _approval_request_to_permission_payload(request_dict),
                )
            except Exception as e:
                logger.error(f"Error sending approval_required event: {e}")

        def on_request_resolved(request):
            """Callback when an approval request is resolved."""
            try:
                request_dict = request.to_dict()
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    asyncio.create_task(
                        _approval_ws_manager.send_approval_resolved(request_dict)
                    )
                else:
                    loop.run_until_complete(
                        _approval_ws_manager.send_approval_resolved(request_dict)
                    )

                _schedule_opencode_event(
                    "permission.replied",
                    _approval_request_to_permission_reply_payload(request_dict),
                )
            except Exception as e:
                logger.error(f"Error sending approval_resolved event: {e}")

        manager.on_request_created(on_request_created)
        manager.on_request_resolved(on_request_resolved)
        _approval_callbacks_registered = True
        logger.info("Approval WebSocket callbacks registered")

    except ImportError:
        logger.debug(
            "Approval module not available, WebSocket callbacks not registered"
        )
    except Exception as e:
        logger.error(f"Failed to setup approval WebSocket callbacks: {e}")


def _setup_question_event_callbacks():
    """Register QuestionManager callbacks for OpenCode event emission."""
    global _question_callbacks_registered
    if _question_callbacks_registered:
        return

    try:
        from penguin.security.question import get_question_manager

        manager = get_question_manager()

        def on_request_created(request):
            try:
                _schedule_opencode_event("question.asked", request.to_dict())
            except Exception:
                logger.debug("Failed to emit question.asked", exc_info=True)

        def on_request_answered(request):
            try:
                _schedule_opencode_event(
                    "question.replied",
                    {
                        "sessionID": request.session_id,
                        "requestID": request.id,
                        "answers": request.answers or [],
                    },
                )
            except Exception:
                logger.debug("Failed to emit question.replied", exc_info=True)

        def on_request_rejected(request):
            try:
                _schedule_opencode_event(
                    "question.rejected",
                    {
                        "sessionID": request.session_id,
                        "requestID": request.id,
                    },
                )
            except Exception:
                logger.debug("Failed to emit question.rejected", exc_info=True)

        manager.on_request_created(on_request_created)
        manager.on_request_answered(on_request_answered)
        manager.on_request_rejected(on_request_rejected)
        _question_callbacks_registered = True
    except ImportError:
        logger.debug("Question module not available, callbacks not registered")
    except Exception as e:
        logger.error("Failed to setup question callbacks: %s", e)


router = APIRouter()


async def get_core():
    return router.core


def _get_coordinator(core: PenguinCore):
    try:
        return core.get_coordinator()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Coordinator not available: {e}")


def _validate_agent_id(agent_id: str) -> None:
    if not agent_id or len(agent_id) > 64:
        raise HTTPException(status_code=400, detail="agent_id must be 1-64 chars")
    if not re.fullmatch(r"[a-z0-9_-]+", agent_id):
        raise HTTPException(status_code=400, detail="agent_id must match ^[a-z0-9_-]+$")


class AgentSpawnRequest(BaseModel):
    id: str
    parent: Optional[str] = None
    model_config_id: str
    persona: Optional[str] = None
    system_prompt: Optional[str] = None
    share_session: bool = False
    share_context_window: bool = False
    shared_cw_max_tokens: Optional[int] = None
    model_overrides: Optional[Dict[str, Any]] = None
    default_tools: Optional[List[str]] = None
    activate: bool = False
    initial_prompt: Optional[str] = None


class AgentRegister(BaseModel):
    role: str


class ToAgentRequest(BaseModel):
    agent_id: str
    content: Any
    message_type: Optional[str] = "message"
    metadata: Optional[Dict[str, Any]] = None
    channel: Optional[str] = None


class ToHumanRequest(BaseModel):
    content: Any
    message_type: Optional[str] = "status"
    metadata: Optional[Dict[str, Any]] = None
    channel: Optional[str] = None


class HumanReplyRequest(BaseModel):
    agent_id: str
    content: Any
    message_type: Optional[str] = "message"
    metadata: Optional[Dict[str, Any]] = None
    channel: Optional[str] = None


class AgentPatchRequest(BaseModel):
    paused: Optional[bool] = None


class AgentDelegateRequest(BaseModel):
    content: Any
    channel: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None
    parent: Optional[str] = None


class MessageEnvelope(BaseModel):
    recipient: str
    content: Any
    message_type: Optional[str] = "message"
    channel: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


class CoordRoleSend(BaseModel):
    role: str
    content: Any
    message_type: Optional[str] = "message"


class CoordBroadcast(BaseModel):
    roles: List[str]
    content: Any
    message_type: Optional[str] = "message"


class CoordRRWorkflow(BaseModel):
    role: str
    prompts: List[str]


class CoordRoleChain(BaseModel):
    roles: List[str]
    content: Any


@router.websocket("/api/v1/events/ws")
async def events_ws(websocket: WebSocket, core: PenguinCore = Depends(get_core)):
    """WebSocket stream forwarding bus.message and UI message events with filters.

    Query params:
      - agent_id: filter by agent id (optional)
      - message_type: filter by message_type (message|action|status)
      - include_ui: 'true'|'false' (default 'true')
      - include_bus: 'true'|'false' (default 'true')
    """
    await websocket.accept()
    params = websocket.query_params
    agent_filter = params.get("agent_id")
    type_filter = params.get("message_type")
    channel_filter = params.get("channel")
    include_ui = params.get("include_ui", "true").lower() != "false"
    include_bus = params.get("include_bus", "true").lower() != "false"

    utils_event_bus = UtilsEventBus.get_instance()
    cli_event_bus = CLIEventBus.get_sync()
    handlers = []
    ui_handlers = []

    async def _send(event: str, payload: Dict[str, Any]):
        try:
            a_id = payload.get("agent_id") or payload.get("sender")
            m_type = payload.get("message_type") or payload.get("type")
            channel = payload.get("channel")
            if agent_filter and a_id != agent_filter:
                return
            if type_filter and m_type != type_filter:
                return
            if channel_filter and channel != channel_filter:
                return
            await websocket.send_json({"event": event, "data": payload})
        except Exception as e:
            # Client closed or other transient error
            return

    # UtilsEventBus: bus.message
    async def _on_bus_message(data):
        if not include_bus:
            return
        try:
            if isinstance(data, dict):
                payload = dict(data)
                if "agent_id" not in payload and "sender" in payload:
                    payload["agent_id"] = payload.get("sender")
                await _send("bus.message", payload)
        except Exception:
            pass

    utils_event_bus.subscribe("bus.message", _on_bus_message)
    handlers.append(("bus.message", _on_bus_message))

    # CLI EventBus: UI events
    async def _on_ui_event(event_type: str, data: Dict[str, Any]):
        if not include_ui:
            return
        try:
            if event_type in {"message", "stream_chunk", "human_message", "tool"}:
                payload = dict(data or {})
                payload.setdefault(
                    "agent_id",
                    getattr(core.conversation_manager, "current_agent_id", None),
                )
                # Don't override message_type for tool events
                if event_type != "tool":
                    payload.setdefault("message_type", "message")
                await _send(event_type, payload)
        except Exception:
            pass

    # Subscribe to all event types via CLI event bus
    for event_type in EventType:
        cli_event_bus.subscribe(event_type.value, _on_ui_event)
        ui_handlers.append((event_type.value, _on_ui_event))

    try:
        while True:
            await asyncio.sleep(1.0)
    except WebSocketDisconnect:
        pass
    finally:
        # Unsubscribe from CLI event bus
        for ev, h in ui_handlers:
            try:
                cli_event_bus.unsubscribe(ev, h)
            except Exception:
                pass
        # Unsubscribe from utils event bus
        for ev, h in handlers:
            try:
                utils_event_bus.unsubscribe(ev, h)
            except Exception:
                pass


@router.websocket("/api/v1/ws/messages")
async def messages_ws(websocket: WebSocket, core: PenguinCore = Depends(get_core)):
    """Alias of /api/v1/events/ws for message streaming.

    Supports the same query params as /api/v1/events/ws:
      - agent_id, message_type, channel, include_ui, include_bus
    """
    await events_ws(websocket, core)  # Reuse the same handler


@router.get("/api/v1/conversations/{conversation_id}/history")
async def api_conversation_history(
    conversation_id: str,
    include_system: bool = True,
    limit: Optional[int] = None,
    core: PenguinCore = Depends(get_core),
    # Optional filters (kept for backwards compatibility)
    agent_id: Optional[str] = None,
    channel: Optional[str] = None,
    message_type: Optional[str] = None,
):
    """Get conversation history with an explicit envelope and optional filters.

    Returns an object with the conversation_id and filtered messages to provide a
    stable shape for API consumers. Optional filters (agent_id, channel,
    message_type) are supported for compatibility with earlier versions.
    """
    try:
        history = core.get_conversation_history(
            conversation_id,
            include_system=include_system,
            limit=limit,
        )

        def _ok(m: Dict[str, Any]) -> bool:
            if agent_id and m.get("agent_id") != agent_id:
                return False
            if channel and (m.get("metadata") or {}).get("channel") != channel:
                return False
            if message_type and m.get("message_type") != message_type:
                return False
            return True

        filtered = [m for m in history if _ok(m)]
        return {"conversation_id": conversation_id, "messages": filtered}
    except Exception as e:
        logger.error(f"conversation history error: {e}")
        raise HTTPException(
            status_code=500, detail="Failed to retrieve conversation history"
        )


@router.get("/api/v1/agents/{agent_id}/history")
async def get_agent_current_history(
    agent_id: str,
    core: PenguinCore = Depends(get_core),
    include_system: bool = True,
    limit: Optional[int] = None,
):
    _validate_agent_id(agent_id)
    try:
        conv = core.conversation_manager.get_agent_conversation(agent_id)
        sid = getattr(conv.session, "id", None)
        if not sid:
            return []
        return core.get_conversation_history(
            sid, include_system=include_system, limit=limit
        )
    except KeyError:
        raise HTTPException(status_code=404, detail="Agent not found")
    except Exception as e:
        logger.error(f"agent history error: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch history")


@router.get("/api/v1/agents/{agent_id}/sessions")
async def list_agent_sessions(agent_id: str, core: PenguinCore = Depends(get_core)):
    _validate_agent_id(agent_id)
    try:
        cm = core.conversation_manager
        cm._ensure_agent(agent_id)  # ensure structures
        sm = cm.agent_session_managers[agent_id]
        sessions = sm.list_sessions(limit=1000, offset=0)
        return sessions
    except KeyError:
        raise HTTPException(status_code=404, detail="Agent not found")
    except Exception as e:
        logger.error(f"list sessions error: {e}")
        raise HTTPException(status_code=500, detail="Failed to list sessions")


async def get_agent_session_history(
    agent_id: str,
    session_id: str,
    core: PenguinCore = Depends(get_core),
    include_system: bool = True,
    limit: Optional[int] = None,
):
    _validate_agent_id(agent_id)
    try:
        cm = core.conversation_manager
        cm._ensure_agent(agent_id)
        # Don't enforce ownership strictly; fetch by session id directly
        items = cm.get_conversation_history(
            session_id, include_system=include_system, limit=limit
        )
        return items
    except KeyError:
        raise HTTPException(status_code=404, detail="Agent not found")
    except Exception as e:
        logger.error(f"agent session history error: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch session history")


@router.get("/api/v1/telemetry")
async def get_telemetry(core: PenguinCore = Depends(get_core)):
    try:
        data = await core.get_telemetry_summary()
        return data
    except Exception as e:
        logger.error(f"telemetry error: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch telemetry")


@router.websocket("/api/v1/ws/telemetry")
async def telemetry_ws(
    websocket: WebSocket,
    core: PenguinCore = Depends(get_core),
):
    await websocket.accept()
    params = websocket.query_params
    agent_filter = params.get("agent_id")
    try:
        interval = float(params.get("interval", "2"))
    except ValueError:
        interval = 2.0
    try:
        while True:
            data = await core.get_telemetry_summary()
            if agent_filter:
                data = _filter_telemetry_snapshot(data, agent_filter)
            await websocket.send_json(data)
            await asyncio.sleep(interval)
    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.debug(f"telemetry ws closed: {e}")


def _filter_telemetry_snapshot(
    snapshot: Dict[str, Any], agent_id: str
) -> Dict[str, Any]:
    """Return a filtered copy focusing on a single agent."""
    try:
        data = copy.deepcopy(snapshot)
    except Exception:
        data = snapshot
    if not isinstance(data, dict):
        return data

    agents = data.get("agents")
    if isinstance(agents, dict):
        agent_stats = agents.get(agent_id)
        data["agents"] = {agent_id: agent_stats} if agent_stats else {}

    tokens = data.get("tokens")
    if isinstance(tokens, dict):
        per_agent = tokens.get("per_agent")
        if isinstance(per_agent, dict):
            tokens["per_agent"] = (
                {agent_id: per_agent.get(agent_id)} if agent_id in per_agent else {}
            )

    return data


@router.get("/api/v1/agents")
async def list_agents(
    core: PenguinCore = Depends(get_core), simple: Optional[bool] = None
):
    """List registered agents.

    - Default: return full roster (JSON list) from core.get_agent_roster().
    - When simple=true: return {"agents": [{agent_id, conversation_id}]} (legacy shape).
    """
    try:
        if simple:
            cm = core.conversation_manager
            agents = []
            for aid, conv in (getattr(cm, "agent_sessions", {}) or {}).items():
                try:
                    agents.append(
                        {
                            "agent_id": aid,
                            "conversation_id": getattr(conv.session, "id", None),
                        }
                    )
                except Exception:
                    continue
            return {"agents": agents}
        return core.get_agent_roster()
    except Exception as e:
        logger.error(f"list_agents error: {e}")
        raise HTTPException(status_code=500, detail="Failed to list agents")


@router.post("/api/v1/agents")
async def create_agent(req: AgentSpawnRequest, core: PenguinCore = Depends(get_core)):
    _validate_agent_id(req.id)
    try:
        parent = (req.parent or "").strip() or None
        if parent:
            core.create_sub_agent(
                req.id,
                parent_agent_id=parent,
                system_prompt=req.system_prompt,
                share_session=bool(req.share_session),
                share_context_window=bool(req.share_context_window),
                shared_context_window_max_tokens=req.shared_cw_max_tokens,
            )
        else:
            core.ensure_agent_conversation(req.id, system_prompt=req.system_prompt)

        if parent:
            try:
                await core.publish_sub_agent_session_created(
                    req.id,
                    parent_agent_id=parent,
                    share_session=bool(req.share_session),
                )
            except Exception:
                logger.debug(
                    "Failed to emit session.created for agent '%s'",
                    req.id,
                    exc_info=True,
                )

        if req.activate:
            core.set_active_agent(req.id)

        # TODO: where the hell is register agent?

        if req.initial_prompt:
            await core.send_to_agent(req.id, req.initial_prompt)

        if not parent:
            try:
                conversation = core.conversation_manager.get_agent_conversation(req.id)
                session = getattr(conversation, "session", None)
                session_id = getattr(session, "id", None)
                if isinstance(session_id, str) and session_id:
                    info = get_session_info(core, session_id)
                    if isinstance(info, dict):
                        await _emit_session_created_event(core, info)
            except Exception:
                logger.debug(
                    "Failed to emit session.created for agent '%s'",
                    req.id,
                    exc_info=True,
                )

        return core.get_agent_profile(req.id) or {"id": req.id}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"create_agent error: {e}")
        raise HTTPException(status_code=500, detail="Failed to create agent")


@router.delete("/api/v1/agents/{agent_id}")
async def delete_agent(
    agent_id: str,
    core: PenguinCore = Depends(get_core),
    preserve_conversation: bool = True,
):
    _validate_agent_id(agent_id)
    try:
        # Block removal if parent has children (core enforces)
        removed = core.unregister_agent(
            agent_id, preserve_conversation=preserve_conversation
        )
        if asyncio.iscoroutine(removed):
            removed = await removed
        return {"removed": bool(removed)}
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        logger.error(f"delete_agent error: {e}")
        raise HTTPException(status_code=500, detail="Failed to delete agent")


@router.get("/api/v1/agents/{agent_id}")
async def get_agent(agent_id: str, core: PenguinCore = Depends(get_core)):
    _validate_agent_id(agent_id)
    prof = core.get_agent_profile(agent_id)
    if not prof:
        raise _format_error_response(AgentNotFoundError(agent_id), 404)
    return prof


@router.patch("/api/v1/agents/{agent_id}")
async def patch_agent(
    agent_id: str, req: AgentPatchRequest, core: PenguinCore = Depends(get_core)
):
    _validate_agent_id(agent_id)
    if req.paused is None:
        raise HTTPException(status_code=400, detail="No changes provided")
    try:
        core.set_agent_paused(agent_id, bool(req.paused))
        return core.get_agent_profile(agent_id) or {"id": agent_id}
    except Exception as e:
        logger.error(f"patch_agent error: {e}")
        raise HTTPException(status_code=500, detail="Failed to update agent")


@router.post("/api/v1/agents/{agent_id}/delegate")
async def delegate_to_agent(
    agent_id: str, req: AgentDelegateRequest, core: PenguinCore = Depends(get_core)
):
    """Convenience wrapper around POST /messages for parent→child delegation.

    Records a delegation event on parent/child (best-effort) and routes the content to the child.
    """
    _validate_agent_id(agent_id)
    if req.content is None:
        raise HTTPException(status_code=400, detail="content is required")
    parent = (
        req.parent
        or getattr(core.conversation_manager, "current_agent_id", None)
        or "default"
    )
    try:
        # Record delegation event
        cm = core.conversation_manager
        try:
            import uuid as _uuid

            delegation_id = _uuid.uuid4().hex[:8]
            meta = dict(req.metadata or {})
            if req.channel:
                meta["channel"] = req.channel
            cm.log_delegation_event(
                delegation_id=delegation_id,
                parent_agent_id=str(parent),
                child_agent_id=agent_id,
                event="request_sent",
                message=str(req.content)[:140],
                metadata=meta,
            )
        except Exception:
            pass

        ok = await core.send_to_agent(
            agent_id,
            req.content,
            message_type="message",
            metadata=req.metadata,
            channel=req.channel,
        )
        return {"ok": bool(ok), "delegated_to": agent_id, "parent": parent}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"delegate_to_agent error: {e}")
        raise HTTPException(status_code=500, detail="Failed to delegate to agent")


@router.post("/api/v1/messages")
async def post_message(req: MessageEnvelope, core: PenguinCore = Depends(get_core)):
    target = (req.recipient or "").strip().lower()
    if not target:
        raise HTTPException(status_code=400, detail="recipient is required")
    try:
        if target in ("human", "user"):
            ok = await core.send_to_human(
                req.content,
                message_type=req.message_type or "message",
                metadata=req.metadata,
                channel=req.channel,
            )
        else:
            _validate_agent_id(target)
            ok = await core.send_to_agent(
                target,
                req.content,
                message_type=req.message_type or "message",
                metadata=req.metadata,
                channel=req.channel,
            )
        return {"sent": bool(ok)}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"post_message error: {e}")
        raise HTTPException(status_code=500, detail="Failed to send message")


@router.post("/api/v1/agents/{agent_id}/register")
async def register_agent(
    agent_id: str, req: AgentRegister, core: PenguinCore = Depends(get_core)
):
    _validate_agent_id(agent_id)
    try:
        coord = _get_coordinator(core)
        coord.register_existing(agent_id, role=req.role)
        return {"ok": True}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"register_agent error: {e}")
        raise HTTPException(status_code=500, detail="Failed to register agent")


@router.post("/api/v1/messages/to-agent")
async def api_to_agent(req: ToAgentRequest, core: PenguinCore = Depends(get_core)):
    _validate_agent_id(req.agent_id)
    try:
        ok = await core.send_to_agent(
            req.agent_id,
            req.content,
            message_type=req.message_type or "message",
            metadata=req.metadata,
            channel=req.channel,
        )
        return {"ok": ok}
    except Exception as e:
        logger.error(f"to-agent error: {e}")
        raise HTTPException(status_code=500, detail="Failed to send to agent")


@router.post("/api/v1/messages/to-human")
async def api_to_human(req: ToHumanRequest, core: PenguinCore = Depends(get_core)):
    try:
        ok = await core.send_to_human(
            req.content,
            message_type=req.message_type or "status",
            metadata=req.metadata,
            channel=req.channel,
        )
        return {"ok": ok}
    except Exception as e:
        logger.error(f"to-human error: {e}")
        raise HTTPException(status_code=500, detail="Failed to send to human")


@router.post("/api/v1/messages/human-reply")
async def api_human_reply(
    req: HumanReplyRequest, core: PenguinCore = Depends(get_core)
):
    _validate_agent_id(req.agent_id)
    try:
        ok = await core.human_reply(
            req.agent_id,
            req.content,
            message_type=req.message_type or "message",
            metadata=req.metadata,
            channel=req.channel,
        )
        return {"ok": ok}
    except Exception as e:
        logger.error(f"human-reply error: {e}")
        raise HTTPException(status_code=500, detail="Failed to send human reply")


@router.post("/api/v1/coord/send-role")
async def api_coord_send_role(
    req: CoordRoleSend, core: PenguinCore = Depends(get_core)
):
    try:
        coord = _get_coordinator(core)
        target = await coord.send_to_role(
            req.role, req.content, message_type=req.message_type or "message"
        )
        return {"ok": True, "target": target}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"coord send-role error: {e}")
        raise HTTPException(status_code=500, detail="Failed to send to role")


@router.post("/api/v1/coord/broadcast")
async def api_coord_broadcast(
    req: CoordBroadcast, core: PenguinCore = Depends(get_core)
):
    try:
        coord = _get_coordinator(core)
        sent = await coord.broadcast(
            req.roles, req.content, message_type=req.message_type or "message"
        )
        return {"ok": True, "sent": sent}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"coord broadcast error: {e}")
        raise HTTPException(status_code=500, detail="Failed to broadcast")


@router.post("/api/v1/coord/rr-workflow")
async def api_coord_rr(req: CoordRRWorkflow, core: PenguinCore = Depends(get_core)):
    try:
        coord = _get_coordinator(core)
        await coord.simple_round_robin_workflow(req.prompts, role=req.role)
        return {"ok": True}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"coord rr-workflow error: {e}")
        raise HTTPException(status_code=500, detail="Failed rr-workflow")


@router.post("/api/v1/coord/role-chain")
async def api_coord_role_chain(
    req: CoordRoleChain, core: PenguinCore = Depends(get_core)
):
    try:
        coord = _get_coordinator(core)
        await coord.role_chain_workflow(req.content, roles=req.roles)
        return {"ok": True}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"coord role-chain error: {e}")
        raise HTTPException(status_code=500, detail="Failed role-chain")


## (removed duplicate conversation history route; unified earlier definition)


@router.get("/api/v1/health")
async def health(core: PenguinCore = Depends(get_core)):
    """Comprehensive health status for container monitoring and Link integration.

    Returns detailed health information including:
    - Overall status (healthy, degraded, at_capacity)
    - Uptime and timestamp
    - Resource usage (CPU, memory, threads)
    - Agent capacity and utilization
    - Performance metrics (latency, success rate, P95/P99)
    - Component health status
    """
    monitor = get_health_monitor()
    return await monitor.get_comprehensive_health(core)


@router.get("/api/v1/system-info")
async def system_info(core: PenguinCore = Depends(get_core)):
    """Return core system information."""
    try:
        return core.get_system_info()
    except Exception as e:
        logger.error(f"system-info error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/path")
async def opencode_path_get(
    core: PenguinCore = Depends(get_core),
    directory: Optional[str] = Query(None),
    session_id: Optional[str] = Query(None),
    conversation_id: Optional[str] = Query(None),
):
    """OpenCode-compatible path endpoint."""
    try:
        effective_session = session_id or conversation_id
        payload = get_path_info(core, directory=directory, session_id=effective_session)
        if isinstance(payload, dict):
            _remember_last_scoped_directory(core, payload.get("directory"))
        return payload
    except Exception as e:
        logger.error(f"path.get error: {e}")
        raise HTTPException(status_code=500, detail="Failed to load path info")


@router.get("/vcs")
async def opencode_vcs_get(
    core: PenguinCore = Depends(get_core),
    directory: Optional[str] = Query(None),
    session_id: Optional[str] = Query(None),
    conversation_id: Optional[str] = Query(None),
):
    """OpenCode-compatible VCS endpoint."""
    try:
        effective_session = session_id or conversation_id
        payload = get_vcs_info(core, directory=directory, session_id=effective_session)
        if isinstance(payload, dict):
            _remember_last_scoped_directory(core, payload.get("root"))
        return payload
    except Exception as e:
        logger.error(f"vcs.get error: {e}")
        raise HTTPException(status_code=500, detail="Failed to load vcs info")


@router.get("/formatter")
async def opencode_formatter_status(
    core: PenguinCore = Depends(get_core),
    directory: Optional[str] = Query(None),
    session_id: Optional[str] = Query(None),
    conversation_id: Optional[str] = Query(None),
):
    """OpenCode-compatible formatter status endpoint."""
    try:
        effective_session = session_id or conversation_id
        _remember_last_scoped_directory(core, directory)
        return get_formatter_status(
            core, directory=directory, session_id=effective_session
        )
    except Exception as e:
        logger.error(f"formatter.status error: {e}")
        raise HTTPException(status_code=500, detail="Failed to load formatter status")


@router.get("/lsp")
async def opencode_lsp_status(
    core: PenguinCore = Depends(get_core),
    directory: Optional[str] = Query(None),
    session_id: Optional[str] = Query(None),
    conversation_id: Optional[str] = Query(None),
):
    """OpenCode-compatible LSP status endpoint."""
    try:
        effective_session = session_id or conversation_id
        _remember_last_scoped_directory(core, directory)
        return get_lsp_status(core, directory=directory, session_id=effective_session)
    except Exception as e:
        logger.error(f"lsp.status error: {e}")
        raise HTTPException(status_code=500, detail="Failed to load lsp status")


@router.get("/find/file")
async def opencode_find_files(
    core: PenguinCore = Depends(get_core),
    query: str = Query(""),
    dirs: Optional[str] = Query(None),
    entry_type: Optional[str] = Query(None, alias="type"),
    limit: Optional[int] = Query(None, ge=1, le=200),
    directory: Optional[str] = Query(None),
    session_id: Optional[str] = Query(None),
    conversation_id: Optional[str] = Query(None),
) -> List[str]:
    """OpenCode-compatible file/directory search endpoint."""
    type_value = entry_type.strip().lower() if isinstance(entry_type, str) else None
    if type_value not in {None, "file", "directory"}:
        raise HTTPException(
            status_code=400, detail="type must be 'file' or 'directory'"
        )

    dirs_enabled = True
    if isinstance(dirs, str) and dirs.strip():
        dirs_enabled = dirs.strip().lower() != "false"

    limit_value = int(limit) if isinstance(limit, int) else 10
    query_value = query.strip() if isinstance(query, str) else ""

    resolved_directory = _resolve_scoped_directory_for_find(
        core,
        directory=directory,
        session_id=session_id,
        conversation_id=conversation_id,
    )
    if not resolved_directory:
        raise HTTPException(
            status_code=400, detail="Unable to resolve search directory"
        )

    files, directories = _get_find_file_index(resolved_directory)
    kind = type_value or ("file" if not dirs_enabled else "all")

    if not query_value:
        if kind == "file":
            return _sort_hidden_last(files, query_value)[:limit_value]
        return _sort_hidden_last(directories, query_value)[:limit_value]

    items = (
        files
        if kind == "file"
        else directories
        if kind == "directory"
        else [*files, *directories]
    )
    search_limit = (
        limit_value * 20
        if kind == "directory" and not _query_targets_hidden_paths(query_value)
        else limit_value
    )
    matched = _search_find_file_items(
        items, query_value, max(search_limit, limit_value)
    )
    return _sort_hidden_last(matched, query_value)[:limit_value]


@router.get("/config")
async def opencode_config_get(core: PenguinCore = Depends(get_core)):
    """OpenCode-compatible config endpoint."""
    try:
        return build_config_payload(core)
    except Exception as e:
        logger.error(f"config.get error: {e}")
        raise HTTPException(status_code=500, detail="Failed to load config")


@router.patch("/config")
async def opencode_config_update(
    config: Optional[Dict[str, Any]] = None,
    core: PenguinCore = Depends(get_core),
):
    """OpenCode-compatible config update endpoint."""
    payload = config if isinstance(config, dict) else {}

    try:
        model_id = payload.get("model")
        if isinstance(model_id, str) and model_id.strip():
            requested_model = model_id.strip()
            candidates: list[str] = [requested_model]
            if "/" in requested_model:
                _, remainder = requested_model.split("/", 1)
                if remainder and remainder not in candidates:
                    candidates.append(remainder)

            model_configs = getattr(getattr(core, "config", None), "model_configs", {})
            if isinstance(model_configs, dict) and len(candidates) == 2:
                full = candidates[0]
                short = candidates[1]
                if short in model_configs and full not in model_configs:
                    candidates = [short, full]

            ok = False
            last_reason: Optional[str] = None
            for candidate in candidates:
                ok = await core.load_model(candidate)
                if ok:
                    break
                reason = getattr(core, "_last_model_load_error", None)
                if isinstance(reason, str) and reason.strip():
                    last_reason = reason.strip()

            if not ok and last_reason:
                logger.warning(
                    "config.update model switch failed requested=%s candidates=%s reason=%s",
                    requested_model,
                    candidates,
                    last_reason,
                )

            if not ok:
                detail = f"Failed to load model '{requested_model}'"
                if last_reason:
                    detail = f"{detail}: {last_reason}"
                raise HTTPException(
                    status_code=400,
                    detail=detail,
                )

        default_agent = payload.get("default_agent")
        if isinstance(default_agent, str) and default_agent.strip():
            _validate_agent_id(default_agent)
            core.set_active_agent(default_agent)

        return build_config_payload(core)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"config.update error: {e}")
        raise HTTPException(status_code=500, detail="Failed to update config")


@router.get("/config/providers")
async def opencode_config_providers(core: PenguinCore = Depends(get_core)):
    """OpenCode-compatible config providers endpoint."""
    try:
        return build_config_providers_payload(core)
    except Exception as e:
        logger.error(f"config.providers error: {e}")
        raise HTTPException(status_code=500, detail="Failed to load config providers")


@router.get("/provider")
async def opencode_provider_list(core: PenguinCore = Depends(get_core)):
    """OpenCode-compatible provider list endpoint."""
    try:
        return build_provider_list_payload(core)
    except Exception as e:
        logger.error(f"provider.list error: {e}")
        raise HTTPException(status_code=500, detail="Failed to load providers")


@router.get("/provider/auth")
async def opencode_provider_auth(core: PenguinCore = Depends(get_core)):
    """OpenCode-compatible provider auth methods endpoint."""
    try:
        return provider_auth_methods(core)
    except Exception as e:
        logger.error(f"provider.auth error: {e}")
        raise HTTPException(status_code=500, detail="Failed to load provider auth")


@router.put("/auth/{providerID}")
async def opencode_auth_set(
    providerID: str,
    auth: Optional[Dict[str, Any]] = None,
    core: PenguinCore = Depends(get_core),
):
    """OpenCode-compatible provider auth write endpoint."""
    payload = auth if isinstance(auth, dict) else {}
    try:
        set_provider_auth_record(providerID, payload)
        record = get_provider_auth_records().get(providerID.strip().lower())
        if isinstance(record, dict):
            apply_auth_to_runtime(core, providerID, record)
        return True
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"auth.set error: {e}")
        raise HTTPException(status_code=500, detail="Failed to set auth credentials")


@router.delete("/auth/{providerID}")
async def opencode_auth_remove(providerID: str):
    """OpenCode-compatible provider auth delete endpoint."""
    try:
        return remove_provider_auth_record(providerID)
    except Exception as e:
        logger.error(f"auth.remove error: {e}")
        raise HTTPException(status_code=500, detail="Failed to remove auth credentials")


@router.post("/instance/dispose")
async def opencode_instance_dispose():
    """OpenCode-compatible instance dispose endpoint."""
    logger.info("instance.dispose requested")
    return True


@router.post("/provider/{providerID}/oauth/authorize")
async def opencode_provider_oauth_authorize(
    providerID: str,
    request: ProviderOAuthAuthorizeRequest,
):
    """OpenCode-compatible provider OAuth authorize endpoint."""
    method = request.method
    try:
        return await provider_oauth_authorize(providerID, method)
    except ValueError as e:
        _request_log_info(
            "provider.oauth.authorize validation error provider=%s method=%s detail=%s",
            providerID,
            method,
            e,
        )
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.exception("provider.oauth.authorize unexpected error")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to authorize provider OAuth: {e}",
        )


@router.post("/provider/{providerID}/oauth/callback")
async def opencode_provider_oauth_callback(
    providerID: str,
    request: ProviderOAuthCallbackRequest,
    core: PenguinCore = Depends(get_core),
):
    """OpenCode-compatible provider OAuth callback endpoint."""
    method = request.method
    code = request.code
    try:
        success = await provider_oauth_callback(providerID, method, code=code)
        if success:
            record = get_provider_auth_records().get(providerID.strip().lower())
            if isinstance(record, dict):
                try:
                    apply_auth_to_runtime(core, providerID, record)
                except Exception:
                    logger.exception(
                        "provider.oauth.callback runtime credential apply failure"
                    )
                    raise
        return success
    except ValueError as e:
        _request_log_info(
            "provider.oauth.callback validation error provider=%s method=%s detail=%s",
            providerID,
            method,
            e,
        )
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.exception("provider.oauth.callback unexpected error")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to process provider OAuth: {e}",
        )


@router.get("/api/v1/config")
async def api_config_get(core: PenguinCore = Depends(get_core)):
    """Alias for OpenCode-compatible config endpoint."""
    return await opencode_config_get(core=core)


@router.patch("/api/v1/config")
async def api_config_update(
    config: Optional[Dict[str, Any]] = None,
    core: PenguinCore = Depends(get_core),
):
    """Alias for OpenCode-compatible config update endpoint."""
    return await opencode_config_update(config=config, core=core)


@router.get("/api/v1/config/providers")
async def api_config_providers(core: PenguinCore = Depends(get_core)):
    """Alias for OpenCode-compatible config providers endpoint."""
    return await opencode_config_providers(core=core)


@router.get("/api/v1/provider")
async def api_provider_list(core: PenguinCore = Depends(get_core)):
    """Alias for OpenCode-compatible provider list endpoint."""
    return await opencode_provider_list(core=core)


@router.get("/api/v1/provider/auth")
async def api_provider_auth(core: PenguinCore = Depends(get_core)):
    """Alias for OpenCode-compatible provider auth methods endpoint."""
    return await opencode_provider_auth(core=core)


@router.put("/api/v1/auth/{providerID}")
async def api_auth_set(
    providerID: str,
    auth: Optional[Dict[str, Any]] = None,
    core: PenguinCore = Depends(get_core),
):
    """Alias for OpenCode-compatible provider auth write endpoint."""
    return await opencode_auth_set(providerID=providerID, auth=auth, core=core)


@router.delete("/api/v1/auth/{providerID}")
async def api_auth_remove(providerID: str):
    """Alias for OpenCode-compatible provider auth delete endpoint."""
    return await opencode_auth_remove(providerID=providerID)


@router.post("/api/v1/instance/dispose")
async def api_instance_dispose():
    """Alias for OpenCode-compatible instance dispose endpoint."""
    return await opencode_instance_dispose()


@router.post("/api/v1/provider/{providerID}/oauth/authorize")
async def api_provider_oauth_authorize(
    providerID: str,
    request: ProviderOAuthAuthorizeRequest,
):
    """Alias for OpenCode-compatible provider OAuth authorize endpoint."""
    return await opencode_provider_oauth_authorize(
        providerID=providerID, request=request
    )


@router.post("/api/v1/provider/{providerID}/oauth/callback")
async def api_provider_oauth_callback(
    providerID: str,
    request: ProviderOAuthCallbackRequest,
    core: PenguinCore = Depends(get_core),
):
    """Alias for OpenCode-compatible provider OAuth callback endpoint."""
    return await opencode_provider_oauth_callback(
        providerID=providerID,
        request=request,
        core=core,
    )


@router.get("/api/v1/path")
async def api_path_get(
    core: PenguinCore = Depends(get_core),
    directory: Optional[str] = Query(None),
    session_id: Optional[str] = Query(None),
    conversation_id: Optional[str] = Query(None),
):
    """Alias for path status in API namespace."""
    return await opencode_path_get(
        core,
        directory=directory,
        session_id=session_id,
        conversation_id=conversation_id,
    )


@router.get("/api/v1/vcs")
async def api_vcs_get(
    core: PenguinCore = Depends(get_core),
    directory: Optional[str] = Query(None),
    session_id: Optional[str] = Query(None),
    conversation_id: Optional[str] = Query(None),
):
    """Alias for VCS status in API namespace."""
    return await opencode_vcs_get(
        core,
        directory=directory,
        session_id=session_id,
        conversation_id=conversation_id,
    )


@router.get("/api/v1/formatter/status")
async def api_formatter_status(
    core: PenguinCore = Depends(get_core),
    directory: Optional[str] = Query(None),
    session_id: Optional[str] = Query(None),
    conversation_id: Optional[str] = Query(None),
):
    """Alias for formatter status in API namespace."""
    return await opencode_formatter_status(
        core,
        directory=directory,
        session_id=session_id,
        conversation_id=conversation_id,
    )


@router.get("/api/v1/lsp/status")
async def api_lsp_status(
    core: PenguinCore = Depends(get_core),
    directory: Optional[str] = Query(None),
    session_id: Optional[str] = Query(None),
    conversation_id: Optional[str] = Query(None),
):
    """Alias for LSP status in API namespace."""
    return await opencode_lsp_status(
        core,
        directory=directory,
        session_id=session_id,
        conversation_id=conversation_id,
    )


@router.get("/api/v1/find/file")
async def api_find_files(
    core: PenguinCore = Depends(get_core),
    query: str = Query(""),
    dirs: Optional[str] = Query(None),
    entry_type: Optional[str] = Query(None, alias="type"),
    limit: Optional[int] = Query(None, ge=1, le=200),
    directory: Optional[str] = Query(None),
    session_id: Optional[str] = Query(None),
    conversation_id: Optional[str] = Query(None),
) -> List[str]:
    """Alias for OpenCode-compatible file/directory search endpoint."""
    return await opencode_find_files(
        core=core,
        query=query,
        dirs=dirs,
        entry_type=entry_type,
        limit=limit,
        directory=directory,
        session_id=session_id,
        conversation_id=conversation_id,
    )


# Note: unified telemetry endpoint above returns the summary directly


@router.get("/api/v1/models")
async def list_models(core: PenguinCore = Depends(get_core)):
    """List available models with metadata.

    If no explicit model_configs are present, include at least the current model
    so clients can always see and select something.
    """
    try:
        raw_models = (
            core.list_available_models()
            if hasattr(core, "list_available_models")
            else []
        )
        models_list: List[Dict[str, Any]] = list(raw_models or [])

        if not models_list:
            # Fallback: expose the current model so the list is never empty
            cur = (
                core.get_current_model() if hasattr(core, "get_current_model") else None
            )
            if isinstance(cur, dict) and cur.get("model"):
                models_list.append(
                    {
                        "id": cur.get("model"),
                        "name": cur.get("model"),
                        "provider": cur.get("provider"),
                        "client_preference": cur.get("client_preference"),
                        "max_output_tokens": cur.get(
                            "max_output_tokens", cur.get("max_tokens")
                        ),  # Accept both keys
                        "temperature": cur.get("temperature"),
                        "vision_enabled": cur.get("vision_enabled", False),
                        "current": True,
                    }
                )

        return {"models": models_list}
    except Exception as e:
        logger.error(f"Error listing models: {e}")
        raise HTTPException(status_code=500, detail="Failed to list models")


@router.post("/api/v1/models/switch")
async def switch_model(
    request: ModelLoadRequest, core: PenguinCore = Depends(get_core)
):
    """Switch the active model at runtime."""
    try:
        ok = await core.load_model(request.model_id)
        if not ok:
            raise HTTPException(
                status_code=400, detail=f"Failed to load model '{request.model_id}'"
            )
        return {"ok": True, "current_model": core.get_current_model()}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error switching model to {request.model_id}: {e}")
        raise HTTPException(status_code=500, detail="Unexpected error switching model")


@router.get("/api/v1/models/discover")
async def discover_models(core: PenguinCore = Depends(get_core)):
    """Discover models via OpenRouter catalogue.

    Requires OPENROUTER_API_KEY in the server environment. Returns the raw
    OpenRouter catalogue mapped to a lean schema: id, name, provider,
    context_length, max_output_tokens, pricing (if present).
    """
    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        raise HTTPException(
            status_code=400, detail="OPENROUTER_API_KEY not set on server"
        )

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    # Optional headers for leaderboard attribution
    site_url = os.getenv("OPENROUTER_SITE_URL")
    site_title = os.getenv("OPENROUTER_SITE_TITLE") or "Penguin_AI"
    if site_url:
        headers["HTTP-Referer"] = site_url
    if site_title:
        headers["X-Title"] = site_title

    url = "https://openrouter.ai/api/v1/models"
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.get(url, headers=headers)
            resp.raise_for_status()
            payload = resp.json()
            data = payload.get("data", []) if isinstance(payload, dict) else []

            # Map to a slimmer structure
            mapped = []
            for m in data:
                try:
                    mapped.append(
                        {
                            "id": m.get("id"),
                            "name": m.get("name"),
                            "provider": (
                                m.get("id", "").split("/", 1)[0] if "id" in m else None
                            ),
                            "context_length": m.get("context_length"),
                            "max_output_tokens": m.get("max_output_tokens"),
                            "pricing": m.get("pricing"),
                        }
                    )
                except Exception:
                    continue

            return {"models": mapped}
    except httpx.HTTPStatusError as e:
        logger.error(
            f"OpenRouter catalogue error: {e.response.status_code} {e.response.text[:200]}"
        )
        raise HTTPException(
            status_code=502, detail="Upstream OpenRouter error fetching models"
        )
    except Exception as e:
        logger.error(f"OpenRouter catalogue request failed: {e}")
        raise HTTPException(
            status_code=502, detail="Failed to fetch OpenRouter model catalogue"
        )


@router.post("/api/v1/chat/message")
async def handle_chat_message(
    request: MessageRequest, core: PenguinCore = Depends(get_core)
):
    """Process a chat message, with optional conversation support."""
    temp_image_files: List[str] = []
    request_session_id: Optional[str] = None
    request_task: Optional[asyncio.Task[Any]] = None
    request_tracked = False
    reasoning_variant_snapshot: Optional[Dict[str, Any]] = None
    try:
        _setup_approval_websocket_callbacks()
        _setup_question_event_callbacks()

        if request.agent_id:
            _validate_agent_id(request.agent_id)
        if (
            request.agent_mode is not None
            and _normalize_agent_mode(request.agent_mode) is None
        ):
            raise HTTPException(
                status_code=400,
                detail="agent_mode must be one of: plan, build",
            )

        if not request.conversation_id and request.session_id:
            request.conversation_id = request.session_id

        # Prefer explicit session_id when provided; conversation_id is continuity metadata.
        effective_session_id = request.session_id or request.conversation_id
        request_session_id = (
            effective_session_id if isinstance(effective_session_id, str) else None
        )
        bound_directory = _bind_session_directory(
            core,
            effective_session_id,
            request.directory,
        )
        resolved_agent_mode = _resolve_agent_mode(
            core,
            request.agent_mode,
            effective_session_id,
        )
        _request_log_info(
            "chat.mode.request session=%s agent=%s mode=%s directory=%s",
            request_session_id or "unknown",
            request.agent_id or "default",
            resolved_agent_mode,
            bound_directory or request.directory,
        )
        await _persist_session_agent_mode(
            core,
            effective_session_id,
            resolved_agent_mode,
        )

        if request_session_id:
            request_task = asyncio.current_task()
            if request_task is not None:
                tasks_map = getattr(core, "_opencode_process_tasks", None)
                if not isinstance(tasks_map, dict):
                    tasks_map = {}
                    setattr(core, "_opencode_process_tasks", tasks_map)
                tasks = tasks_map.get(request_session_id)
                if not isinstance(tasks, set):
                    tasks = set()
                    tasks_map[request_session_id] = tasks
                tasks.add(request_task)
                request_tracked = True

        scope_directory = bound_directory or request.directory
        part_context_files, part_image_paths = _extract_paths_from_parts(
            request.parts,
            directory=scope_directory,
        )
        context_files = list(request.context_files or [])
        for file_path in part_context_files:
            if file_path not in context_files:
                context_files.append(file_path)
        inline_context_files = _extract_context_files_from_text(
            request.text,
            directory=scope_directory,
        )
        for file_path in inline_context_files:
            if file_path not in context_files:
                context_files.append(file_path)
        context_files = _normalize_context_files(
            context_files,
            directory=scope_directory,
        )
        if context_files:
            _request_log_info(
                "chat.context.files session=%s count=%s files=%s",
                request_session_id or "unknown",
                len(context_files),
                [
                    os.path.basename(path) if isinstance(path, str) else path
                    for path in context_files[:5]
                ],
            )

        image_paths = list(request.image_paths or [])
        for image_path in part_image_paths:
            if image_path not in image_paths:
                image_paths.append(image_path)

        execution_context = _build_execution_context(
            core,
            session_id=effective_session_id,
            conversation_id=effective_session_id,
            agent_id=request.agent_id,
            agent_mode=resolved_agent_mode,
            directory=bound_directory or request.directory,
        )

        requested_model = (
            request.model.strip() if isinstance(request.model, str) else ""
        )
        if requested_model:
            current_model = (
                core.get_current_model() if hasattr(core, "get_current_model") else None
            )
            current_raw = ""
            current_provider = ""
            if isinstance(current_model, dict):
                raw_model = current_model.get("model")
                raw_provider = current_model.get("provider")
                if isinstance(raw_model, str):
                    current_raw = raw_model.strip()
                if isinstance(raw_provider, str):
                    current_provider = raw_provider.strip()
            current_qualified = (
                f"{current_provider}/{current_raw}"
                if current_provider and current_raw
                else ""
            )

            if requested_model not in {current_raw, current_qualified}:
                candidates: list[str] = [requested_model]
                if "/" in requested_model:
                    _, remainder = requested_model.split("/", 1)
                    if remainder and remainder not in candidates:
                        candidates.append(remainder)

                model_configs = getattr(
                    getattr(core, "config", None), "model_configs", {}
                )
                if isinstance(model_configs, dict) and len(candidates) == 2:
                    full = candidates[0]
                    short = candidates[1]
                    if short in model_configs and full not in model_configs:
                        candidates = [short, full]

                loaded = False
                last_reason: Optional[str] = None
                for candidate in candidates:
                    loaded = await core.load_model(candidate)
                    if loaded:
                        break
                    reason = getattr(core, "_last_model_load_error", None)
                    if isinstance(reason, str) and reason.strip():
                        last_reason = reason.strip()
                    _request_log_info(
                        "chat.model.load_failed session=%s requested=%s candidate=%s reason=%s",
                        request_session_id or "unknown",
                        requested_model,
                        candidate,
                        last_reason or "unknown",
                    )

                if not loaded:
                    detail = f"Failed to load model '{requested_model}'"
                    if last_reason:
                        detail = f"{detail}: {last_reason}"
                    raise HTTPException(
                        status_code=400,
                        detail=detail,
                    )

        # Maybe?
        # # If no conversation_id is provided, try to use the most recent one
        # if not request.conversation_id:
        #     # This is a temporary solution until the frontend manages sessions more explicitly.
        #     # We fetch the list of conversations and use the most recent one.
        #     recent_conversations = core.list_conversations(limit=1)
        #     if recent_conversations:
        #         request.conversation_id = recent_conversations[0].get("id")
        #         logger.debug(f"No conversation_id provided. Using most recent: {request.conversation_id}")

        # Create input data dictionary from request
        input_data = {"text": request.text}

        # Add image paths if provided (with limit enforcement)
        if image_paths:
            if len(image_paths) > MAX_IMAGES_PER_REQUEST:
                logger.warning(
                    f"Truncating image_paths from {len(image_paths)} to {MAX_IMAGES_PER_REQUEST}"
                )
                image_paths = image_paths[:MAX_IMAGES_PER_REQUEST]

            materialized_paths, created_files = _materialize_image_paths(
                image_paths,
                directory=scope_directory,
            )
            if created_files:
                temp_image_files.extend(created_files)
            input_data["image_paths"] = materialized_paths
            existing_count = sum(
                1
                for value in materialized_paths
                if isinstance(value, str) and os.path.exists(value)
            )
            unresolved_data_urls = sum(
                1
                for value in materialized_paths
                if isinstance(value, str) and value.startswith("data:")
            )
            logger.info(
                "Image input received session=%s count=%s existing=%s data_urls=%s",
                effective_session_id,
                len(materialized_paths),
                existing_count,
                unresolved_data_urls,
            )

        # If reasoning is requested, capture reasoning chunks via a local callback
        reasoning_buf: List[str] = []
        stream_cb = None
        # Respect client streaming preference for OpenCode compatibility.
        effective_streaming = bool(request.streaming)
        if request.include_reasoning:
            effective_streaming = (
                True  # force streaming internally to collect reasoning
            )

            async def _rest_stream_cb(chunk: str, message_type: str = "assistant"):
                if message_type == "reasoning" and chunk:
                    reasoning_buf.append(chunk)

            stream_cb = _rest_stream_cb

        reasoning_variant_snapshot = _apply_reasoning_variant_override(
            core,
            request.variant,
        )
        model_config = getattr(core, "model_config", None)
        variant_value = (
            request.variant.strip().lower()
            if isinstance(request.variant, str) and request.variant.strip()
            else None
        )
        reasoning_payload = None
        reasoning_getter = getattr(model_config, "get_reasoning_config", None)
        if callable(reasoning_getter):
            try:
                resolved = reasoning_getter()
                if isinstance(resolved, dict):
                    reasoning_payload = dict(resolved)
            except Exception:
                logger.debug(
                    "Failed to resolve reasoning payload for request log",
                    exc_info=True,
                )
        if variant_value or reasoning_payload:
            _request_log_info(
                "chat.reasoning.request session=%s model=%s variant=%s reasoning=%s",
                request_session_id or "unknown",
                getattr(model_config, "model", None),
                variant_value,
                reasoning_payload,
            )

        # Process the message with all available options
        with execution_context_scope(execution_context):
            request_gate = getattr(core, "_opencode_request_gate", None)
            if not isinstance(request_gate, asyncio.Lock):
                request_gate = asyncio.Lock()
                setattr(core, "_opencode_request_gate", request_gate)

            async with request_gate:
                process_result = await core.process(
                    input_data=input_data,
                    context=request.context,
                    conversation_id=effective_session_id,
                    agent_id=request.agent_id,
                    max_iterations=request.max_iterations or 100,
                    context_files=context_files,
                    streaming=effective_streaming,
                    stream_callback=stream_cb,
                )

        # Build response
        if request_session_id:
            _queue_session_title_refresh(
                core,
                request_session_id,
                fallback_text=request.text if isinstance(request.text, str) else None,
            )

        resp: Dict[str, Any] = {
            "response": process_result.get("assistant_response", ""),
            "action_results": process_result.get("action_results", []),
        }
        if request.include_reasoning:
            resp["reasoning"] = "".join(reasoning_buf)
        return resp
    except asyncio.CancelledError:
        logger.info("Chat request cancelled for session %s", request_session_id)
        return {"response": "", "action_results": [], "aborted": True}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error processing message: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        _restore_reasoning_variant_override(core, reasoning_variant_snapshot)
        if request_tracked and request_session_id and request_task is not None:
            tasks_map = getattr(core, "_opencode_process_tasks", None)
            if isinstance(tasks_map, dict):
                tasks = tasks_map.get(request_session_id)
                if isinstance(tasks, set):
                    tasks.discard(request_task)
                    if not tasks:
                        tasks_map.pop(request_session_id, None)
        for temp_file in temp_image_files:
            try:
                Path(temp_file).unlink(missing_ok=True)
            except Exception:
                logger.debug("Failed to clean temp image file", exc_info=True)


@router.websocket("/api/v1/chat/stream")
async def stream_chat(websocket: WebSocket, core: PenguinCore = Depends(get_core)):
    """Stream chat responses in real-time using a queue."""
    await websocket.accept()
    _setup_approval_websocket_callbacks()
    _setup_question_event_callbacks()

    response_queue = asyncio.Queue()
    sender_task = None

    # Task to send messages from the queue to the client
    async def sender(queue: asyncio.Queue):
        nonlocal sender_task
        send_buffer = ""
        BUFFER_SEND_SIZE = 5  # Send after accumulating this many chars
        BUFFER_TIMEOUT = 0.1  # Or send after this many seconds of inactivity

        while True:
            item = None
            try:
                # Wait for a token with a timeout
                item = await asyncio.wait_for(queue.get(), timeout=BUFFER_TIMEOUT)

                if item is None:  # Sentinel value to stop
                    logger.debug("[Sender Task] Received stop signal.")
                    # Send any remaining buffer before stopping
                    if send_buffer:
                        logger.debug(
                            f"[Sender Task] Sending final buffer: '{send_buffer}'"
                        )
                        await websocket.send_json(
                            {"event": "token", "data": {"token": send_buffer}}
                        )
                        send_buffer = ""
                    queue.task_done()
                    break

                # Handle dict payloads {token, type, include_reasoning}
                if isinstance(item, dict):
                    tkn = item.get("token", "")
                    mtype = item.get("type", "assistant")
                    inc_reason = bool(item.get("include_reasoning", False))

                    if mtype == "reasoning":
                        # Flush any pending assistant buffer before reasoning
                        if send_buffer and inc_reason:
                            await websocket.send_json(
                                {"event": "token", "data": {"token": send_buffer}}
                            )
                            send_buffer = ""
                        # Emit reasoning token only if requested
                        if inc_reason and tkn:
                            await websocket.send_json(
                                {"event": "reasoning", "data": {"token": tkn}}
                            )
                        queue.task_done()
                        continue
                    else:
                        # Regular assistant content – buffer and coalesce
                        send_buffer += tkn
                        queue.task_done()
                        logger.debug(
                            f"[Sender Task] Added to buffer: '{tkn}'. Buffer size: {len(send_buffer)}"
                        )
                else:
                    # Backward-compat: plain string token
                    send_buffer += str(item)
                    queue.task_done()
                    logger.debug(
                        f"[Sender Task] Added to buffer: '{item}'. Buffer size: {len(send_buffer)}"
                    )

                # Send buffer if it reaches size threshold
                if len(send_buffer) >= BUFFER_SEND_SIZE:
                    logger.debug(
                        f"[Sender Task] Buffer reached size {BUFFER_SEND_SIZE}. Sending: '{send_buffer}'"
                    )
                    try:
                        await websocket.send_json(
                            {"event": "token", "data": {"token": send_buffer}}
                        )
                        send_buffer = ""  # Reset buffer
                    except (WebSocketDisconnect, RuntimeError) as e:
                        # Client disconnected or connection already closed
                        logger.info(
                            f"[Sender Task] Client disconnected during send: {e}"
                        )
                        break

            except asyncio.TimeoutError:
                # Timeout occurred - send buffer if it has content
                if send_buffer:
                    logger.debug(
                        f"[Sender Task] Timeout reached. Sending buffer: '{send_buffer}'"
                    )
                    try:
                        await websocket.send_json(
                            {"event": "token", "data": {"token": send_buffer}}
                        )
                        send_buffer = ""
                    except (WebSocketDisconnect, RuntimeError) as e:
                        # Client disconnected or connection already closed
                        logger.info(
                            f"[Sender Task] Client disconnected during timeout send: {e}"
                        )
                        break
                # Continue waiting for next token or stop signal
                continue

            except (websockets.exceptions.ConnectionClosed, WebSocketDisconnect):
                logger.info("[Sender Task] WebSocket closed by client.")
                break  # Exit if connection is closed
            except Exception as e:
                logger.error(f"[Sender Task] Unexpected error: {e}", exc_info=True)
                break

        logger.info("[Sender Task] Exiting.")

    # (per-request stream_callback is defined inside the loop to capture include_reasoning)

    try:
        while True:  # Keep handling incoming client messages
            # Guard receive_json against client disconnect
            try:
                data = await websocket.receive_json()  # Wait for a request from client
            except (WebSocketDisconnect, RuntimeError) as e:
                logger.info(f"Client disconnected during receive_json: {e}")
                break  # Exit the loop cleanly

            logger.info(f"Received request from client: {data.get('text', '')[:50]}...")

            # Start a new sender task for this message
            sender_task = asyncio.create_task(sender(response_queue))
            logger.info("Sender task started for this message.")

            # Extract parameters
            text = data.get("text", "")
            conversation_id = data.get("conversation_id")
            session_id = data.get("session_id")
            context_files = data.get("context_files")
            context = data.get("context")
            max_iterations = data.get("max_iterations", 100)
            image_paths = data.get("image_paths")  # Multiple images supported
            parts = data.get("parts")
            include_reasoning = bool(data.get("include_reasoning", False))
            variant = data.get("variant")
            agent_id = data.get("agent_id")
            agent_mode = data.get("agent_mode")
            directory = data.get("directory")

            # Prefer explicit session_id when provided; conversation_id is continuity metadata.
            effective_session_id = session_id or conversation_id
            bound_directory = _bind_session_directory(
                core,
                effective_session_id,
                directory,
            )
            resolved_agent_mode = _resolve_agent_mode(
                core,
                agent_mode if isinstance(agent_mode, str) else None,
                effective_session_id,
            )
            await _persist_session_agent_mode(
                core,
                effective_session_id,
                resolved_agent_mode,
            )
            execution_context = _build_execution_context(
                core,
                session_id=effective_session_id,
                conversation_id=effective_session_id,
                agent_id=agent_id,
                agent_mode=resolved_agent_mode,
                directory=bound_directory or directory,
            )

            scope_directory = bound_directory or directory
            part_context_files, part_image_paths = _extract_paths_from_parts(
                parts if isinstance(parts, list) else None,
                directory=scope_directory,
            )
            merged_context_files = (
                list(context_files) if isinstance(context_files, list) else []
            )
            for file_path in part_context_files:
                if file_path not in merged_context_files:
                    merged_context_files.append(file_path)
            inline_context_files = _extract_context_files_from_text(
                text,
                directory=scope_directory,
            )
            for file_path in inline_context_files:
                if file_path not in merged_context_files:
                    merged_context_files.append(file_path)
            context_files = _normalize_context_files(
                merged_context_files,
                directory=scope_directory,
            )
            if context_files:
                _request_log_info(
                    "chat.stream.context.files session=%s count=%s files=%s",
                    effective_session_id or "unknown",
                    len(context_files),
                    [
                        os.path.basename(path) if isinstance(path, str) else path
                        for path in context_files[:5]
                    ],
                )

            merged_image_paths = (
                list(image_paths) if isinstance(image_paths, list) else []
            )
            for image_path in part_image_paths:
                if image_path not in merged_image_paths:
                    merged_image_paths.append(image_path)
            image_paths = merged_image_paths

            # Log conversation ID for debugging
            print(
                f"[DEBUG] Processing message for conversation_id: {conversation_id}",
                flush=True,
            )
            logger.info(f"Processing message for conversation_id: {conversation_id}")

            if agent_id:
                _validate_agent_id(agent_id)

            input_data = {"text": text}
            if image_paths:
                if len(image_paths) > MAX_IMAGES_PER_REQUEST:
                    logger.warning(
                        f"Truncating image_paths from {len(image_paths)} to {MAX_IMAGES_PER_REQUEST}"
                    )
                    input_data["image_paths"] = image_paths[:MAX_IMAGES_PER_REQUEST]
                else:
                    input_data["image_paths"] = image_paths

            # Progress callback setup with connection state check
            progress_callback_task = None

            async def progress_callback(iteration, max_iter, message=None):
                nonlocal progress_callback_task
                # Skip if websocket is not connected
                try:
                    if websocket.client_state.name != "CONNECTED":
                        return
                except Exception:
                    return  # Can't check state, assume disconnected

                progress_callback_task = asyncio.create_task(
                    websocket.send_json(
                        {
                            "event": "progress",
                            "data": {
                                "iteration": iteration,
                                "max_iterations": max_iter,
                                "message": message,
                            },
                        }
                    )
                )
                try:
                    await progress_callback_task
                except asyncio.CancelledError:
                    logger.debug("Progress callback task cancelled")
                except (WebSocketDisconnect, RuntimeError):
                    logger.debug("WebSocket closed during progress callback")
                except Exception as e:
                    logger.error(f"Error sending progress update: {e}")

            process_task = None
            ui_event_handler = None
            try:
                if hasattr(core, "register_progress_callback"):
                    core.register_progress_callback(progress_callback)

                # Register UI event handler for tool events and other UI updates
                async def _stream_ui_event_handler(
                    event_type: str, data: Dict[str, Any]
                ):
                    # Skip if websocket is not connected
                    try:
                        if websocket.client_state.name != "CONNECTED":
                            return
                    except Exception:
                        return  # Can't check state, assume disconnected

                    try:
                        if event_type == "tool":
                            # Forward tool events directly to client
                            await websocket.send_json({"event": "tool", "data": data})
                        elif (
                            event_type == "message"
                            and data.get("message_type") == "action"
                        ):
                            # Also forward action messages for backwards compatibility
                            await websocket.send_json(
                                {"event": "message", "data": data}
                            )
                    except (WebSocketDisconnect, RuntimeError):
                        logger.debug(f"WebSocket closed during UI event: {event_type}")
                    except Exception as e:
                        logger.error(f"Error sending UI event via WebSocket: {e}")

                ui_event_handler = _stream_ui_event_handler
                # Subscribe to all event types via CLI event bus
                stream_cli_event_bus = CLIEventBus.get_sync()
                stream_ui_handlers = []
                for ev_type in EventType:
                    stream_cli_event_bus.subscribe(ev_type.value, ui_event_handler)
                    stream_ui_handlers.append((ev_type.value, ui_event_handler))
                logger.debug("Subscribed UI event handler to event bus for tool events")

                await websocket.send_json(
                    {"event": "start", "data": {}}
                )  # Signal start to client
                logger.info("Sent 'start' event to client.")

                # Run core.process as a task - NOTE: We don't await the *result* here immediately
                # The stream_callback puts tokens on the queue for the sender_task
                logger.info("Starting core.process...")

                # Define a per-request callback that preserves message_type
                async def per_request_stream_callback(
                    chunk: str, message_type: str = "assistant"
                ):
                    try:
                        await response_queue.put(
                            {
                                "token": chunk,
                                "type": message_type,
                                "include_reasoning": include_reasoning,
                            }
                        )
                    except Exception as e:
                        logger.error(f"Error enqueuing stream chunk: {e}")

                reasoning_variant_snapshot = _apply_reasoning_variant_override(
                    core,
                    variant if isinstance(variant, str) else None,
                )
                model_config = getattr(core, "model_config", None)
                variant_value = (
                    variant.strip().lower()
                    if isinstance(variant, str) and variant.strip()
                    else None
                )
                reasoning_payload = None
                reasoning_getter = getattr(model_config, "get_reasoning_config", None)
                if callable(reasoning_getter):
                    try:
                        resolved = reasoning_getter()
                        if isinstance(resolved, dict):
                            reasoning_payload = dict(resolved)
                    except Exception:
                        logger.debug(
                            "Failed to resolve reasoning payload for websocket request log",
                            exc_info=True,
                        )
                if variant_value or reasoning_payload:
                    _request_log_info(
                        "chat.stream.reasoning.request session=%s model=%s variant=%s reasoning=%s",
                        effective_session_id or "unknown",
                        getattr(model_config, "model", None),
                        variant_value,
                        reasoning_payload,
                    )
                try:
                    with execution_context_scope(execution_context):
                        process_task = asyncio.create_task(
                            core.process(
                                input_data=input_data,
                                conversation_id=effective_session_id,
                                agent_id=agent_id,
                                max_iterations=max_iterations,
                                context_files=context_files,
                                context=context,
                                streaming=True,
                                stream_callback=per_request_stream_callback,
                            )
                        )

                    # Wait for the core process to finish
                    process_result = await process_task
                finally:
                    _restore_reasoning_variant_override(
                        core, reasoning_variant_snapshot
                    )
                logger.info(
                    f"core.process finished. Result keys: {list(process_result.keys())}"
                )

                # Finalize streaming message (adds to conversation with reasoning)
                if hasattr(core, "finalize_streaming_message"):
                    core.finalize_streaming_message()
                    logger.debug("Finalized streaming message with reasoning")

                # Signal sender task to finish *after* core.process is done
                logger.debug("Putting stop signal (None) on queue for sender task.")
                await response_queue.put(None)

                # Wait for sender task to process remaining items and finish
                # Add a timeout to prevent hanging indefinitely
                try:
                    logger.debug("Waiting for sender task to finish...")
                    await asyncio.wait_for(
                        sender_task, timeout=10.0
                    )  # Wait max 10s for sender
                    logger.info("Sender task finished cleanly.")
                except asyncio.TimeoutError:
                    logger.warning(
                        "Sender task timed out after core.process completed. Cancelling."
                    )
                    if sender_task and not sender_task.done():
                        sender_task.cancel()
                except Exception as e:
                    logger.error(f"Error waiting for sender task: {e}", exc_info=True)
                    if sender_task and not sender_task.done():
                        sender_task.cancel()

                # Send final complete message AFTER sender is done
                logger.info("Sending 'complete' event to client.")
                complete_payload = {
                    "response": process_result.get("assistant_response", ""),
                    "action_results": process_result.get("action_results", []),
                }
                if include_reasoning:
                    complete_payload["reasoning"] = getattr(
                        core, "streaming_reasoning_content", ""
                    )

                try:
                    await websocket.send_json(
                        {"event": "complete", "data": complete_payload}
                    )
                    logger.info("Sent 'complete' event to client.")
                except (WebSocketDisconnect, RuntimeError) as e:
                    # Client disconnected before we could send complete event
                    logger.info(
                        f"Client disconnected before complete event could be sent: {e}"
                    )

            except WebSocketDisconnect as disconnect_err:
                # Client disconnected during processing - this is normal
                logger.info(
                    f"Client disconnected during message processing: {disconnect_err}"
                )
                # Ensure tasks are cancelled
                if process_task and not process_task.done():
                    process_task.cancel()
                if sender_task and not sender_task.done():
                    sender_task.cancel()
                break  # Exit loop on disconnect
            except Exception as process_err:
                logger.error(
                    f"Error during message processing: {process_err}", exc_info=True
                )
                # Try to send error to client if possible
                try:
                    await websocket.send_json(
                        {"event": "error", "data": {"message": str(process_err)}}
                    )
                except (WebSocketDisconnect, RuntimeError):
                    logger.info("Could not send error to client - connection closed")
                # Ensure tasks are cancelled on error
                if process_task and not process_task.done():
                    process_task.cancel()
                if sender_task and not sender_task.done():
                    sender_task.cancel()
                break  # Exit loop on processing error
            finally:
                # Clean up progress callback
                if (
                    hasattr(core, "progress_callbacks")
                    and progress_callback in core.progress_callbacks
                ):
                    core.progress_callbacks.remove(progress_callback)
                # Clean up UI event handler - unsubscribe from event bus
                if ui_event_handler and stream_ui_handlers:
                    for ev, h in stream_ui_handlers:
                        try:
                            stream_cli_event_bus.unsubscribe(ev, h)
                        except Exception:
                            pass
                    logger.debug("Unsubscribed UI event handler from event bus")
                # Ensure tasks are awaited/cancelled if they are still running (e.g., due to early exit)
                if process_task and not process_task.done():
                    process_task.cancel()
                if sender_task and not sender_task.done():
                    sender_task.cancel()
                # Wait briefly for tasks to cancel
                await asyncio.sleep(0.1)

    except WebSocketDisconnect:
        logger.info("WebSocket client disconnected")
    except RuntimeError as e:
        if "Cannot call" in str(e) and "close" in str(e):
            logger.info("WebSocket closed, cannot receive more messages.")
        else:
            logger.error(f"RuntimeError in WebSocket handler: {e}", exc_info=True)
    except Exception as e:
        logger.error(f"Unhandled error in websocket handler: {str(e)}", exc_info=True)
    finally:
        logger.info("Cleaning up stream_chat handler.")
        # Ensure sender task is cancelled if connection closes unexpectedly
        if sender_task and not sender_task.done():
            logger.info("Cancelling sender task due to handler exit.")
            sender_task.cancel()
            try:
                await sender_task  # Allow cancellation to propagate
            except asyncio.CancelledError:
                logger.debug("Sender task cancellation confirmed.")
            except Exception as final_cancel_err:
                logger.error(
                    f"Error during final sender task cancellation: {final_cancel_err}"
                )


# Enhanced Project Management API
class ProjectCreateRequest(BaseModel):
    name: str
    description: Optional[str] = None
    workspace_path: Optional[str] = None


class ProjectUpdateRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    status: Optional[str] = None


class TaskCreateRequest(BaseModel):
    project_id: str
    title: str
    description: Optional[str] = None
    parent_task_id: Optional[str] = None
    priority: Optional[int] = 1


class TaskUpdateRequest(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    status: Optional[str] = None
    priority: Optional[int] = None


# Project Management Endpoints
@router.post("/api/v1/projects")
async def create_project(
    request: ProjectCreateRequest, core: PenguinCore = Depends(get_core)
):
    """Create a new project."""
    try:
        project = await core.project_manager.create_project_async(
            name=request.name,
            description=request.description or f"Project: {request.name}",
            workspace_path=request.workspace_path,
        )
        return {
            "id": project.id,
            "name": project.name,
            "description": project.description,
            "status": project.status,
            "workspace_path": project.workspace_path,
            "created_at": project.created_at if project.created_at else None,
        }
    except Exception as e:
        logger.error(f"Error creating project: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/v1/projects")
async def list_projects(core: PenguinCore = Depends(get_core)):
    """List all projects."""
    try:
        projects = await core.project_manager.list_projects_async()
        return {
            "projects": [
                {
                    "id": project.id,
                    "name": project.name,
                    "description": project.description,
                    "status": project.status,
                    "workspace_path": project.workspace_path,
                    "created_at": project.created_at if project.created_at else None,
                    "updated_at": project.updated_at if project.updated_at else None,
                }
                for project in projects
            ]
        }
    except Exception as e:
        logger.error(f"Error listing projects: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/v1/projects/{project_id}")
async def get_project(project_id: str, core: PenguinCore = Depends(get_core)):
    """Get a specific project by ID."""
    try:
        project = await core.project_manager.get_project_async(project_id)
        if not project:
            raise HTTPException(
                status_code=404, detail=f"Project {project_id} not found"
            )

        # Get tasks for this project
        tasks = await core.project_manager.list_tasks_async(project_id=project_id)

        return {
            "id": project.id,
            "name": project.name,
            "description": project.description,
            "status": project.status,
            "workspace_path": project.workspace_path,
            "created_at": project.created_at if project.created_at else None,
            "updated_at": project.updated_at if project.updated_at else None,
            "tasks": [
                {
                    "id": task.id,
                    "title": task.title,
                    "status": task.status.value,
                    "priority": task.priority,
                    "created_at": task.created_at if task.created_at else None,
                }
                for task in tasks
            ],
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting project: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


# Temporarily disabled - update_project method not implemented in ProjectManager
# @router.put("/api/v1/projects/{project_id}")
# async def update_project(...):

# Temporarily disabled - delete_project method not implemented in ProjectManager
# @router.delete("/api/v1/projects/{project_id}")
# async def delete_project(...):


# Task Management Endpoints
@router.post("/api/v1/tasks")
async def create_task(
    request: TaskCreateRequest, core: PenguinCore = Depends(get_core)
):
    """Create a new task in a project."""
    try:
        task = await core.project_manager.create_task_async(
            project_id=request.project_id,
            title=request.title,
            description=request.description or request.title,
            parent_task_id=request.parent_task_id,
            priority=request.priority or 1,
        )
        return {
            "id": task.id,
            "project_id": task.project_id,
            "title": task.title,
            "description": task.description,
            "status": task.status.value,
            "priority": task.priority,
            "parent_task_id": task.parent_task_id,
            "created_at": task.created_at if task.created_at else None,
        }
    except Exception as e:
        logger.error(f"Error creating task: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/v1/tasks")
async def list_tasks(
    project_id: Optional[str] = None,
    status: Optional[str] = None,
    core: PenguinCore = Depends(get_core),
):
    """List tasks, optionally filtered by project or status."""
    try:
        # Parse status filter
        status_filter = None
        if status:
            from penguin.project.models import TaskStatus

            try:
                status_filter = TaskStatus(status.upper())
            except ValueError:
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid status: {status}. Valid options: pending, running, completed, failed",
                )

        tasks = await core.project_manager.list_tasks_async(
            project_id=project_id, status=status_filter
        )

        return {
            "tasks": [
                {
                    "id": task.id,
                    "project_id": task.project_id,
                    "title": task.title,
                    "description": task.description,
                    "status": task.status.value,
                    "priority": task.priority,
                    "parent_task_id": task.parent_task_id,
                    "created_at": task.created_at if task.created_at else None,
                    "updated_at": task.updated_at if task.updated_at else None,
                }
                for task in tasks
            ]
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error listing tasks: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/v1/tasks/{task_id}")
async def get_task(task_id: str, core: PenguinCore = Depends(get_core)):
    """Get a specific task by ID."""
    try:
        task = await core.project_manager.get_task_async(task_id)
        if not task:
            raise HTTPException(status_code=404, detail=f"Task {task_id} not found")

        return {
            "id": task.id,
            "project_id": task.project_id,
            "title": task.title,
            "description": task.description,
            "status": task.status.value,
            "priority": task.priority,
            "parent_task_id": task.parent_task_id,
            "created_at": task.created_at if task.created_at else None,
            "updated_at": task.updated_at if task.updated_at else None,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting task: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


# Temporarily disabled - general update_task method not implemented in ProjectManager
# Use update_task_status for status changes or implement full update_task method
# @router.put("/api/v1/tasks/{task_id}")
# async def update_task(...):

# Temporarily disabled - delete_task method not implemented in ProjectManager
# @router.delete("/api/v1/tasks/{task_id}")
# async def delete_task(...):


# Task Status Management
@router.post("/api/v1/tasks/{task_id}/start")
async def start_task(task_id: str, core: PenguinCore = Depends(get_core)):
    """Start a task (set status to running)."""
    try:
        from penguin.project.models import TaskStatus

        # Get the task first to check its current status
        task = await core.project_manager.get_task_async(task_id)
        if not task:
            raise HTTPException(status_code=404, detail=f"Task {task_id} not found")

        # If task is already active, that's fine - just return success
        if task.status == TaskStatus.ACTIVE:
            return {
                "id": task.id,
                "title": task.title,
                "status": task.status.value,
                "message": "Task is already active",
            }

        # Otherwise, try to transition to active
        success = core.project_manager.update_task_status(
            task_id, TaskStatus.ACTIVE, "Started via API"
        )
        if not success:
            raise HTTPException(
                status_code=400,
                detail=f"Cannot start task - invalid status transition from {task.status.value}",
            )

        # Get the updated task
        updated_task = await core.project_manager.get_task_async(task_id)
        return {
            "id": updated_task.id,
            "title": updated_task.title,
            "status": updated_task.status.value,
            "message": "Task started successfully",
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error starting task: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/v1/tasks/{task_id}/complete")
async def complete_task(task_id: str, core: PenguinCore = Depends(get_core)):
    """Complete a task (set status to completed)."""
    try:
        from penguin.project.models import TaskStatus

        success = core.project_manager.update_task_status(
            task_id, TaskStatus.COMPLETED, "Completed via API"
        )
        if not success:
            raise HTTPException(status_code=404, detail=f"Task {task_id} not found")

        # Get the updated task
        task = await core.project_manager.get_task_async(task_id)
        return {
            "id": task.id,
            "title": task.title,
            "status": task.status.value,
            "message": "Task completed successfully",
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error completing task: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/v1/tasks/{task_id}/execute")
async def execute_task_from_project(
    task_id: str, core: PenguinCore = Depends(get_core)
):
    """Execute a task using the Engine with project context."""
    try:
        # Get the task details
        task = await core.project_manager.get_task_async(task_id)
        if not task:
            raise HTTPException(status_code=404, detail=f"Task {task_id} not found")

        # Check if Engine is available
        if not hasattr(core, "engine") or not core.engine:
            raise HTTPException(
                status_code=503, detail="Engine layer not available for task execution"
            )

        # Set task to running status
        from penguin.project.models import TaskStatus

        core.project_manager.update_task_status(
            task_id, TaskStatus.ACTIVE, "Executing via Engine"
        )

        # Create task prompt
        task_prompt = f"Task: {task.title}"
        if task.description:
            task_prompt += f"\nDescription: {task.description}"

        # Execute task using Engine
        result = await core.engine.run_task(
            task_prompt=task_prompt,
            max_iterations=get_engine_max_iterations_default(),
            task_name=task.title,
            task_context={
                "task_id": task_id,
                "project_id": task.project_id,
                "priority": task.priority,
            },
            enable_events=True,
        )

        # Update task status based on result
        final_status = (
            TaskStatus.COMPLETED
            if result.get("status") == "completed"
            else TaskStatus.FAILED
        )
        core.project_manager.update_task_status(
            task_id, final_status, f"Engine execution result: {result.get('status')}"
        )

        return {
            "task_id": task_id,
            "status": result.get("status", "completed"),
            "response": result.get("assistant_response", ""),
            "iterations": result.get("iterations", 0),
            "execution_time": result.get("execution_time", 0),
            "action_results": result.get("action_results", []),
            "final_task_status": final_status.value,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error executing task: {str(e)}")
        # Set task to failed status
        try:
            from penguin.project.models import TaskStatus

            core.project_manager.update_task_status(
                task_id, TaskStatus.FAILED, f"Execution error: {str(e)}"
            )
        except:
            pass  # Don't fail the response if status update fails
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/v1/tasks/execute")
async def execute_task(
    request: TaskRequest,
    background_tasks: BackgroundTasks,
    core: PenguinCore = Depends(get_core),
):
    """Execute a task in the background."""
    # Use background tasks to execute long-running tasks
    background_tasks.add_task(
        core.start_run_mode,
        name=request.name,
        description=request.description,
        continuous=request.continuous,
        time_limit=request.time_limit,
    )
    return {"status": "started"}


# Enhanced task execution with Engine support
@router.post("/api/v1/tasks/execute-sync")
async def execute_task_sync(
    request: TaskRequest, core: PenguinCore = Depends(get_core)
):
    """Execute a task synchronously using the Engine layer."""
    try:
        # Check if Engine is available
        if not hasattr(core, "engine") or not core.engine:
            # Fallback to RunMode
            return await execute_task_via_runmode(request, core)

        # Use Engine for task execution
        task_prompt = f"Task: {request.name}"
        if request.description:
            task_prompt += f"\nDescription: {request.description}"

        # Execute task using Engine
        result = await core.engine.run_task(
            task_prompt=task_prompt,
            max_iterations=get_engine_max_iterations_default(),
            task_name=request.name,
            task_context={
                "continuous": request.continuous,
                "time_limit": request.time_limit,
            },
            enable_events=True,
        )

        return {
            "status": result.get("status", "completed"),
            "response": result.get("assistant_response", ""),
            "iterations": result.get("iterations", 0),
            "execution_time": result.get("execution_time", 0),
            "action_results": result.get("action_results", []),
            "task_metadata": result.get("task", {}),
        }

    except Exception as e:
        logger.error(f"Error executing task synchronously: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error executing task: {str(e)}")


async def execute_task_via_runmode(
    request: TaskRequest, core: PenguinCore
) -> Dict[str, Any]:
    """Fallback method using RunMode when Engine is not available."""
    try:
        # This would need to be modified to return result instead of running in background
        # For now, return an error indicating Engine is required
        raise HTTPException(
            status_code=503,
            detail="Engine layer not available. Use /api/v1/tasks/execute for background execution via RunMode.",
        )
    except Exception as e:
        logger.error(f"Error in RunMode fallback: {str(e)}")
        raise HTTPException(
            status_code=500, detail=f"Error in fallback execution: {str(e)}"
        )


@router.get("/api/v1/token-usage")
async def get_token_usage(core: PenguinCore = Depends(get_core)):
    """Get current token usage statistics."""
    return {"usage": core.get_token_usage()}


@router.get("/api/v1/conversations")
async def list_conversations(core: PenguinCore = Depends(get_core)):
    """List all available conversations."""
    try:
        return list_conversations_payload(core)
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Error retrieving conversations: {str(e)}"
        )


@router.get("/api/v1/conversations/{conversation_id}")
async def get_conversation(conversation_id: str, core: PenguinCore = Depends(get_core)):
    """Retrieve conversation details by ID."""
    try:
        return get_conversation_payload(core, conversation_id)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error loading conversation {conversation_id}: {str(e)}",
        )


@router.post("/api/v1/conversations/create")
async def create_conversation(core: PenguinCore = Depends(get_core)):
    """Create a new conversation."""
    try:
        return create_conversation_payload(core)
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Error creating conversation: {str(e)}"
        )


@router.get("/session")
async def session_list(
    core: PenguinCore = Depends(get_core),
    directory: Optional[str] = Query(None),
    roots: Optional[bool] = Query(False),
    start: Optional[int] = Query(None),
    search: Optional[str] = Query(None),
    limit: Optional[int] = Query(None),
):
    """OpenCode-compatible session list endpoint."""
    requested_directory = directory if isinstance(directory, str) else None
    resolved_directory = normalize_directory(requested_directory)
    if requested_directory and not resolved_directory:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid directory: {requested_directory}",
        )

    _remember_last_scoped_directory(core, resolved_directory)

    return list_session_infos(
        core,
        directory=resolved_directory,
        roots=bool(roots),
        start=start,
        search=search,
        limit=limit,
    )


@router.get("/session/status")
async def session_status(
    core: PenguinCore = Depends(get_core),
    directory: Optional[str] = Query(None),
):
    """OpenCode-compatible session.status endpoint."""
    requested_directory = directory if isinstance(directory, str) else None
    resolved_directory = normalize_directory(requested_directory)
    if requested_directory and not resolved_directory:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid directory: {requested_directory}",
        )

    _remember_last_scoped_directory(core, resolved_directory)

    statuses = list_session_statuses(core)
    if not resolved_directory:
        return statuses

    filtered: Dict[str, Dict[str, Any]] = {}
    for session_id, status in statuses.items():
        info = get_session_info(core, session_id)
        if info is None:
            continue
        session_dir = normalize_directory(info.get("directory"))
        if session_dir == resolved_directory:
            filtered[session_id] = status
    return filtered


@router.post("/session")
async def session_create(
    payload: Optional[Dict[str, Any]] = None,
    core: PenguinCore = Depends(get_core),
    directory: Optional[str] = Query(None),
):
    """OpenCode-compatible session.create endpoint."""
    body = payload if isinstance(payload, dict) else {}
    title = body.get("title")
    parent_id = body.get("parentID")
    permission = body.get("permission")
    agent_mode = body.get("agent_mode")
    if agent_mode is None:
        agent_mode = body.get("agentMode")

    if title is not None and not isinstance(title, str):
        raise HTTPException(status_code=400, detail="title must be a string")
    if parent_id is not None and not isinstance(parent_id, str):
        raise HTTPException(status_code=400, detail="parentID must be a string")
    if permission is not None and not isinstance(permission, list):
        raise HTTPException(status_code=400, detail="permission must be a list")
    normalized_agent_mode = _normalize_agent_mode(agent_mode)
    if agent_mode is not None and normalized_agent_mode is None:
        raise HTTPException(
            status_code=400,
            detail="agent_mode must be one of: plan, build",
        )

    if isinstance(parent_id, str) and parent_id.strip():
        parent = get_session_info(core, parent_id)
        if parent is None:
            raise HTTPException(
                status_code=404, detail=f"Session {parent_id} not found"
            )

    requested_directory = directory if isinstance(directory, str) else None
    resolved_directory = normalize_directory(requested_directory)
    if requested_directory and not resolved_directory:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid directory: {requested_directory}",
        )

    try:
        info = create_session_info(
            core,
            title=title if isinstance(title, str) else None,
            parent_id=parent_id if isinstance(parent_id, str) else None,
            directory=resolved_directory,
            permission=permission if isinstance(permission, list) else None,
            agent_mode=normalized_agent_mode,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    bound_directory = _bind_session_directory(core, info.get("id"), resolved_directory)
    if bound_directory:
        info["directory"] = bound_directory

    await _emit_session_created_event(core, info)
    return info


@router.get("/session/{session_id}")
async def session_get(session_id: str, core: PenguinCore = Depends(get_core)):
    """OpenCode-compatible session get endpoint."""
    session = get_session_info(core, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")
    return session


@router.patch("/session/{session_id}")
async def session_update(
    session_id: str,
    payload: Optional[Dict[str, Any]] = None,
    core: PenguinCore = Depends(get_core),
):
    """OpenCode-compatible session.update endpoint."""
    body = payload if isinstance(payload, dict) else {}
    title = body.get("title")
    archived = None
    agent_mode = body.get("agent_mode")
    if agent_mode is None:
        agent_mode = body.get("agentMode")

    if title is not None and not isinstance(title, str):
        raise HTTPException(status_code=400, detail="title must be a string")
    normalized_agent_mode = _normalize_agent_mode(agent_mode)
    if agent_mode is not None and normalized_agent_mode is None:
        raise HTTPException(
            status_code=400,
            detail="agent_mode must be one of: plan, build",
        )

    time_data = body.get("time")
    if isinstance(time_data, dict) and time_data.get("archived") is not None:
        raw_archived = time_data.get("archived")
        if isinstance(raw_archived, int):
            archived = raw_archived
        elif isinstance(raw_archived, str) and raw_archived.strip().isdigit():
            archived = int(raw_archived.strip())
        else:
            raise HTTPException(status_code=400, detail="time.archived must be an int")

    updated = update_session_info(
        core,
        session_id,
        title=title if isinstance(title, str) else None,
        archived=archived,
        agent_mode=normalized_agent_mode,
    )
    if updated is None:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")

    await _emit_session_updated_event(core, updated)
    return updated


class SessionForkRequest(BaseModel):
    messageID: Optional[str] = None


class SessionRevertRequest(BaseModel):
    messageID: Optional[str] = None
    partID: Optional[str] = None


@router.post("/session/{session_id}/fork")
async def session_fork(
    session_id: str,
    payload: Optional[SessionForkRequest] = None,
    core: PenguinCore = Depends(get_core),
    directory: Optional[str] = Query(None),
):
    """OpenCode-compatible session.fork endpoint."""
    source = get_session_info(core, session_id)
    if source is None:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")

    requested_directory = directory if isinstance(directory, str) else None
    resolved_directory = normalize_directory(requested_directory)
    if requested_directory and not resolved_directory:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid directory: {requested_directory}",
        )

    body = payload if isinstance(payload, SessionForkRequest) else SessionForkRequest()
    if body.messageID is not None and not isinstance(body.messageID, str):
        raise HTTPException(status_code=400, detail="messageID must be a string")

    info = fork_session(
        core,
        session_id,
        message_id=body.messageID,
        directory=resolved_directory,
    )
    if info is None:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")

    bound_directory = _bind_session_directory(
        core, info.get("id"), info.get("directory")
    )
    if bound_directory:
        info["directory"] = bound_directory

    await _emit_session_created_event(core, info)
    return info


@router.post("/session/{session_id}/revert")
async def session_revert(
    session_id: str,
    payload: Optional[SessionRevertRequest] = None,
    core: PenguinCore = Depends(get_core),
):
    """OpenCode-compatible session.revert endpoint."""
    existing = get_session_info(core, session_id)
    if existing is None:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")

    body = (
        payload if isinstance(payload, SessionRevertRequest) else SessionRevertRequest()
    )
    if not isinstance(body.messageID, str) or not body.messageID.strip():
        raise HTTPException(
            status_code=400, detail="messageID must be a non-empty string"
        )
    if body.partID is not None and not isinstance(body.partID, str):
        raise HTTPException(status_code=400, detail="partID must be a string")

    try:
        result = revert_session(
            core,
            session_id,
            message_id=body.messageID.strip(),
            part_id=body.partID.strip()
            if isinstance(body.partID, str) and body.partID.strip()
            else None,
        )
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))

    if result is None:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")

    info, diffs = result
    await _emit_session_updated_event(core, info)
    await _emit_session_diff_event(core, session_id, diffs)
    return info


@router.post("/session/{session_id}/unrevert")
async def session_unrevert(
    session_id: str,
    core: PenguinCore = Depends(get_core),
):
    """OpenCode-compatible session.unrevert endpoint."""
    existing = get_session_info(core, session_id)
    if existing is None:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")

    try:
        result = unrevert_session(core, session_id)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))

    if result is None:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")

    info, diffs = result
    await _emit_session_updated_event(core, info)
    await _emit_session_diff_event(core, session_id, diffs)
    return info


@router.delete("/session/{session_id}")
async def session_delete(session_id: str, core: PenguinCore = Depends(get_core)):
    """OpenCode-compatible session.delete endpoint."""
    existing = get_session_info(core, session_id)
    if existing is None:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")
    removed = remove_session_info(core, session_id)
    if not removed:
        raise HTTPException(
            status_code=500, detail=f"Failed to delete session {session_id}"
        )

    await _emit_session_deleted_event(core, existing)
    return True


@router.post("/session/{session_id}/abort")
async def session_abort(session_id: str, core: PenguinCore = Depends(get_core)):
    """OpenCode-compatible session.abort endpoint."""
    existing = get_session_info(core, session_id)
    if existing is None:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")

    handler = getattr(core, "abort_session", None)
    if not callable(handler):
        return False
    result = await handler(session_id)
    return bool(result)


@router.post("/session/{session_id}/summarize")
async def session_summarize(
    session_id: str,
    payload: Optional[Dict[str, Any]] = None,
    core: PenguinCore = Depends(get_core),
):
    """OpenCode-compatible session.summarize endpoint.

    Penguin semantics: title generation/refresh without compaction side effects.
    """
    body = payload if isinstance(payload, dict) else {}
    provider_id = body.get("providerID")
    model_id = body.get("modelID")
    auto = body.get("auto")

    if provider_id is not None and not isinstance(provider_id, str):
        raise HTTPException(status_code=400, detail="providerID must be a string")
    if model_id is not None and not isinstance(model_id, str):
        raise HTTPException(status_code=400, detail="modelID must be a string")
    if auto is not None and not isinstance(auto, bool):
        raise HTTPException(status_code=400, detail="auto must be a boolean")

    _title_log_info(
        "session.summarize session=%s provider=%s model=%s auto=%s",
        session_id,
        provider_id,
        model_id,
        auto,
    )

    result = await summarize_session_title(
        core,
        session_id,
        provider_id=provider_id if isinstance(provider_id, str) else None,
        model_id=model_id if isinstance(model_id, str) else None,
    )
    if result is None:
        _title_log_info(
            "session.summarize session=%s status=missing_session", session_id
        )
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")

    info = result.get("info") if isinstance(result, dict) else None
    changed = bool(result.get("changed")) if isinstance(result, dict) else False
    source = result.get("source") if isinstance(result, dict) else None
    snippet_count = (
        int(result.get("snippet_count", 0)) if isinstance(result, dict) else 0
    )
    used_fallback = (
        bool(result.get("used_fallback_text")) if isinstance(result, dict) else False
    )
    if changed and isinstance(info, dict):
        await _emit_session_updated_event(core, info)
    _title_log_info(
        "session.summarize session=%s status=ok changed=%s source=%s snippets=%s fallback=%s title=%r",
        session_id,
        changed,
        source,
        snippet_count,
        used_fallback,
        result.get("title") if isinstance(result, dict) else None,
    )

    return True


@router.get("/session/{session_id}/message")
async def session_messages(
    session_id: str,
    core: PenguinCore = Depends(get_core),
    limit: Optional[int] = Query(None),
):
    """OpenCode-compatible session.messages endpoint."""
    messages = get_session_messages(core, session_id, limit=limit)
    if messages is None:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")
    return messages


@router.get("/session/{session_id}/todo")
async def session_todo(session_id: str, core: PenguinCore = Depends(get_core)):
    """OpenCode-compatible session.todo endpoint."""
    todos = get_session_todo(core, session_id)
    if todos is None:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")
    return todos


@router.get("/session/{session_id}/diff")
async def session_diff(
    session_id: str,
    core: PenguinCore = Depends(get_core),
    messageID: Optional[str] = Query(None),
):
    """OpenCode-compatible session.diff endpoint."""
    diffs = get_session_diff(core, session_id, message_id=messageID)
    if diffs is None:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")
    return diffs


@router.get("/api/v1/session")
async def api_session_list(
    core: PenguinCore = Depends(get_core),
    directory: Optional[str] = Query(None),
    roots: Optional[bool] = Query(False),
    start: Optional[int] = Query(None),
    search: Optional[str] = Query(None),
    limit: Optional[int] = Query(None),
):
    """Alias for OpenCode-compatible session list endpoint."""
    return await session_list(
        core,
        directory=directory,
        roots=roots,
        start=start,
        search=search,
        limit=limit,
    )


@router.get("/api/v1/session/status")
async def api_session_status(
    core: PenguinCore = Depends(get_core),
    directory: Optional[str] = Query(None),
):
    """Alias for OpenCode-compatible session.status endpoint."""
    return await session_status(core=core, directory=directory)


@router.post("/api/v1/session")
async def api_session_create(
    payload: Optional[Dict[str, Any]] = None,
    core: PenguinCore = Depends(get_core),
    directory: Optional[str] = Query(None),
):
    """Alias for OpenCode-compatible session.create endpoint."""
    return await session_create(payload=payload, core=core, directory=directory)


@router.get("/api/v1/session/{session_id}")
async def api_session_get(session_id: str, core: PenguinCore = Depends(get_core)):
    """Alias for OpenCode-compatible session get endpoint."""
    return await session_get(session_id, core)


@router.patch("/api/v1/session/{session_id}")
async def api_session_update(
    session_id: str,
    payload: Optional[Dict[str, Any]] = None,
    core: PenguinCore = Depends(get_core),
):
    """Alias for OpenCode-compatible session.update endpoint."""
    return await session_update(session_id, payload=payload, core=core)


@router.delete("/api/v1/session/{session_id}")
async def api_session_delete(session_id: str, core: PenguinCore = Depends(get_core)):
    """Alias for OpenCode-compatible session.delete endpoint."""
    return await session_delete(session_id, core=core)


@router.post("/api/v1/session/{session_id}/fork")
async def api_session_fork(
    session_id: str,
    payload: Optional[SessionForkRequest] = None,
    core: PenguinCore = Depends(get_core),
    directory: Optional[str] = Query(None),
):
    """Alias for OpenCode-compatible session.fork endpoint."""
    return await session_fork(
        session_id,
        payload=payload,
        core=core,
        directory=directory,
    )


@router.post("/api/v1/session/{session_id}/revert")
async def api_session_revert(
    session_id: str,
    payload: Optional[SessionRevertRequest] = None,
    core: PenguinCore = Depends(get_core),
):
    """Alias for OpenCode-compatible session.revert endpoint."""
    return await session_revert(session_id, payload=payload, core=core)


@router.post("/api/v1/session/{session_id}/unrevert")
async def api_session_unrevert(
    session_id: str,
    core: PenguinCore = Depends(get_core),
):
    """Alias for OpenCode-compatible session.unrevert endpoint."""
    return await session_unrevert(session_id, core=core)


@router.post("/api/v1/session/{session_id}/abort")
async def api_session_abort(session_id: str, core: PenguinCore = Depends(get_core)):
    """Alias for OpenCode-compatible session.abort endpoint."""
    return await session_abort(session_id, core=core)


@router.post("/api/v1/session/{session_id}/summarize")
async def api_session_summarize(
    session_id: str,
    payload: Optional[Dict[str, Any]] = None,
    core: PenguinCore = Depends(get_core),
):
    """Alias for OpenCode-compatible session.summarize endpoint."""
    return await session_summarize(session_id, payload=payload, core=core)


@router.get("/api/v1/session/{session_id}/message")
async def api_session_messages(
    session_id: str,
    core: PenguinCore = Depends(get_core),
    limit: Optional[int] = Query(None),
):
    """Alias for OpenCode-compatible session.messages endpoint."""
    return await session_messages(session_id, core, limit=limit)


@router.get("/api/v1/session/{session_id}/todo")
async def api_session_todo(session_id: str, core: PenguinCore = Depends(get_core)):
    """Alias for OpenCode-compatible session.todo endpoint."""
    return await session_todo(session_id, core=core)


@router.get("/api/v1/session/{session_id}/diff")
async def api_session_diff(
    session_id: str,
    core: PenguinCore = Depends(get_core),
    messageID: Optional[str] = Query(None),
):
    """Alias for OpenCode-compatible session.diff endpoint."""
    return await session_diff(session_id, core=core, messageID=messageID)


# Conversation-specific checkpointing
class ConversationCheckpointRequest(BaseModel):
    conversation_id: Optional[str] = None
    name: Optional[str] = None
    description: Optional[str] = None


@router.post("/api/v1/conversations/checkpoint")
async def create_conversation_checkpoint(
    request: ConversationCheckpointRequest, core: PenguinCore = Depends(get_core)
):
    """Create a checkpoint for a specific conversation."""
    try:
        # Create checkpoint for current conversation (simplified approach)
        checkpoint_id = await core.create_checkpoint(
            name=request.name or "Conversation checkpoint",
            description=request.description
            or "Checkpoint created via conversation API",
        )

        if checkpoint_id:
            current_session = core.conversation_manager.get_current_session()
            return {
                "checkpoint_id": checkpoint_id,
                "conversation_id": current_session.id if current_session else None,
                "status": "created",
                "name": request.name,
                "description": request.description,
            }
        else:
            raise HTTPException(
                status_code=500, detail="Failed to create conversation checkpoint"
            )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating conversation checkpoint: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/v1/context-files")
async def list_context_files(core: PenguinCore = Depends(get_core)):
    """List all available context files."""
    try:
        files = core.list_context_files()
        return {"files": files}
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Error listing context files: {str(e)}"
        )


@router.post("/api/v1/context-files/load")
async def load_context_file(
    request: ContextFileRequest, core: PenguinCore = Depends(get_core)
):
    """Load a context file into the current conversation."""
    try:
        # Use the ConversationManager directly
        if hasattr(core, "conversation_manager"):
            success = core.conversation_manager.load_context_file(request.file_path)
        # Removed the fallback check for core.conversation_system
        else:
            raise HTTPException(
                status_code=500,
                detail="Conversation manager not found in core. Initialization might have failed.",
            )

        return {"success": success, "file_path": request.file_path}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error loading context file: {str(e)}")
        raise HTTPException(
            status_code=500, detail=f"Error loading context file: {str(e)}"
        )


@router.post("/api/v1/upload")
async def upload_file(
    file: UploadFile = File(...), core: PenguinCore = Depends(get_core)
):
    """Upload a file (primarily images) to be used in conversations."""
    try:
        # Create uploads directory if it doesn't exist
        uploads_dir = Path(WORKSPACE_PATH) / "uploads"
        uploads_dir.mkdir(exist_ok=True)

        # Generate a unique filename
        file_extension = file.filename.split(".")[-1] if "." in file.filename else ""
        unique_filename = f"{uuid.uuid4()}.{file_extension}"
        file_path = uploads_dir / unique_filename

        # Save the file
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        # Return the path that can be referenced in future requests
        return {
            "path": str(file_path),
            "filename": file.filename,
            "content_type": file.content_type,
        }
    except Exception as e:
        logger.error(f"Error uploading file: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error uploading file: {str(e)}")


@router.get("/api/v1/capabilities")
async def get_capabilities(core: PenguinCore = Depends(get_core)):
    """Get model capabilities like vision support."""
    try:
        capabilities = {
            "version": __version__,
            "vision_enabled": False,
            "streaming_enabled": True,
            "reasoning_supported": False,
            "reasoning_enabled": False,
        }

        # Check if the model supports vision
        if hasattr(core, "model_config") and hasattr(
            core.model_config, "vision_enabled"
        ):
            capabilities["vision_enabled"] = core.model_config.vision_enabled

        # Check streaming support
        if hasattr(core, "model_config") and hasattr(
            core.model_config, "streaming_enabled"
        ):
            capabilities["streaming_enabled"] = core.model_config.streaming_enabled

        if hasattr(core, "model_config") and hasattr(
            core.model_config, "supports_reasoning"
        ):
            capabilities["reasoning_supported"] = bool(
                core.model_config.supports_reasoning
            )

        if hasattr(core, "model_config") and hasattr(
            core.model_config, "reasoning_enabled"
        ):
            capabilities["reasoning_enabled"] = bool(
                core.model_config.reasoning_enabled
            )

        if hasattr(core, "model_config") and hasattr(core.model_config, "model"):
            capabilities.setdefault("model", getattr(core.model_config, "model"))

        return capabilities
    except Exception as e:
        logger.error(f"Error getting capabilities: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


# --- New WebSocket Endpoint for Run Mode Streaming ---
@router.websocket("/api/v1/tasks/stream")
async def stream_task(websocket: WebSocket, core: PenguinCore = Depends(get_core)):
    """Stream run mode task execution events in real-time."""
    await websocket.accept()
    task_execution = None
    run_mode_callback_task = None

    # Define the callback function to send events over WebSocket
    async def run_mode_event_callback(event_type: str, data: Dict[str, Any]):
        nonlocal run_mode_callback_task
        # Ensure this runs as a task to avoid blocking RunMode
        run_mode_callback_task = asyncio.create_task(
            websocket.send_json({"event": event_type, "data": data})
        )
        try:
            await run_mode_callback_task
        except asyncio.CancelledError:
            logger.debug(
                f"Run mode callback send task cancelled for event: {event_type}"
            )
        except Exception as e:
            logger.error(
                f"Error sending run mode event '{event_type}' via WebSocket: {e}"
            )
            # Optionally try to close WebSocket on send error
            # await websocket.close(code=1011) # Internal error

    try:
        while True:  # Keep connection open to handle potential multiple task requests?
            # Or expect one task request per connection?
            # Let's assume one task per connection for simplicity now.
            data = await websocket.receive_json()
            logger.info(f"Received run mode request: {data}")

            # Extract task parameters from the received data
            name = data.get("name")
            description = data.get("description")
            continuous = data.get("continuous", False)
            time_limit = data.get("time_limit")
            context = data.get("context")  # Allow passing context
            conversation_id = data.get(
                "conversation_id"
            )  # Get conversation ID from client

            if not name:
                await websocket.send_json(
                    {"event": "error", "data": {"message": "Task name is required."}}
                )
                await websocket.close(code=1008)  # Policy violation
                return  # Exit after closing

            # Load or create the session if conversation_id is provided
            if conversation_id and hasattr(core, "conversation_manager"):
                logger.info(f"Loading/creating session for RunMode: {conversation_id}")
                session = core.conversation_manager.session_manager.load_session(
                    conversation_id
                )
                if session:
                    logger.info(f"Loaded existing session: {conversation_id}")
                    core.conversation_manager.conversation.session = session
                else:
                    logger.info(f"Creating new session: {conversation_id}")
                    # Create a new session with the specified ID
                    from penguin.system.state import Session

                    new_session = Session(id=conversation_id)
                    core.conversation_manager.session_manager.sessions[
                        conversation_id
                    ] = (new_session, True)
                    core.conversation_manager.session_manager.current_session = (
                        new_session
                    )
                    core.conversation_manager.conversation.session = new_session

            # Start the run mode task in the background using core.start_run_mode
            logger.info(f"Starting streaming run mode for task: {name}")

            # Create callback to send events to WebSocket
            async def send_event_to_websocket(event: Dict[str, Any]):
                try:
                    from penguin.system.state import MessageCategory

                    # Serialize event data, converting enums to strings
                    def serialize_value(val):
                        if isinstance(val, MessageCategory):
                            return val.name
                        elif isinstance(val, dict):
                            return {k: serialize_value(v) for k, v in val.items()}
                        elif isinstance(val, list):
                            return [serialize_value(item) for item in val]
                        return val

                    event_type = event.get("type", "unknown")

                    # For message events, send the whole event with serialization
                    if event_type == "message":
                        serialized_event = serialize_value(event)
                        await websocket.send_json(
                            {
                                "event": "message",
                                "data": {
                                    "content": serialized_event.get("content", ""),
                                    "role": serialized_event.get("role", "system"),
                                    "category": serialized_event.get(
                                        "category", "SYSTEM"
                                    ),
                                },
                            }
                        )
                    # For status events, use status_type
                    else:
                        status_type = event.get("status_type", event_type)
                        serialized_data = serialize_value(event.get("data", event))
                        await websocket.send_json(
                            {"event": status_type, "data": serialized_data}
                        )
                except Exception as e:
                    logger.error(
                        f"Error sending event to WebSocket: {e}", exc_info=True
                    )

            # Store callback temporarily so Core._handle_run_mode_event can use it
            core._temp_ws_callback = send_event_to_websocket

            task_execution = asyncio.create_task(
                core.start_run_mode(
                    name=name,
                    description=description,
                    continuous=continuous,
                    time_limit=time_limit,
                    context=context,
                )
            )

            # Wait for the task execution to complete or error out
            try:
                await task_execution
                logger.info(f"Run mode task '{name}' execution finished.")
                # The 'complete' or 'error' event should be sent by RunMode itself
                # via the callback before the task finishes.
            except Exception as task_err:
                logger.error(
                    f"Error during run mode task '{name}' execution: {task_err}",
                    exc_info=True,
                )
                # Send error via websocket if possible
                if websocket.client_state == websocket.client_state.CONNECTED:
                    await websocket.send_json(
                        {
                            "event": "error",
                            "data": {"message": f"Task execution failed: {task_err}"},
                        }
                    )
            finally:
                # Clean up temporary callback
                if hasattr(core, "_temp_ws_callback"):
                    delattr(core, "_temp_ws_callback")

            # Once the task is done (completed, errored, interrupted), we can break the loop
            # Assuming one task per connection.
            break

    except WebSocketDisconnect:
        logger.info("Run mode WebSocket client disconnected")
        # If client disconnects, we should try to interrupt the running task
        if task_execution and not task_execution.done():
            logger.warning(
                f"Client disconnected, attempting to interrupt task execution..."
            )
            # Need a way to signal interruption to RunMode/Core gracefully.
            # For now, just cancel the asyncio task.
            task_execution.cancel()
    except RuntimeError as e:
        if "Cannot call" in str(e) and "close" in str(e):
            logger.info("Run mode WebSocket closed, cannot receive more messages.")
        else:
            logger.error(f"RuntimeError in stream_task handler: {e}", exc_info=True)
    except Exception as e:
        logger.error(f"Unhandled error in stream_task handler: {e}", exc_info=True)
        # Try to send error to client if connection is still open
        if websocket.client_state == websocket.client_state.CONNECTED:
            try:
                await websocket.send_json(
                    {"event": "error", "data": {"message": f"Server error: {e}"}}
                )
            except Exception as send_err:
                logger.error(f"Failed to send final error to client: {send_err}")
    finally:
        logger.info("Cleaning up stream_task handler.")
        # Ensure the task is cancelled if the handler exits unexpectedly
        if task_execution and not task_execution.done():
            logger.info("Cancelling run mode task due to handler exit.")
            task_execution.cancel()
            try:
                await task_execution  # Allow cancellation to propagate
            except asyncio.CancelledError:
                logger.debug("Run mode task cancellation confirmed.")
            except Exception as final_cancel_err:
                logger.error(
                    f"Error during final task cancellation: {final_cancel_err}"
                )
        # Close WebSocket connection if it's still open
        if websocket.client_state == websocket.client_state.CONNECTED:
            await websocket.close()


# --- End New WebSocket Endpoint ---

# --- Checkpoint Management Endpoints ---


@router.post("/api/v1/checkpoints/create")
async def create_checkpoint(
    request: CheckpointCreateRequest, core: PenguinCore = Depends(get_core)
):
    """Create a manual checkpoint of the current conversation state."""
    try:
        # Validate input - reject empty names or invalid descriptions
        if request.name is not None and request.name.strip() == "":
            raise HTTPException(
                status_code=400, detail="Checkpoint name cannot be empty"
            )

        # Validate description if provided
        if request.description is not None and not isinstance(request.description, str):
            raise HTTPException(
                status_code=400, detail="Checkpoint description must be a string"
            )

        checkpoint_id = await core.create_checkpoint(
            name=request.name, description=request.description
        )

        if checkpoint_id:
            return {
                "checkpoint_id": checkpoint_id,
                "status": "created",
                "name": request.name,
                "description": request.description,
            }
        else:
            raise HTTPException(status_code=500, detail="Failed to create checkpoint")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating checkpoint: {str(e)}")
        raise HTTPException(
            status_code=500, detail=f"Error creating checkpoint: {str(e)}"
        )


@router.get("/api/v1/checkpoints")
async def list_checkpoints(
    session_id: Optional[str] = None,
    limit: int = 50,
    core: PenguinCore = Depends(get_core),
):
    """List available checkpoints with optional filtering."""
    try:
        checkpoints = core.list_checkpoints(session_id=session_id, limit=limit)
        return {"checkpoints": checkpoints}
    except Exception as e:
        logger.error(f"Error listing checkpoints: {str(e)}")
        raise HTTPException(
            status_code=500, detail=f"Error listing checkpoints: {str(e)}"
        )


@router.post("/api/v1/checkpoints/{checkpoint_id}/rollback")
async def rollback_to_checkpoint(
    checkpoint_id: str, core: PenguinCore = Depends(get_core)
):
    """Rollback conversation to a specific checkpoint."""
    try:
        success = await core.rollback_to_checkpoint(checkpoint_id)

        if success:
            return {
                "status": "success",
                "checkpoint_id": checkpoint_id,
                "message": f"Successfully rolled back to checkpoint {checkpoint_id}",
            }
        else:
            raise HTTPException(
                status_code=404,
                detail=f"Checkpoint {checkpoint_id} not found or rollback failed",
            )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error rolling back to checkpoint {checkpoint_id}: {str(e)}")
        raise HTTPException(
            status_code=500, detail=f"Error rolling back to checkpoint: {str(e)}"
        )


@router.post("/api/v1/checkpoints/{checkpoint_id}/branch")
async def branch_from_checkpoint(
    checkpoint_id: str,
    request: CheckpointBranchRequest,
    core: PenguinCore = Depends(get_core),
):
    """Create a new conversation branch from a checkpoint."""
    try:
        branch_id = await core.branch_from_checkpoint(
            checkpoint_id, name=request.name, description=request.description
        )

        if branch_id:
            current_session = getattr(
                getattr(
                    getattr(core, "conversation_manager", None), "session_manager", None
                ),
                "current_session",
                None,
            )
            session_info = None
            current_session_id = getattr(current_session, "id", None)
            if isinstance(current_session_id, str):
                session_info = get_session_info(core, current_session_id)
                if isinstance(session_info, dict):
                    await _emit_session_created_event(core, session_info)

            return {
                "branch_id": branch_id,
                "source_checkpoint_id": checkpoint_id,
                "status": "created",
                "name": request.name,
                "description": request.description,
                "session": session_info,
            }
        else:
            raise HTTPException(
                status_code=404,
                detail=f"Checkpoint {checkpoint_id} not found or branch creation failed",
            )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating branch from checkpoint {checkpoint_id}: {str(e)}")
        raise HTTPException(
            status_code=500, detail=f"Error creating branch from checkpoint: {str(e)}"
        )


@router.get("/api/v1/checkpoints/stats")
async def get_checkpoint_stats(core: PenguinCore = Depends(get_core)):
    """Get statistics about the checkpointing system."""
    try:
        stats = core.get_checkpoint_stats()
        return stats
    except Exception as e:
        logger.error(f"Error getting checkpoint stats: {str(e)}")
        raise HTTPException(
            status_code=500, detail=f"Error getting checkpoint stats: {str(e)}"
        )


@router.post("/api/v1/checkpoints/cleanup")
async def cleanup_old_checkpoints(core: PenguinCore = Depends(get_core)):
    """Clean up old checkpoints according to retention policy."""
    try:
        cleaned_count = await core.cleanup_old_checkpoints()
        return {
            "status": "completed",
            "cleaned_count": cleaned_count,
            "message": f"Cleaned up {cleaned_count} old checkpoints",
        }
    except Exception as e:
        logger.error(f"Error cleaning up checkpoints: {str(e)}")
        raise HTTPException(
            status_code=500, detail=f"Error cleaning up checkpoints: {str(e)}"
        )


# --- Model Management Endpoints ---

# Note: unified models listing endpoint defined earlier (returns {"models": [...]})


@router.post("/api/v1/models/load")
async def load_model(request: ModelLoadRequest, core: PenguinCore = Depends(get_core)):
    """Switch to a different model."""
    try:
        success = await core.load_model(request.model_id)

        if success:
            current_model = None
            if core.model_config and core.model_config.model:
                current_model = core.model_config.model

            return {
                "status": "success",
                "model_id": request.model_id,
                "current_model": current_model,
                "message": f"Successfully loaded model: {request.model_id}",
            }
        else:
            raise HTTPException(
                status_code=400, detail=f"Failed to load model: {request.model_id}"
            )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error loading model {request.model_id}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error loading model: {str(e)}")


@router.get("/api/v1/models/current")
async def get_current_model(core: PenguinCore = Depends(get_core)):
    """Get information about the currently loaded model."""
    try:
        if not core.model_config:
            raise HTTPException(status_code=404, detail="No model configuration found")

        return {
            "model": core.model_config.model,
            "provider": core.model_config.provider,
            "client_preference": core.model_config.client_preference,
            "max_output_tokens": core.model_config.max_output_tokens,  # Output token limit
            "temperature": core.model_config.temperature,
            "streaming_enabled": core.model_config.streaming_enabled,
            "vision_enabled": core.model_config.vision_enabled,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting current model: {str(e)}")
        raise HTTPException(
            status_code=500, detail=f"Error getting current model: {str(e)}"
        )


# --- System Information and Diagnostics ---


@router.get("/api/v1/system/config")
async def get_runtime_config(core: PenguinCore = Depends(get_core)):
    """Get current runtime configuration (project root, workspace root, execution mode)."""
    try:
        return runtime_config_payload(core)
    except Exception as e:
        logger.error(f"Error getting runtime config: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/v1/system/settings")
async def get_system_settings(
    core: PenguinCore = Depends(get_core),
    directory: Optional[str] = Query(None),
    session_id: Optional[str] = Query(None),
    conversation_id: Optional[str] = Query(None),
):
    """Get Penguin settings locations and runtime metadata."""
    try:
        effective_session = session_id or conversation_id
        path_info = get_path_info(
            core, directory=directory, session_id=effective_session
        )
        effective_directory = (
            path_info.get("directory") if isinstance(path_info, dict) else None
        )
        return settings_locations_payload(
            core,
            cwd=effective_directory if isinstance(effective_directory, str) else None,
        )
    except Exception as e:
        logger.error(f"Error getting system settings: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/v1/system/config/project-root")
async def set_project_root(
    request: SystemConfigRequest, core: PenguinCore = Depends(get_core)
):
    """Set the active project root directory.

    This will update the project root for all components that subscribe to runtime
    configuration changes (e.g., ToolManager, file operations).
    """
    try:
        result = core.runtime_config.set_project_root(request.path)
        return {
            "status": "success",
            "message": result,
            "path": core.runtime_config.project_root,
            "active_root": core.runtime_config.active_root,
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error setting project root: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/v1/system/config/workspace-root")
async def set_workspace_root(
    request: SystemConfigRequest, core: PenguinCore = Depends(get_core)
):
    """Set the active workspace root directory.

    This will update the workspace root for all components that subscribe to runtime
    configuration changes (e.g., ToolManager, file operations).
    """
    try:
        result = core.runtime_config.set_workspace_root(request.path)
        return {
            "status": "success",
            "message": result,
            "path": core.runtime_config.workspace_root,
            "active_root": core.runtime_config.active_root,
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error setting workspace root: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/v1/system/config/execution-mode")
async def set_execution_mode(
    request: SystemConfigRequest, core: PenguinCore = Depends(get_core)
):
    """Set the execution mode (project or workspace).

    This determines which root directory is used as the active root for file operations.

    Args:
        request.path: Either 'project' or 'workspace'
    """
    try:
        # Use 'path' field to pass the mode value for consistency with other endpoints
        mode = request.path
        result = core.runtime_config.set_execution_mode(mode)
        return {
            "status": "success",
            "message": result,
            "execution_mode": core.runtime_config.execution_mode,
            "active_root": core.runtime_config.active_root,
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error setting execution mode: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/v1/system/config/llm")
async def set_llm_config(
    request: LLMConfigRequest, core: PenguinCore = Depends(get_core)
):
    """Configure LLM endpoint and Link integration at runtime.

    This endpoint is called by Link when starting a Penguin session to:
    1. Point Penguin at Link's inference proxy (base_url)
    2. Pass user context for billing attribution (link_user_id, etc.)

    Only non-None values in the request will update the configuration.

    Example request from Link:
        POST /api/v1/system/config/llm
        {
            "base_url": "http://localhost:3001/api/v1",
            "link_user_id": "user-123",
            "link_session_id": "sess-456"
        }
    """
    try:
        # Get or create LLM client with Link support
        llm_client = getattr(core, "_llm_client", None)

        if llm_client is None:
            # Initialize LLM client if not present
            from penguin.llm.client import LLMClient, LLMClientConfig, LinkConfig

            config = LLMClientConfig(
                base_url=request.base_url,
                link=LinkConfig(
                    user_id=request.link_user_id,
                    session_id=request.link_session_id,
                    agent_id=request.link_agent_id,
                    workspace_id=request.link_workspace_id,
                    api_key=request.link_api_key,
                ),
            )
            llm_client = LLMClient(core.model_config, config)
            core._llm_client = llm_client
        else:
            # Update existing client configuration
            llm_client.update_config(
                base_url=request.base_url,
                link_user_id=request.link_user_id,
                link_session_id=request.link_session_id,
                link_agent_id=request.link_agent_id,
                link_workspace_id=request.link_workspace_id,
                link_api_key=request.link_api_key,
            )

        return {
            "status": "success",
            "config": llm_client.get_status(),
        }
    except Exception as e:
        logger.error(f"Error setting LLM config: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/v1/system/config/llm")
async def get_llm_config(core: PenguinCore = Depends(get_core)):
    """Get current LLM configuration and Link integration status.

    Returns information about:
    - Current base_url (OpenRouter or Link proxy)
    - Whether Link integration is configured
    - Link user/session/agent IDs (if set)
    """
    try:
        llm_client = getattr(core, "_llm_client", None)

        if llm_client is None:
            return {
                "status": "not_configured",
                "message": "LLM client not initialized. Using default OpenRouter configuration.",
                "base_url": "https://openrouter.ai/api/v1",
                "link_configured": False,
            }

        return {"status": "configured", "config": llm_client.get_status()}
    except Exception as e:
        logger.error(f"Error getting LLM config: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/v1/system/info")
async def get_system_info(core: PenguinCore = Depends(get_core)):
    """Get comprehensive system information."""
    try:
        info = {
            "penguin_version": "0.1.0",  # Could be extracted from package info
            "engine_available": hasattr(core, "engine") and core.engine is not None,
            "checkpoints_enabled": core.get_checkpoint_stats().get("enabled", False),
            "current_model": None,
            "conversation_manager": {
                "active": hasattr(core, "conversation_manager")
                and core.conversation_manager is not None,
                "current_session_id": None,
                "total_messages": 0,
            },
            "tool_manager": {
                "active": hasattr(core, "tool_manager")
                and core.tool_manager is not None,
                "total_tools": 0,
            },
        }

        # Add current model info
        if core.model_config:
            info["current_model"] = {
                "model": core.model_config.model,
                "provider": core.model_config.provider,
                "streaming_enabled": core.model_config.streaming_enabled,
                "vision_enabled": core.model_config.vision_enabled,
            }

        # Add conversation manager details
        if hasattr(core, "conversation_manager") and core.conversation_manager:
            current_session = core.conversation_manager.get_current_session()
            if current_session:
                info["conversation_manager"]["current_session_id"] = current_session.id
                info["conversation_manager"]["total_messages"] = len(
                    current_session.messages
                )

        # Add tool manager details
        if hasattr(core, "tool_manager") and core.tool_manager:
            info["tool_manager"]["total_tools"] = len(
                getattr(core.tool_manager, "tools", {})
            )

        return info

    except Exception as e:
        logger.error(f"Error getting system info: {str(e)}")
        raise HTTPException(
            status_code=500, detail=f"Error getting system info: {str(e)}"
        )


@router.get("/api/v1/system/status")
async def get_system_status(core: PenguinCore = Depends(get_core)):
    """Get current system status including RunMode state."""
    try:
        status = {
            "status": "active",
            "runmode_status": getattr(
                core, "current_runmode_status_summary", "RunMode idle."
            ),
            "continuous_mode": getattr(core, "_continuous_mode", False),
            "streaming_active": getattr(core, "streaming_active", False),
            "token_usage": core.get_token_usage(),
            "timestamp": datetime.now().isoformat(),
        }

        return status

    except Exception as e:
        logger.error(f"Error getting system status: {str(e)}")
        raise HTTPException(
            status_code=500, detail=f"Error getting system status: {str(e)}"
        )


# ============================================================================
# Workflow / Orchestration API Endpoints
# ============================================================================


class WorkflowStartRequest(BaseModel):
    task_id: str
    blueprint_id: Optional[str] = None
    config: Optional[Dict[str, Any]] = None


class WorkflowSignalRequest(BaseModel):
    signal: str  # pause, resume, cancel, inject_feedback
    payload: Optional[Dict[str, Any]] = None


@router.get("/api/v1/workflows")
async def list_workflows(
    project_id: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 50,
    core: PenguinCore = Depends(get_core),
):
    """List workflows with optional filtering."""
    try:
        from penguin.orchestration import get_backend, WorkflowStatus

        backend = get_backend(workspace_path=WORKSPACE_PATH)

        # Set core reference for native backend
        if hasattr(backend, "set_core"):
            backend.set_core(core)

        # Parse status filter
        status_filter = None
        if status:
            try:
                status_filter = WorkflowStatus(status.lower())
            except ValueError:
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid status: {status}. Valid: pending, running, paused, completed, failed, cancelled",
                )

        workflows = await backend.list_workflows(
            project_id=project_id,
            status_filter=status_filter,
            limit=limit,
        )

        return {
            "workflows": [w.to_dict() for w in workflows],
            "count": len(workflows),
        }
    except HTTPException:
        raise
    except ImportError as e:
        raise HTTPException(status_code=503, detail=f"Orchestration not available: {e}")
    except Exception as e:
        logger.error(f"Error listing workflows: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/v1/workflows")
async def start_workflow(
    request: WorkflowStartRequest,
    core: PenguinCore = Depends(get_core),
):
    """Start a new ITUV workflow for a task."""
    try:
        from penguin.orchestration import get_backend

        backend = get_backend(workspace_path=WORKSPACE_PATH)

        if hasattr(backend, "set_core"):
            backend.set_core(core)

        # Get blueprint_id from task if not provided
        blueprint_id = request.blueprint_id
        if not blueprint_id:
            task = core.project_manager.get_task(request.task_id)
            if task:
                blueprint_id = getattr(task, "blueprint_id", None)

        workflow_id = await backend.start_workflow(
            task_id=request.task_id,
            blueprint_id=blueprint_id,
            config=request.config,
        )

        return {
            "workflow_id": workflow_id,
            "task_id": request.task_id,
            "status": "started",
        }
    except ImportError as e:
        raise HTTPException(status_code=503, detail=f"Orchestration not available: {e}")
    except Exception as e:
        logger.error(f"Error starting workflow: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/v1/workflows/{workflow_id}")
async def get_workflow(
    workflow_id: str,
    core: PenguinCore = Depends(get_core),
):
    """Get workflow status and details."""
    try:
        from penguin.orchestration import get_backend

        backend = get_backend(workspace_path=WORKSPACE_PATH)

        if hasattr(backend, "set_core"):
            backend.set_core(core)

        info = await backend.get_workflow_status(workflow_id)
        if not info:
            raise HTTPException(
                status_code=404, detail=f"Workflow {workflow_id} not found"
            )

        return info.to_dict()
    except HTTPException:
        raise
    except ImportError as e:
        raise HTTPException(status_code=503, detail=f"Orchestration not available: {e}")
    except Exception as e:
        logger.error(f"Error getting workflow: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/v1/workflows/{workflow_id}/signal")
async def signal_workflow(
    workflow_id: str,
    request: WorkflowSignalRequest,
    core: PenguinCore = Depends(get_core),
):
    """Send a signal to a workflow (pause, resume, cancel, inject_feedback)."""
    try:
        from penguin.orchestration import get_backend

        backend = get_backend(workspace_path=WORKSPACE_PATH)

        if hasattr(backend, "set_core"):
            backend.set_core(core)

        signal = request.signal.lower()

        if signal == "pause":
            success = await backend.pause_workflow(workflow_id)
        elif signal == "resume":
            success = await backend.resume_workflow(workflow_id)
        elif signal == "cancel":
            success = await backend.cancel_workflow(workflow_id)
        elif signal == "inject_feedback":
            if hasattr(backend, "signal_workflow"):
                success = await backend.signal_workflow(
                    workflow_id, "inject_feedback", request.payload
                )
            else:
                raise HTTPException(
                    status_code=400,
                    detail="inject_feedback signal not supported by this backend",
                )
        else:
            raise HTTPException(
                status_code=400,
                detail=f"Unknown signal: {signal}. Valid: pause, resume, cancel, inject_feedback",
            )

        if success:
            return {"status": "ok", "signal": signal, "workflow_id": workflow_id}
        else:
            raise HTTPException(
                status_code=400,
                detail=f"Failed to send signal {signal} to workflow {workflow_id}",
            )
    except HTTPException:
        raise
    except ImportError as e:
        raise HTTPException(status_code=503, detail=f"Orchestration not available: {e}")
    except Exception as e:
        logger.error(f"Error signaling workflow: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/v1/workflows/{workflow_id}/pause")
async def pause_workflow(workflow_id: str, core: PenguinCore = Depends(get_core)):
    """Convenience endpoint to pause a workflow."""
    return await signal_workflow(
        workflow_id, WorkflowSignalRequest(signal="pause"), core
    )


@router.post("/api/v1/workflows/{workflow_id}/resume")
async def resume_workflow(workflow_id: str, core: PenguinCore = Depends(get_core)):
    """Convenience endpoint to resume a workflow."""
    return await signal_workflow(
        workflow_id, WorkflowSignalRequest(signal="resume"), core
    )


@router.post("/api/v1/workflows/{workflow_id}/cancel")
async def cancel_workflow(workflow_id: str, core: PenguinCore = Depends(get_core)):
    """Convenience endpoint to cancel a workflow."""
    return await signal_workflow(
        workflow_id, WorkflowSignalRequest(signal="cancel"), core
    )


@router.get("/api/v1/orchestration/config")
async def get_orchestration_config(core: PenguinCore = Depends(get_core)):
    """Get current orchestration configuration."""
    try:
        from penguin.orchestration import get_config

        config = get_config()
        return config.to_dict()
    except ImportError as e:
        raise HTTPException(status_code=503, detail=f"Orchestration not available: {e}")
    except Exception as e:
        logger.error(f"Error getting orchestration config: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/v1/orchestration/health")
async def orchestration_health(core: PenguinCore = Depends(get_core)):
    """Check orchestration backend health."""
    try:
        from penguin.orchestration import get_backend, get_config

        config = get_config()
        backend = get_backend(workspace_path=WORKSPACE_PATH)

        # Basic health check
        health = {
            "backend": config.backend,
            "status": "healthy",
            "details": {},
        }

        # Check if backend has health_check method
        if hasattr(backend, "health_check"):
            health["details"] = await backend.health_check()

        # For Temporal, check connection
        if config.backend == "temporal":
            try:
                from penguin.orchestration.temporal import TemporalClient

                client = TemporalClient(config.temporal)
                connected = await client.is_connected()
                health["details"]["temporal_connected"] = connected
                if not connected:
                    health["status"] = "degraded"
            except Exception as e:
                health["status"] = "degraded"
                health["details"]["temporal_error"] = str(e)

        return health
    except ImportError as e:
        return {
            "backend": "unavailable",
            "status": "unavailable",
            "error": str(e),
        }
    except Exception as e:
        logger.error(f"Error checking orchestration health: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# Memory System API Endpoints
# ============================================================================
@router.post("/api/v1/memory/store")
async def store_memory(
    request: MemoryStoreRequest, core: PenguinCore = Depends(get_core)
):
    """Store a new memory entry."""
    try:
        # Use the ToolManager's memory functionality
        tool_manager = core.tool_manager

        # Check if memory provider is available
        if (
            not hasattr(tool_manager, "_memory_provider")
            or tool_manager._memory_provider is None
        ):
            # Initialize memory provider
            from penguin.memory.providers.factory import MemoryProviderFactory

            memory_config = (
                tool_manager.config.get("memory", {})
                if hasattr(tool_manager.config, "get")
                else {}
            )
            tool_manager._memory_provider = MemoryProviderFactory.create_provider(
                memory_config
            )
            await tool_manager._memory_provider.initialize()

        # Store the memory
        memory_id = await tool_manager._memory_provider.add_memory(
            content=request.content,
            metadata=request.metadata,
            categories=request.categories,
        )

        return {
            "memory_id": memory_id,
            "status": "success",
            "message": "Memory stored successfully",
        }

    except Exception as e:
        logger.error(f"Error storing memory: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/v1/memory/search")
async def search_memory(
    request: MemorySearchRequest, core: PenguinCore = Depends(get_core)
):
    """Search for memories."""
    try:
        # Use ToolManager's memory search functionality
        result = await core.tool_manager.perform_memory_search(
            query=request.query,
            k=request.max_results,
            memory_type=request.memory_type,
            categories=request.categories,
        )

        # Parse the JSON result from perform_memory_search
        import json

        try:
            parsed_result = json.loads(result)
            if isinstance(parsed_result, dict) and "error" in parsed_result:
                raise HTTPException(status_code=500, detail=parsed_result["error"])

            return {
                "query": request.query,
                "results": parsed_result
                if isinstance(parsed_result, list)
                else [parsed_result],
                "count": len(parsed_result) if isinstance(parsed_result, list) else 1,
            }
        except json.JSONDecodeError:
            # If it's not JSON, return as text
            return {
                "query": request.query,
                "results": [{"content": result}],
                "count": 1,
            }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error searching memory: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/v1/memory/{memory_id}")
async def get_memory(memory_id: str, core: PenguinCore = Depends(get_core)):
    """Get a specific memory by ID."""
    try:
        # Access memory provider
        tool_manager = core.tool_manager
        if (
            not hasattr(tool_manager, "_memory_provider")
            or tool_manager._memory_provider is None
        ):
            raise HTTPException(status_code=500, detail="Memory system not initialized")

        memory = await tool_manager._memory_provider.get_memory(memory_id)
        if not memory:
            raise HTTPException(status_code=404, detail=f"Memory {memory_id} not found")

        return memory

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error retrieving memory: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/v1/memory/stats")
async def get_memory_stats(core: PenguinCore = Depends(get_core)):
    """Get memory system statistics."""
    try:
        tool_manager = core.tool_manager
        if (
            not hasattr(tool_manager, "_memory_provider")
            or tool_manager._memory_provider is None
        ):
            return {"total_memories": 0, "status": "not_initialized"}

        stats = await tool_manager._memory_provider.get_memory_stats()
        return stats

    except Exception as e:
        logger.error(f"Error getting memory stats: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


class AgentPatchRequest(BaseModel):
    paused: Optional[bool] = None


class MessageEnvelope(BaseModel):
    recipient: str
    content: Any
    message_type: Optional[str] = "message"
    channel: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


# ============================================================================
# Security/Permission Configuration Endpoints
# ============================================================================

# Lazy import to avoid circular imports
_approval_manager = None
_question_manager = None


def _get_approval_manager():
    """Get the singleton ApprovalManager instance."""
    global _approval_manager
    if _approval_manager is None:
        from penguin.security.approval import get_approval_manager

        _approval_manager = get_approval_manager()
    return _approval_manager


def _get_question_manager():
    """Get the singleton QuestionManager instance."""
    global _question_manager
    if _question_manager is None:
        from penguin.security.question import get_question_manager

        _question_manager = get_question_manager()
    return _question_manager


def _get_default_capabilities(mode: str, enabled: bool) -> Dict[str, Any]:
    """Generate default capabilities based on mode."""
    if not enabled:
        return {
            "mode": "yolo",
            "can": ["Everything (YOLO mode - no restrictions)"],
            "cannot": [],
            "requires_approval": [],
        }

    if mode == "read_only":
        return {
            "mode": "read_only",
            "can": ["Read files", "Search", "Analyze", "View git status"],
            "cannot": ["Write files", "Delete files", "Execute commands", "Git push"],
            "requires_approval": [],
        }
    elif mode == "full":
        return {
            "mode": "full",
            "can": ["All operations"],
            "cannot": [],
            "requires_approval": ["Destructive operations"],
        }
    else:  # workspace
        return {
            "mode": "workspace",
            "can": [
                "Read/write within workspace",
                "Read/write within project",
                "Safe commands",
            ],
            "cannot": [
                "Write outside boundaries",
                "Access system paths",
                "Modify sensitive files",
            ],
            "requires_approval": ["File deletion", "Git push"],
        }


@router.get("/api/v1/security/config")
async def get_security_config(core: PenguinCore = Depends(get_core)):
    """Get current security/permission configuration.

    Returns the active security mode, enabled status, and capabilities summary.
    """
    try:
        # Get runtime config if available
        runtime_config = getattr(core, "runtime_config", None)

        if runtime_config:
            mode = runtime_config.security_mode
            enabled = runtime_config.security_enabled
            workspace_root = runtime_config.workspace_root
            project_root = runtime_config.project_root
        else:
            # Fallback to defaults
            mode = "workspace"
            enabled = True
            workspace_root = str(WORKSPACE_PATH)
            project_root = os.getcwd()

        # Get capabilities summary from permission enforcer if available
        capabilities = None
        if hasattr(core, "tool_manager") and core.tool_manager:
            enforcer = getattr(core.tool_manager, "permission_enforcer", None)
            if enforcer:
                capabilities = enforcer.get_capabilities_summary()

        if capabilities is None:
            # Generate default capabilities based on mode
            capabilities = _get_default_capabilities(mode, enabled)

        return {
            "mode": mode,
            "enabled": enabled,
            "workspace_root": workspace_root,
            "project_root": project_root,
            "capabilities": capabilities,
            "yolo_mode": not enabled,
        }

    except Exception as e:
        logger.error(f"Error getting security config: {str(e)}")
        raise HTTPException(
            status_code=500, detail=f"Error getting security config: {str(e)}"
        )


@router.patch("/api/v1/security/config")
async def update_security_config(
    request: SecurityConfigUpdate, core: PenguinCore = Depends(get_core)
):
    """Update security/permission configuration at runtime.

    Allows changing:
    - mode: Permission mode (read_only, workspace, full)
    - enabled: Toggle permission checks (False = YOLO mode)

    Changes take effect immediately for new tool executions.
    """
    try:
        runtime_config = getattr(core, "runtime_config", None)
        if not runtime_config:
            raise HTTPException(
                status_code=503, detail="Runtime configuration not available"
            )

        results = []

        # Update mode if provided
        if request.mode is not None:
            valid_modes = ("read_only", "workspace", "full")
            if request.mode.lower() not in valid_modes:
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid mode '{request.mode}'. Must be one of: {valid_modes}",
                )
            result = runtime_config.set_security_mode(request.mode)
            results.append(result)

        # Update enabled status if provided
        if request.enabled is not None:
            result = runtime_config.set_security_enabled(request.enabled)
            results.append(result)

        # Get updated config
        return {
            "success": True,
            "message": "; ".join(results) if results else "No changes made",
            "current": {
                "mode": runtime_config.security_mode,
                "enabled": runtime_config.security_enabled,
                "yolo_mode": not runtime_config.security_enabled,
            },
        }

    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error updating security config: {str(e)}")
        raise HTTPException(
            status_code=500, detail=f"Error updating security config: {str(e)}"
        )


@router.post("/api/v1/security/yolo")
async def toggle_yolo_mode(enable: bool = True, core: PenguinCore = Depends(get_core)):
    """Quick toggle for YOLO mode (disable/enable all permission checks).

    Args:
        enable: True to enable YOLO mode (disable checks), False to restore checks

    This is a convenience endpoint equivalent to PATCH /api/v1/security/config with enabled=!enable
    """
    try:
        runtime_config = getattr(core, "runtime_config", None)
        if not runtime_config:
            raise HTTPException(
                status_code=503, detail="Runtime configuration not available"
            )

        # YOLO mode means checks are DISABLED
        result = runtime_config.set_security_enabled(not enable)

        return {
            "success": True,
            "yolo_mode": enable,
            "message": result,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error toggling YOLO mode: {str(e)}")
        raise HTTPException(
            status_code=500, detail=f"Error toggling YOLO mode: {str(e)}"
        )


@router.get("/api/v1/security/audit")
async def get_audit_log(
    limit: int = Query(
        default=100, ge=1, le=1000, description="Maximum entries to return (1-1000)"
    ),
    result: Optional[str] = Query(
        default=None, description="Filter by result (allow/ask/deny)"
    ),
    category: Optional[str] = Query(default=None, description="Filter by category"),
    agent_id: Optional[str] = Query(default=None, description="Filter by agent ID"),
):
    """Get recent permission audit log entries.

    Returns a list of recent permission checks with their results.
    Useful for debugging permission issues and understanding what operations
    were allowed or denied.

    Query parameters:
    - limit: Maximum entries to return (default 100, max 1000)
    - result: Filter by result ("allow", "ask", "deny")
    - category: Filter by category ("filesystem", "process", "network", etc.)
    - agent_id: Filter by agent ID
    """
    try:
        from penguin.security.audit import get_audit_logger

        audit_logger = get_audit_logger()
        entries = audit_logger.get_recent_entries(
            limit=limit,
            result_filter=result,
            category_filter=category,
            agent_filter=agent_id,
        )

        return {
            "entries": [e.to_dict() for e in entries],
            "total": len(entries),
            "filters": {
                "limit": limit,
                "result": result,
                "category": category,
                "agent_id": agent_id,
            },
        }

    except ImportError as e:
        raise HTTPException(
            status_code=503, detail=f"Audit module not available: {str(e)}"
        )
    except Exception as e:
        logger.error(f"Error getting audit log: {str(e)}")
        raise HTTPException(
            status_code=500, detail=f"Error getting audit log: {str(e)}"
        )


@router.get("/api/v1/security/audit/stats")
async def get_audit_stats():
    """Get audit statistics.

    Returns summary statistics about permission checks:
    - Total number of checks
    - Breakdown by result (allow/ask/deny)
    - Breakdown by category
    """
    try:
        from penguin.security.audit import get_audit_logger

        audit_logger = get_audit_logger()
        stats = audit_logger.get_stats()

        return {
            "total": stats.get("total", 0),
            "by_result": {
                "allow": stats.get("allow", 0),
                "ask": stats.get("ask", 0),
                "deny": stats.get("deny", 0),
            },
            "by_category": stats.get("by_category", {}),
        }

    except ImportError as e:
        raise HTTPException(
            status_code=503, detail=f"Audit module not available: {str(e)}"
        )
    except Exception as e:
        logger.error(f"Error getting audit stats: {str(e)}")
        raise HTTPException(
            status_code=500, detail=f"Error getting audit stats: {str(e)}"
        )


# ==========================================================================
# OpenCode Permission + Question Endpoints
# ==========================================================================


@router.get("/permission")
@router.get("/api/v1/permission")
async def list_pending_permissions(
    sessionID: Optional[str] = Query(None),
    session_id: Optional[str] = Query(None),
):
    """List pending permissions in OpenCode-compatible shape."""
    try:
        _setup_approval_websocket_callbacks()
        manager = _get_approval_manager()
        target_session = session_id or sessionID
        pending = manager.get_pending(session_id=target_session)
        return [
            _approval_request_to_permission_payload(request.to_dict())
            for request in pending
        ]
    except Exception as e:
        logger.error("Error listing permissions: %s", e)
        raise HTTPException(status_code=500, detail=f"Error listing permissions: {e}")


@router.post("/permission/{request_id}/reply")
@router.post("/api/v1/permission/{request_id}/reply")
async def reply_permission_request(
    request_id: str,
    action: PermissionReplyAction,
):
    """Reply to a pending permission request.

    Supported replies: ``once`` | ``always`` | ``reject``.
    """
    try:
        from penguin.security.approval import ApprovalScope

        _setup_approval_websocket_callbacks()
        manager = _get_approval_manager()
        existing = manager.get_request(request_id)
        if existing is None:
            raise HTTPException(
                status_code=404,
                detail=f"Permission request not found: {request_id}",
            )

        existing_dict = existing.to_dict()
        if existing_dict.get("status") != "pending":
            return True

        reply = action.reply.strip().lower() if isinstance(action.reply, str) else ""
        if reply == "reject":
            resolved = manager.deny(request_id)
            if resolved and isinstance(action.message, str) and action.message.strip():
                resolved.context["message"] = action.message.strip()
        elif reply == "once":
            resolved = manager.approve(request_id, scope=ApprovalScope.ONCE)
        elif reply == "always":
            raw_pattern = existing_dict.get("resource")
            pattern = (
                raw_pattern.strip()
                if isinstance(raw_pattern, str) and raw_pattern.strip()
                else "*"
            )
            resolved = manager.approve(
                request_id,
                scope=ApprovalScope.PATTERN,
                pattern=pattern,
            )
        else:
            raise HTTPException(
                status_code=400,
                detail="reply must be one of: once, always, reject",
            )

        if resolved is None:
            raise HTTPException(
                status_code=404,
                detail=f"Permission request not found or already resolved: {request_id}",
            )

        return True
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error replying permission request: %s", e)
        raise HTTPException(
            status_code=500,
            detail=f"Error replying permission request: {e}",
        )


@router.get("/question")
@router.get("/api/v1/question")
async def list_pending_questions(
    sessionID: Optional[str] = Query(None),
    session_id: Optional[str] = Query(None),
):
    """List pending user questions in OpenCode-compatible shape."""
    try:
        _setup_question_event_callbacks()
        manager = _get_question_manager()
        target_session = session_id or sessionID
        pending = manager.list_pending(session_id=target_session)
        return [request.to_dict() for request in pending]
    except Exception as e:
        logger.error("Error listing questions: %s", e)
        raise HTTPException(status_code=500, detail=f"Error listing questions: {e}")


@router.post("/question/{request_id}/reply")
@router.post("/api/v1/question/{request_id}/reply")
async def reply_question_request(
    request_id: str,
    action: QuestionReplyAction,
):
    """Reply to a pending question request."""
    try:
        _setup_question_event_callbacks()
        manager = _get_question_manager()
        existing = manager.get_request(request_id)
        if existing is None:
            raise HTTPException(
                status_code=404,
                detail=f"Question request not found: {request_id}",
            )
        if getattr(getattr(existing, "status", None), "value", "") != "pending":
            return True

        resolved = manager.reply(request_id, answers=action.answers)
        if resolved is None:
            raise HTTPException(
                status_code=404,
                detail=f"Question request not found or already resolved: {request_id}",
            )
        return True
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error replying question request: %s", e)
        raise HTTPException(
            status_code=500,
            detail=f"Error replying question request: {e}",
        )


@router.post("/question/{request_id}/reject")
@router.post("/api/v1/question/{request_id}/reject")
async def reject_question_request(request_id: str):
    """Reject a pending question request."""
    try:
        _setup_question_event_callbacks()
        manager = _get_question_manager()
        existing = manager.get_request(request_id)
        if existing is None:
            raise HTTPException(
                status_code=404,
                detail=f"Question request not found: {request_id}",
            )
        if getattr(existing.status, "value", "") != "pending":
            return True

        resolved = manager.reject(request_id)
        if resolved is None:
            raise HTTPException(
                status_code=404,
                detail=f"Question request not found or already resolved: {request_id}",
            )
        return True
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error rejecting question request: %s", e)
        raise HTTPException(
            status_code=500,
            detail=f"Error rejecting question request: {e}",
        )


# ============================================================================
# Approval Flow Endpoints
# ============================================================================
# NOTE: Route order matters in FastAPI - specific paths must come before path parameters
# Order: /approvals -> /approvals/pre-approve -> /approvals/session/* -> /approvals/{id}


@router.get("/api/v1/approvals")
async def list_pending_approvals(
    session_id: Optional[str] = None,
):
    """List all pending approval requests.

    Args:
        session_id: Optional filter by session ID

    Returns:
        List of pending approval requests
    """
    try:
        manager = _get_approval_manager()
        pending = manager.get_pending(session_id=session_id)

        return {
            "pending": [r.to_dict() for r in pending],
            "count": len(pending),
        }

    except Exception as e:
        logger.error(f"Error listing approvals: {str(e)}")
        raise HTTPException(
            status_code=500, detail=f"Error listing approvals: {str(e)}"
        )


@router.post("/api/v1/approvals/pre-approve")
async def pre_approve_operation(request: PreApprovalRequest):
    """Pre-approve an operation for a session or globally.

    This allows bypassing the approval flow for specific operations,
    useful for automation/CI scenarios.

    Args:
        request: Pre-approval configuration

    Returns:
        The created pre-approval
    """
    try:
        manager = _get_approval_manager()

        approval = manager.pre_approve(
            operation=request.operation,
            pattern=request.pattern,
            session_id=request.session_id,
            ttl_seconds=request.ttl_seconds,
        )

        scope = (
            "global" if request.session_id is None else f"session={request.session_id}"
        )
        pattern_desc = f" with pattern '{request.pattern}'" if request.pattern else ""

        return {
            "success": True,
            "message": f"Pre-approved '{request.operation}'{pattern_desc} for {scope}",
            "approval": {
                "operation": approval.operation,
                "pattern": approval.pattern,
                "session_id": approval.session_id,
                "created_at": approval.created_at.isoformat(),
                "expires_at": approval.expires_at.isoformat()
                if approval.expires_at
                else None,
            },
        }

    except Exception as e:
        logger.error(f"Error pre-approving operation: {str(e)}")
        raise HTTPException(
            status_code=500, detail=f"Error pre-approving operation: {str(e)}"
        )


@router.get("/api/v1/approvals/session/{session_id}")
async def get_session_approvals(session_id: str):
    """Get all active pre-approvals for a session.

    Args:
        session_id: The session ID

    Returns:
        List of active session approvals
    """
    try:
        manager = _get_approval_manager()
        approvals = manager.get_session_approvals(session_id)

        return {
            "session_id": session_id,
            "approvals": [
                {
                    "operation": a.operation,
                    "pattern": a.pattern,
                    "created_at": a.created_at.isoformat(),
                    "expires_at": a.expires_at.isoformat() if a.expires_at else None,
                }
                for a in approvals
            ],
            "count": len(approvals),
        }

    except Exception as e:
        logger.error(f"Error getting session approvals: {str(e)}")
        raise HTTPException(
            status_code=500, detail=f"Error getting session approvals: {str(e)}"
        )


@router.delete("/api/v1/approvals/session/{session_id}")
async def clear_session_approvals(session_id: str):
    """Clear all pre-approvals for a session.

    Args:
        session_id: The session ID

    Returns:
        Count of cleared approvals
    """
    try:
        manager = _get_approval_manager()
        count = manager.clear_session_approvals(session_id)

        return {
            "success": True,
            "message": f"Cleared {count} approvals for session '{session_id}'",
            "cleared_count": count,
        }

    except Exception as e:
        logger.error(f"Error clearing session approvals: {str(e)}")
        raise HTTPException(
            status_code=500, detail=f"Error clearing session approvals: {str(e)}"
        )


# Routes with path parameters must come AFTER specific paths
@router.get("/api/v1/approvals/{request_id}")
async def get_approval_request(request_id: str):
    """Get details of a specific approval request.

    Args:
        request_id: The approval request ID

    Returns:
        The approval request details
    """
    try:
        manager = _get_approval_manager()
        request = manager.get_request(request_id)

        if request is None:
            raise HTTPException(
                status_code=404, detail=f"Approval request not found: {request_id}"
            )

        return request.to_dict()

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting approval request: {str(e)}")
        raise HTTPException(
            status_code=500, detail=f"Error getting approval request: {str(e)}"
        )


@router.post("/api/v1/approvals/{request_id}/approve")
async def approve_request(
    request_id: str,
    action: ApprovalAction = ApprovalAction(),
):
    """Approve a pending approval request.

    Args:
        request_id: The approval request ID
        action: Approval action with scope (once, session, pattern)

    Returns:
        The resolved approval request
    """
    try:
        from penguin.security.approval import ApprovalScope

        manager = _get_approval_manager()

        # Parse scope
        scope_map = {
            "once": ApprovalScope.ONCE,
            "session": ApprovalScope.SESSION,
            "pattern": ApprovalScope.PATTERN,
        }
        scope = scope_map.get(action.scope.lower())
        if scope is None:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid scope '{action.scope}'. Must be one of: once, session, pattern",
            )

        # Pattern is required for pattern scope
        if scope == ApprovalScope.PATTERN and not action.pattern:
            raise HTTPException(
                status_code=400, detail="Pattern is required when scope is 'pattern'"
            )

        result = manager.approve(request_id, scope=scope, pattern=action.pattern)

        if result is None:
            raise HTTPException(
                status_code=404,
                detail=f"Approval request not found or already resolved: {request_id}",
            )

        return {
            "success": True,
            "message": f"Request approved with scope '{action.scope}'",
            "request": result.to_dict(),
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error approving request: {str(e)}")
        raise HTTPException(
            status_code=500, detail=f"Error approving request: {str(e)}"
        )


@router.post("/api/v1/approvals/{request_id}/deny")
async def deny_request(request_id: str):
    """Deny a pending approval request.

    Args:
        request_id: The approval request ID

    Returns:
        The resolved approval request
    """
    try:
        manager = _get_approval_manager()
        result = manager.deny(request_id)

        if result is None:
            raise HTTPException(
                status_code=404,
                detail=f"Approval request not found or already resolved: {request_id}",
            )

        return {
            "success": True,
            "message": "Request denied",
            "request": result.to_dict(),
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error denying request: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error denying request: {str(e)}")
