"""OpenCode-shaped session and message view adapters."""

from __future__ import annotations

from datetime import datetime
import logging
import os
from pathlib import Path
import subprocess
from typing import Any, Optional

from penguin import __version__

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

_TODO_STATUS_VALUES = {"pending", "in_progress", "completed", "cancelled"}
_TODO_PRIORITY_VALUES = {"high", "medium", "low"}

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


def _resolve_session_model_state(
    core: Any,
    session: Any,
    message: Any | None = None,
) -> dict[str, Optional[str]]:
    """Resolve model/provider/variant from message, then session, then global fallback."""
    session_meta_raw = getattr(session, "metadata", None)
    session_meta = session_meta_raw if isinstance(session_meta_raw, dict) else {}
    message_meta_raw = (
        getattr(message, "metadata", None) if message is not None else None
    )
    message_meta = message_meta_raw if isinstance(message_meta_raw, dict) else {}
    message_model = message_meta.get("model")
    message_model_dict = message_model if isinstance(message_model, dict) else {}

    provider_id = (
        _normalize_non_empty_string(message_meta.get("providerID"))
        or _normalize_non_empty_string(message_meta.get("provider_id"))
        or _normalize_non_empty_string(message_model_dict.get("providerID"))
        or _normalize_non_empty_string(session_meta.get(PROVIDER_ID_KEY))
        or _normalize_non_empty_string(session_meta.get("providerID"))
        or _normalize_non_empty_string(session_meta.get("provider_id"))
        or _normalize_non_empty_string(
            getattr(getattr(core, "model_config", None), "provider", None)
        )
    )
    model_id = (
        _normalize_non_empty_string(message_meta.get("modelID"))
        or _normalize_non_empty_string(message_meta.get("model_id"))
        or _normalize_non_empty_string(message_model_dict.get("modelID"))
        or _normalize_non_empty_string(session_meta.get(MODEL_ID_KEY))
        or _normalize_non_empty_string(session_meta.get("modelID"))
        or _normalize_non_empty_string(session_meta.get("model_id"))
        or _normalize_non_empty_string(
            getattr(getattr(core, "model_config", None), "model", None)
        )
    )
    variant = (
        _normalize_non_empty_string(message_meta.get("variant"))
        or _normalize_non_empty_string(session_meta.get(VARIANT_KEY))
        or _normalize_non_empty_string(session_meta.get("variant"))
    )
    return {
        "providerID": provider_id,
        "modelID": model_id,
        "variant": variant,
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
    if conversation_manager is None:
        return []

    candidates: list[Any] = []
    default_manager = getattr(conversation_manager, "session_manager", None)
    if default_manager is not None:
        candidates.append(default_manager)

    agent_managers = getattr(conversation_manager, "agent_session_managers", {})
    if isinstance(agent_managers, dict):
        candidates.extend(agent_managers.values())

    unique: list[Any] = []
    seen: set[int] = set()
    for manager in candidates:
        manager_id = id(manager)
        if manager_id in seen:
            continue
        seen.add(manager_id)
        unique.append(manager)
    return unique


def _find_session(core: Any, session_id: str) -> tuple[Optional[Any], Optional[Any]]:
    """Find a session and its manager by id."""
    for manager in _iter_session_managers(core):
        cached = getattr(manager, "sessions", {})
        if isinstance(cached, dict) and session_id in cached:
            return cached[session_id][0], manager

        index = getattr(manager, "session_index", {})
        if isinstance(index, dict) and session_id in index:
            session = _load_session_view_only(manager, session_id)
            if session is not None:
                return session, manager
    return None, None


def _load_session_view_only(manager: Any, session_id: str) -> Optional[Any]:
    """Load a session for inspection without changing shared current_session."""
    previous = getattr(manager, "current_session", None)
    try:
        return manager.load_session(session_id)
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


def _build_session_info(core: Any, session: Any, manager: Any) -> dict[str, Any]:
    """Build OpenCode-compatible Session.Info payload."""
    runtime = getattr(core, "runtime_config", None)
    runtime_dir = getattr(runtime, "active_root", None) or getattr(
        runtime, "project_root", None
    )
    metadata = getattr(session, "metadata", {})
    session_dirs = getattr(core, "_opencode_session_directories", {})

    directory = ""
    directory_source = "missing"
    if isinstance(session_dirs, dict):
        mapped = session_dirs.get(str(session.id))
        if isinstance(mapped, str) and mapped.strip():
            directory = mapped
            directory_source = "session_map"
    if isinstance(metadata, dict) and isinstance(metadata.get("directory"), str):
        directory = metadata["directory"]
        directory_source = "metadata"
    if not directory and runtime_dir:
        directory = str(runtime_dir)
        directory_source = "runtime"
    if not directory:
        directory = str(Path.cwd())
        directory_source = "cwd"

    if directory_source in {"runtime", "cwd"}:
        logger.warning(
            "session.view.directory_fallback session=%s source=%s resolved=%s manager=%s",
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

    payload: dict[str, Any] = {
        "id": str(session.id),
        "slug": str(session.id),
        "projectID": "penguin",
        "directory": directory,
        "agent_mode": "build",
        "title": _infer_title(session),
        "version": __version__,
        "time": {
            "created": created,
            "updated": updated,
        },
    }

    model_state = _resolve_session_model_state(core, session)
    if model_state["providerID"]:
        payload["providerID"] = model_state["providerID"]
    if model_state["modelID"]:
        payload["modelID"] = model_state["modelID"]
    if model_state["variant"]:
        payload["variant"] = model_state["variant"]

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
        elif "title" in metadata:
            metadata.pop("title", None)

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
    return diffs


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

    by_file: dict[str, dict[str, Any]] = {}
    for row in selected_rows:
        parts = row.get("parts")
        if not isinstance(parts, list):
            continue
        for part in parts:
            if not isinstance(part, dict) or part.get("type") != "tool":
                continue
            for diff in _diffs_from_tool_part(part):
                file_key = str(diff.get("file") or "unknown")
                by_file[file_key] = diff

    if by_file:
        return list(by_file.values())

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
        index = getattr(manager, "session_index", {})
        if not isinstance(index, dict):
            continue

        for session_id in list(index.keys()):
            session = None
            cached = getattr(manager, "sessions", {})
            if isinstance(cached, dict) and session_id in cached:
                session = cached[session_id][0]
            if session is None:
                session = _load_session_view_only(manager, session_id)
            if session is None:
                continue

            info = _build_session_info(core, session, manager)

            if roots and info.get("parentID"):
                continue
            if normalized_directory:
                session_directory = _normalize_existing_directory(info.get("directory"))
                if not session_directory:
                    continue
                if not _directory_matches(session_directory, normalized_directory):
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


def _default_assistant_info(
    core: Any,
    session_id: str,
    message_id: str,
    *,
    agent_id: str | None = None,
    session: Any | None = None,
) -> dict[str, Any]:
    """Build a minimal valid assistant info envelope."""
    now = int(datetime.now().timestamp() * 1000)
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
            for message_id in order:
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
            "session.view.messages_legacy_fallback session=%s count=%s first=%s last=%s",
            session_id,
            len(rows),
            first_id,
            last_id,
        )

    if limit is not None and limit > 0:
        return rows[-limit:]
    return rows
