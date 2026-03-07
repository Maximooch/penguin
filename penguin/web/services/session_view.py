"""OpenCode-shaped session and message view adapters."""

from __future__ import annotations

from datetime import datetime
import os
from pathlib import Path
import subprocess
from typing import Any, Optional

from penguin import __version__

TRANSCRIPT_KEY = "_opencode_transcript_v1"
USAGE_KEY = "_opencode_usage_v1"
TODO_KEY = "_opencode_todo_v1"
AGENT_MODE_KEY = "_opencode_agent_mode_v1"

_TODO_STATUS_VALUES = {"pending", "in_progress", "completed", "cancelled"}
_TODO_PRIORITY_VALUES = {"high", "medium", "low"}


def _normalize_agent_mode(value: Any) -> Optional[str]:
    if not isinstance(value, str):
        return None
    normalized = value.strip().lower()
    if normalized in {"plan", "build"}:
        return normalized
    return None


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
            try:
                session = manager.load_session(session_id)
            except Exception:
                session = None
            if session is not None:
                return session, manager
    return None, None


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
    if isinstance(session_dirs, dict):
        mapped = session_dirs.get(str(session.id))
        if isinstance(mapped, str) and mapped.strip():
            directory = mapped
    if isinstance(metadata, dict) and isinstance(metadata.get("directory"), str):
        directory = metadata["directory"]
    if not directory and runtime_dir:
        directory = str(runtime_dir)
    if not directory:
        directory = str(Path.cwd())

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


def _git_project_key(
    directory: str,
    cache: dict[str, Optional[str]],
) -> Optional[str]:
    """Return stable git/worktree identity key for directory filtering."""
    cached = cache.get(directory)
    if cached is not None or directory in cache:
        return cached

    top_level = _run_git(["rev-parse", "--show-toplevel"], directory)
    if not top_level:
        cache[directory] = None
        return None

    common_dir = _run_git(["rev-parse", "--git-common-dir"], directory)
    if common_dir:
        common_path = Path(common_dir)
        if not common_path.is_absolute():
            common_path = Path(directory) / common_path
        try:
            common_resolved = common_path.expanduser().resolve()
        except Exception:
            common_resolved = common_path.expanduser()
        key = f"git:{common_resolved}"
        cache[directory] = key
        return key

    try:
        top_resolved = Path(top_level).expanduser().resolve()
    except Exception:
        top_resolved = Path(top_level).expanduser()
    key = f"root:{top_resolved}"
    cache[directory] = key
    return key


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

    return _git_fallback_diffs(_session_directory(core, session))


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
    project_cache: dict[str, Optional[str]] = {}
    requested_project_key = (
        _git_project_key(normalized_directory, project_cache)
        if normalized_directory
        else None
    )

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
                try:
                    session = manager.load_session(session_id)
                except Exception:
                    session = None
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
                    if not requested_project_key:
                        continue
                    session_project_key = _git_project_key(
                        session_directory,
                        project_cache,
                    )
                    if session_project_key != requested_project_key:
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
    core: Any, session_id: str, message_id: str
) -> dict[str, Any]:
    """Build a minimal valid assistant info envelope."""
    now = int(datetime.now().timestamp() * 1000)
    cwd = str(Path.cwd())
    return {
        "id": message_id,
        "sessionID": session_id,
        "role": "assistant",
        "time": {"created": now},
        "parentID": "root",
        "modelID": getattr(
            getattr(core, "model_config", None), "model", "penguin-default"
        ),
        "providerID": getattr(
            getattr(core, "model_config", None), "provider", "penguin"
        ),
        "mode": "chat",
        "agent": "default",
        "path": {"cwd": cwd, "root": cwd},
        "cost": 0,
        "tokens": {
            "input": 0,
            "output": 0,
            "reasoning": 0,
            "cache": {"read": 0, "write": 0},
        },
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

    if role == "user":
        info = {
            "id": message_id,
            "sessionID": session_id,
            "role": "user",
            "time": {"created": created},
            "agent": getattr(message, "agent_id", None) or "default",
            "model": {
                "providerID": getattr(
                    getattr(core, "model_config", None), "provider", "penguin"
                ),
                "modelID": getattr(
                    getattr(core, "model_config", None), "model", "penguin-default"
                ),
            },
        }
    else:
        info = _default_assistant_info(core, session_id, message_id)
        info["time"] = {"created": created, "completed": created}

    part = {
        "id": f"part_{message_id}_0",
        "sessionID": session_id,
        "messageID": message_id,
        "type": "text",
        "text": text,
    }
    return {"info": info, "parts": [part]}


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
                    info = _default_assistant_info(core, session_id, str(message_id))

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

    if not rows:
        rows = legacy_rows
    elif legacy_rows:
        transcript_by_id: dict[str, dict[str, Any]] = {}
        for row in rows:
            info = row.get("info") if isinstance(row, dict) else None
            message_id = info.get("id") if isinstance(info, dict) else None
            if isinstance(message_id, str):
                transcript_by_id[message_id] = row

        merged_rows: list[dict[str, Any]] = []
        merged_ids: set[str] = set()
        for legacy_row in legacy_rows:
            info = legacy_row.get("info") if isinstance(legacy_row, dict) else None
            message_id = info.get("id") if isinstance(info, dict) else None
            if isinstance(message_id, str) and message_id in transcript_by_id:
                merged_rows.append(transcript_by_id[message_id])
                merged_ids.add(message_id)
                continue
            merged_rows.append(legacy_row)
            if isinstance(message_id, str):
                merged_ids.add(message_id)

        for row in rows:
            info = row.get("info") if isinstance(row, dict) else None
            message_id = info.get("id") if isinstance(info, dict) else None
            if isinstance(message_id, str) and message_id in merged_ids:
                continue
            merged_rows.append(row)
            if isinstance(message_id, str):
                merged_ids.add(message_id)

        rows = merged_rows

    if limit is not None and limit > 0:
        return rows[-limit:]
    return rows
