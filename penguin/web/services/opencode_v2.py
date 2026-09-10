"""OpenCode 2 protocol projections backed by Penguin-owned state."""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from pathlib import Path
from typing import Any

from penguin import __version__
from penguin.web.services.opencode_v2_interactions import (
    interaction_event_projection,
)
from penguin.web.services.provider_catalog import canonical_model_id, provider_name
from penguin.web.services.session_view import (
    create_session_info,
    get_session_info,
    get_session_messages,
    list_session_infos,
    list_session_statuses,
    remove_session_info,
    update_session_info,
)
from penguin.web.services.system_status import get_path_info, get_vcs_info

UPSTREAM_V2_COMMIT = "b35c5fc98577b77d8d67d298c6254e0cd138c9d5"
PROJECT_ID = "penguin"

_EMPTY_TOKENS = {
    "input": 0,
    "output": 0,
    "reasoning": 0,
    "cache": {"read": 0, "write": 0},
}
_FINISH_REASONS = {
    "stop",
    "length",
    "tool-calls",
    "content-filter",
    "error",
    "unknown",
}


class OpenCodeV2Error(ValueError):
    """Raised when a V2 request cannot be represented safely by Penguin."""


def health_payload() -> dict[str, Any]:
    """Return the pinned OpenCode 2 health contract."""
    import os

    return {"healthy": True, "version": __version__, "pid": os.getpid()}


def location_payload(
    core: Any,
    *,
    directory: str | None = None,
    workspace_id: str | None = None,
) -> dict[str, Any]:
    """Resolve one OpenCode 2 location without changing Penguin runtime state."""
    if directory:
        try:
            candidate = Path(directory).expanduser().resolve()
        except (OSError, RuntimeError) as exc:
            raise OpenCodeV2Error(f"Invalid directory: {directory}") from exc
        if not candidate.is_dir():
            raise OpenCodeV2Error(f"Directory does not exist: {directory}")
        requested = str(candidate)
    else:
        requested = None

    path = get_path_info(core, directory=requested)
    resolved = str(Path(path["directory"]).resolve())
    canonical = str(Path(path["worktree"]).resolve())
    payload: dict[str, Any] = {
        "directory": resolved,
        "project": {
            "id": PROJECT_ID,
            "directory": canonical,
            "canonical": canonical,
        },
    }
    if workspace_id:
        payload["workspaceID"] = workspace_id
    return payload


def located_payload(
    core: Any,
    data: Any,
    *,
    directory: str | None = None,
    workspace_id: str | None = None,
) -> dict[str, Any]:
    """Wrap data in the OpenCode 2 location response contract."""
    return {
        "location": location_payload(
            core,
            directory=directory,
            workspace_id=workspace_id,
        ),
        "data": data,
    }


def filesystem_list_payload(
    core: Any,
    *,
    directory: str | None = None,
    workspace_id: str | None = None,
    path: str | None = None,
) -> dict[str, Any]:
    """List direct filesystem children without escaping the requested location."""
    location = location_payload(
        core,
        directory=directory,
        workspace_id=workspace_id,
    )
    base = Path(location["directory"]).resolve()
    relative = Path(path or ".")
    if relative.is_absolute():
        raise OpenCodeV2Error("path must be relative")
    try:
        target = (base / relative).resolve()
        target.relative_to(base)
    except (OSError, RuntimeError, ValueError) as exc:
        raise OpenCodeV2Error("path escapes the requested location") from exc
    if not target.is_dir():
        raise OpenCodeV2Error(f"Directory does not exist: {path or '.'}")

    entries: list[dict[str, str]] = []
    try:
        children = target.iterdir()
        for child in children:
            if child.is_symlink():
                continue
            if child.is_dir():
                entry_type = "directory"
            elif child.is_file():
                entry_type = "file"
            else:
                continue
            entry_path = child.relative_to(base).as_posix()
            if entry_type == "directory":
                entry_path += "/"
            entries.append({"path": entry_path, "type": entry_type})
    except OSError as exc:
        raise OpenCodeV2Error(f"Unable to list directory: {path or '.'}") from exc
    entries.sort(key=lambda entry: (entry["type"] != "directory", entry["path"]))
    return {"location": location, "data": entries}


def vcs_payload(
    core: Any,
    *,
    directory: str | None = None,
    workspace_id: str | None = None,
) -> dict[str, Any]:
    """Return the current branch in OpenCode 2's location response shape."""
    location = location_payload(
        core,
        directory=directory,
        workspace_id=workspace_id,
    )
    vcs = get_vcs_info(core, directory=location["directory"], emit_events=False)
    branch: dict[str, str] = {}
    current = _string(vcs.get("branch"))
    if current:
        branch["current"] = current
    return {"location": location, "data": {"branch": branch}}


def project_current_payload(
    core: Any,
    *,
    directory: str | None = None,
    workspace_id: str | None = None,
) -> dict[str, str]:
    """Resolve the current project for a location."""
    location = location_payload(
        core,
        directory=directory,
        workspace_id=workspace_id,
    )
    project = location["project"]
    return {
        "id": str(project["id"]),
        "directory": str(project["directory"]),
        "canonical": str(project["canonical"]),
    }


def projects_payload(core: Any) -> list[dict[str, Any]]:
    """Return Penguin's current project as the minimum V2 project catalog."""
    current = project_current_payload(core)
    canonical = Path(current["canonical"])
    now = int(time.time() * 1000)
    try:
        stat = canonical.stat()
        created = max(int(stat.st_ctime * 1000), 0)
        updated = max(int(stat.st_mtime * 1000), 0)
    except OSError:
        created = now
        updated = now
    vcs = get_vcs_info(core, directory=current["directory"], emit_events=False)
    result: dict[str, Any] = {
        "id": current["id"],
        "canonical": current["canonical"],
        "name": canonical.name or PROJECT_ID,
        "time": {"created": created, "updated": updated},
        "sandboxes": [],
    }
    if vcs.get("vcs") == "git":
        result["vcs"] = "git"
    return [result]


def model_catalog_payload(core: Any) -> list[dict[str, Any]]:
    """Return the active Penguin model as a usable V2 model catalog."""
    model_config = getattr(core, "model_config", None)
    current = core.get_current_model() if hasattr(core, "get_current_model") else None
    current = current if isinstance(current, dict) else {}
    raw_model_id = (
        _string(current.get("model"))
        or _string(getattr(model_config, "model", None))
        or "penguin-default"
    )
    provider_id = _string(current.get("provider")) or _string(
        getattr(model_config, "provider", None)
    )
    if not provider_id:
        provider_id = (
            raw_model_id.split("/", 1)[0] if "/" in raw_model_id else "penguin"
        )
    model_id = canonical_model_id(provider_id, raw_model_id)
    context_limit = _positive_integer(
        current.get("context_window") or getattr(model_config, "context_window", None),
        128_000,
    )
    output_limit = _positive_integer(
        current.get("max_output_tokens")
        or current.get("max_tokens")
        or getattr(model_config, "max_output_tokens", None),
        8_192,
    )
    vision = bool(
        current.get("vision_enabled") or getattr(model_config, "vision_enabled", False)
    )
    inputs = ["text", "image"] if vision else ["text"]
    return [
        {
            "id": model_id,
            "modelID": model_id,
            "providerID": provider_id,
            "name": model_id,
            "capabilities": {
                "tools": True,
                "input": inputs,
                "output": ["text"],
            },
            "variants": [],
            "time": {"released": 0},
            "cost": [],
            "status": "active",
            "enabled": True,
            "limit": {"context": context_limit, "output": output_limit},
        }
    ]


def provider_catalog_payload(core: Any) -> list[dict[str, Any]]:
    """Return providers referenced by the minimum V2 model catalog."""
    providers = {
        str(model["providerID"])
        for model in model_catalog_payload(core)
        if model.get("providerID")
    }
    return [
        {
            "id": provider_id,
            "name": provider_name(provider_id),
            "package": "",
        }
        for provider_id in sorted(providers)
    ]


def agent_catalog_payload(core: Any) -> list[dict[str, Any]]:
    """Expose Penguin's supported build and plan modes as V2 agents."""
    model = model_catalog_payload(core)[0]
    model_ref = {"providerID": model["providerID"], "id": model["id"]}
    return [
        {
            "id": agent_id,
            "name": name,
            "model": model_ref,
            "request": {"settings": {}, "headers": {}, "body": {}},
            "mode": "primary",
            "hidden": False,
            "permissions": [],
        }
        for agent_id, name in (("build", "Build"), ("plan", "Plan"))
    ]


def session_payload(info: dict[str, Any]) -> dict[str, Any]:
    """Project a V1-shaped Penguin session into OpenCode 2 Session.Info."""
    directory = str(Path(str(info.get("directory") or Path.cwd())).resolve())
    payload: dict[str, Any] = {
        "id": str(info["id"]),
        "projectID": str(info.get("projectID") or PROJECT_ID),
        "cost": _non_negative_number(info.get("cost")),
        "tokens": _tokens(info.get("tokens")),
        "time": _session_time(info.get("time")),
        "location": {"directory": directory},
    }

    title = _string(info.get("title"))
    if title:
        payload["title"] = title
    parent_id = _string(info.get("parentID"))
    if parent_id:
        payload["parentID"] = parent_id
    agent = _string(info.get("agent_id")) or _string(info.get("agent_mode"))
    if agent:
        payload["agent"] = agent
    model = _model_ref(info)
    if model:
        payload["model"] = model
    archived = payload["time"].get("archived")
    if archived is None:
        payload["time"].pop("archived", None)

    revert = info.get("revert")
    if isinstance(revert, dict) and _string(revert.get("messageID")):
        projected_revert = {"messageID": str(revert["messageID"])}
        for key in ("partID", "snapshot"):
            value = _string(revert.get(key))
            if value:
                projected_revert[key] = value
        payload["revert"] = projected_revert
    return payload


def list_sessions_payload(
    core: Any,
    *,
    directory: str | None = None,
    search: str | None = None,
    parent_id: str | object | None = ...,  # ``None`` means roots only.
    limit: int = 50,
    order: str = "desc",
) -> dict[str, Any]:
    """Return the first V2 session page using Penguin's existing session view."""
    if limit < 1 or limit > 200:
        raise OpenCodeV2Error("limit must be between 1 and 200")
    if order not in {"asc", "desc"}:
        raise OpenCodeV2Error("order must be asc or desc")

    rows = list_session_infos(
        core,
        directory=directory,
        search=search,
        roots=parent_id is None,
        limit=None,
    )
    if parent_id is not ... and parent_id is not None:
        rows = [row for row in rows if row.get("parentID") == parent_id]
    if order == "asc":
        rows.reverse()
    return {"data": [session_payload(row) for row in rows[:limit]], "cursor": {}}


def get_session_payload(core: Any, session_id: str) -> dict[str, Any] | None:
    """Return one V2 session projection."""
    info = get_session_info(core, session_id)
    return session_payload(info) if isinstance(info, dict) else None


def create_session_payload(
    core: Any,
    payload: dict[str, Any],
    *,
    default_directory: str,
) -> dict[str, Any]:
    """Create a Penguin session from the supported V2 creation fields."""
    if payload.get("id") is not None:
        raise OpenCodeV2Error("Client-selected session ids are not supported")
    location = payload.get("location")
    if location is not None and not isinstance(location, dict):
        raise OpenCodeV2Error("location must be an object")
    location = location if isinstance(location, dict) else {}
    directory = _string(location.get("directory")) or default_directory
    resolved = location_payload(core, directory=directory)["directory"]

    model = payload.get("model")
    if model is not None and not isinstance(model, dict):
        raise OpenCodeV2Error("model must be an object")
    model = model if isinstance(model, dict) else {}
    parent_id = _optional_string_field(payload, "parentID")
    deleting = getattr(core, "_opencode_v2_deleting_sessions", None)
    if parent_id and isinstance(deleting, set) and parent_id in deleting:
        raise OpenCodeV2Error(f"Parent session is being deleted: {parent_id}")
    if parent_id and get_session_payload(core, parent_id) is None:
        raise OpenCodeV2Error(f"Parent session not found: {parent_id}")
    info = create_session_info(
        core,
        title=_optional_string_field(payload, "title"),
        parent_id=parent_id,
        directory=resolved,
        agent_mode=_optional_agent(payload.get("agent")),
        provider_id=_optional_string_field(model, "providerID"),
        model_id=_optional_string_field(model, "id"),
        variant=_optional_string_field(model, "variant"),
    )
    return session_payload(info)


def rename_session(core: Any, session_id: str, title: Any) -> dict[str, Any] | None:
    """Rename one session and return its V2 projection."""
    if not isinstance(title, str) or not title.strip():
        raise OpenCodeV2Error("title must be a non-empty string")
    updated = update_session_info(core, session_id, title=title.strip())
    return session_payload(updated) if isinstance(updated, dict) else None


def switch_session_agent(
    core: Any, session_id: str, agent: Any
) -> dict[str, Any] | None:
    """Persist the V2 agent selection through Penguin's existing mode field."""
    normalized = _optional_agent(agent)
    if normalized is None:
        raise OpenCodeV2Error("agent must be one of: build, plan")
    updated = update_session_info(core, session_id, agent_mode=normalized)
    return session_payload(updated) if isinstance(updated, dict) else None


def switch_session_model(
    core: Any, session_id: str, model: Any
) -> dict[str, Any] | None:
    """Persist the V2 model selection without mutating the shared runtime model."""
    if not isinstance(model, dict):
        raise OpenCodeV2Error("model must be an object")
    provider_id = _required_string_field(model, "providerID")
    model_id = _required_string_field(model, "id")
    updated = update_session_info(
        core,
        session_id,
        provider_id=provider_id,
        model_id=model_id,
        variant=_optional_string_field(model, "variant") or "",
    )
    return session_payload(updated) if isinstance(updated, dict) else None


def deletion_order(core: Any, session_id: str) -> list[dict[str, Any]] | None:
    """Return an existing session subtree in children-first removal order."""
    existing = get_session_payload(core, session_id)
    if existing is None:
        return None

    sessions = {
        projected["id"]: projected
        for info in list_session_infos(core, limit=None)
        if (projected := session_payload(info))
    }
    sessions.setdefault(session_id, existing)
    children: dict[str, list[str]] = {}
    for candidate in sessions.values():
        parent_id = _string(candidate.get("parentID"))
        if parent_id:
            children.setdefault(parent_id, []).append(candidate["id"])

    order: list[str] = []
    visited: set[str] = set()

    def visit(candidate_id: str) -> None:
        if candidate_id in visited:
            return
        visited.add(candidate_id)
        for child_id in children.get(candidate_id, []):
            visit(child_id)
        order.append(candidate_id)

    visit(session_id)
    return [sessions[candidate_id] for candidate_id in order]


def delete_sessions(core: Any, sessions: list[dict[str, Any]]) -> None:
    """Remove a previously resolved children-first session subtree."""
    for candidate in sessions:
        candidate_id = candidate["id"]
        if not remove_session_info(core, candidate_id):
            raise OpenCodeV2Error(f"Failed to delete session {candidate_id}")


def active_sessions_payload(core: Any) -> dict[str, Any]:
    """Return sessions with an active Penguin request in the V2 active shape."""
    active = {
        session_id: {"type": "running"}
        for session_id, status in list_session_statuses(core).items()
        if status.get("type") == "busy"
    }
    reservations = getattr(core, "_opencode_v2_prompt_reservations", None)
    if isinstance(reservations, set):
        for session_id in reservations:
            if isinstance(session_id, str):
                active[session_id] = {"type": "running"}
    tasks = getattr(core, "_opencode_v2_prompt_tasks", None)
    if isinstance(tasks, dict):
        for session_id, task in tasks.items():
            done = getattr(task, "done", None)
            if isinstance(session_id, str) and callable(done) and not done():
                active[session_id] = {"type": "running"}
    deleting = getattr(core, "_opencode_v2_deleting_sessions", None)
    if isinstance(deleting, set):
        for session_id in deleting:
            if isinstance(session_id, str):
                active[session_id] = {"type": "running"}
    return {"data": active}


def messages_payload(
    core: Any,
    session_id: str,
    *,
    limit: int = 50,
    order: str = "desc",
) -> dict[str, Any] | None:
    """Return projected V2 messages for one Penguin session."""
    if limit < 1 or limit > 200:
        raise OpenCodeV2Error("limit must be between 1 and 200")
    if order not in {"asc", "desc"}:
        raise OpenCodeV2Error("order must be asc or desc")
    rows = get_session_messages(core, session_id)
    if rows is None:
        return None
    projected = [item for row in rows if (item := message_payload(row)) is not None]
    if order == "desc":
        projected.reverse()
    return {"data": projected[:limit], "cursor": {}}


def prompt_payload(
    core: Any,
    session_id: str,
    payload: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]] | None:
    """Validate a V2 prompt and build its pending and Penguin request payloads."""
    session = get_session_payload(core, session_id)
    if session is None:
        return None
    text = payload.get("text")
    if not isinstance(text, str):
        raise OpenCodeV2Error("text must be a string")
    for field in ("files", "agents", "skills"):
        value = payload.get(field)
        if value not in (None, []):
            raise OpenCodeV2Error(f"{field} attachments are not supported yet")
    if payload.get("resume") is False:
        raise OpenCodeV2Error("resume=false admission is not supported yet")
    delivery = payload.get("delivery", "steer")
    if delivery not in {"steer", "queue"}:
        raise OpenCodeV2Error("delivery must be steer or queue")
    if delivery == "queue":
        raise OpenCodeV2Error("queue delivery is not supported yet")
    message_id = payload.get("id") or f"msg_{uuid.uuid4().hex}"
    if not isinstance(message_id, str) or not message_id.startswith("msg_"):
        raise OpenCodeV2Error("id must start with msg_")
    metadata = payload.get("metadata")
    if metadata is not None and not isinstance(metadata, dict):
        raise OpenCodeV2Error("metadata must be an object")

    data: dict[str, Any] = {"text": text}
    if metadata:
        data["metadata"] = metadata
    pending = {
        "id": message_id,
        "sessionID": session_id,
        "timeCreated": int(time.time() * 1000),
        "type": "user",
        "data": data,
        "delivery": delivery,
    }
    model = session.get("model")
    model_ref = None
    variant = None
    if isinstance(model, dict):
        provider_id = _string(model.get("providerID"))
        model_id = _string(model.get("id"))
        if provider_id and model_id:
            model_ref = f"{provider_id}/{model_id}"
        variant = _string(model.get("variant"))
    request = {
        "text": text,
        "session_id": session_id,
        "conversation_id": session_id,
        "client_message_id": message_id,
        "client_part_id": f"part_{uuid.uuid4().hex}",
        "context": metadata,
        "streaming": True,
        "agent_id": session.get("agent"),
        "agent_mode": session.get("agent"),
        "directory": session["location"]["directory"],
        "model": model_ref,
        "variant": variant,
    }
    return pending, request


def message_payload(row: dict[str, Any]) -> dict[str, Any] | None:
    """Project one OpenCode 1 WithParts row into an OpenCode 2 message."""
    info = row.get("info")
    if not isinstance(info, dict):
        return None
    message_id = _string(info.get("id"))
    role = _string(info.get("role"))
    if not message_id or role not in {"user", "assistant"}:
        return None
    parts = [part for part in row.get("parts", []) if isinstance(part, dict)]
    created = _message_time(info.get("time"))["created"]

    if role == "user":
        return {
            "id": message_id,
            "type": "user",
            "text": "".join(
                str(part.get("text") or "")
                for part in parts
                if part.get("type") == "text"
            ),
            "time": {"created": created},
        }

    model = _model_ref(info) or {"providerID": "penguin", "id": "penguin-default"}
    result: dict[str, Any] = {
        "id": message_id,
        "type": "assistant",
        "agent": _string(info.get("agent")) or "build",
        "model": model,
        "content": [content for part in parts if (content := _content(part))],
        "cost": _non_negative_number(info.get("cost")),
        "tokens": _tokens(info.get("tokens")),
        "time": _message_time(info.get("time")),
    }
    finish = _string(info.get("finish"))
    if finish in _FINISH_REASONS:
        result["finish"] = finish
    error = info.get("error")
    if isinstance(error, dict):
        result["error"] = _error(error)
    if result["time"].get("completed") is None:
        result["time"].pop("completed", None)
    return result


def event_payload(
    data: dict[str, Any],
    *,
    suffix: str = "event",
) -> dict[str, Any] | None:
    """Project non-stream V1 lifecycle events consumed during V2 hydration."""
    event_type = _string(data.get("type"))
    properties = data.get("properties")
    if not event_type or not isinstance(properties, dict):
        return None
    runtime = data.get("runtime_event")
    runtime = runtime if isinstance(runtime, dict) else {}
    created = _integer(
        data.get("time"), _integer(runtime.get("time"), int(time.time() * 1000))
    )
    session_id = _event_session(properties)
    directory = _event_directory(properties)

    projected_type = event_type
    projected_data: dict[str, Any]
    durable_version: int | None = None
    interaction = interaction_event_projection(event_type, properties)
    if interaction is not None:
        projected_type, projected_data = interaction
    elif event_type == "session.created":
        info = properties.get("info")
        if not isinstance(info, dict) or not session_id:
            return None
        session = session_payload(info)
        projected_data = {
            "sessionID": session_id,
            "projectID": session["projectID"],
            "location": session["location"],
            "slug": session_id,
            "title": session.get("title"),
            "agent": session.get("agent"),
            "model": session.get("model"),
            "version": __version__,
        }
        projected_data = {
            key: value for key, value in projected_data.items() if value is not None
        }
        durable_version = 1
    elif event_type == "session.updated":
        info = properties.get("info")
        if not isinstance(info, dict) or not session_id:
            return None
        projected_type = "session.renamed"
        projected_data = {
            "sessionID": session_id,
            "title": str(info.get("title") or ""),
        }
        durable_version = 1
    elif event_type == "session.agent.selected":
        agent = _string(properties.get("agent"))
        if not session_id or not agent:
            return None
        projected_data = {"sessionID": session_id, "agent": agent}
        previous = _string(properties.get("previous"))
        if previous:
            projected_data["previous"] = previous
        durable_version = 1
    elif event_type == "session.model.selected":
        model = _model_ref({"model": properties.get("model")})
        if not session_id or model is None:
            return None
        projected_data = {"sessionID": session_id, "model": model}
        previous = _model_ref({"model": properties.get("previous")})
        if previous:
            projected_data["previous"] = previous
        durable_version = 1
    elif event_type == "session.deleted":
        if not session_id:
            return None
        projected_data = {"sessionID": session_id}
        durable_version = 2
    elif event_type == "vcs.branch.updated":
        projected_data = {"branch": _string(properties.get("branch")) or ""}
    else:
        return None

    source_id = _string(data.get("id")) or _string(runtime.get("id")) or event_type
    result: dict[str, Any] = {
        "id": _event_id(source_id, suffix),
        "created": created,
        "type": projected_type,
        "data": projected_data,
    }
    if directory:
        result["location"] = {"directory": directory}
    if durable_version is not None and session_id:
        sequence = _integer(runtime.get("sequence"), _integer(data.get("order"), 1))
        result["durable"] = {
            "aggregateID": session_id,
            "seq": max(sequence, 0),
            "version": durable_version,
        }
    return result


def _content(part: dict[str, Any]) -> dict[str, Any] | None:
    part_type = _string(part.get("type"))
    if part_type == "text":
        return {"type": "text", "text": str(part.get("text") or "")}
    if part_type == "reasoning":
        result: dict[str, Any] = {
            "type": "reasoning",
            "text": str(part.get("text") or ""),
        }
        time_data = part.get("time")
        if isinstance(time_data, dict):
            result["time"] = _message_time(time_data)
        return result
    if part_type != "tool":
        return None

    state = part.get("state")
    state = state if isinstance(state, dict) else {}
    status = _string(state.get("status")) or "running"
    input_data = state.get("input") if isinstance(state.get("input"), dict) else {}
    metadata = state.get("metadata") if isinstance(state.get("metadata"), dict) else {}
    if status == "completed":
        output = state.get("output")
        rendered = (
            output if isinstance(output, str) else json.dumps(output, default=str)
        )
        projected_state: dict[str, Any] = {
            "status": "completed",
            "input": input_data,
            "content": [{"type": "text", "text": rendered or "(no output)"}],
        }
        if metadata:
            projected_state["metadata"] = metadata
    elif status == "error":
        projected_state = {
            "status": "error",
            "input": input_data,
            "error": {
                "type": "tool.error",
                "message": str(state.get("error") or "Tool execution failed"),
            },
        }
        if metadata:
            projected_state["metadata"] = metadata
    else:
        projected_state = {
            "status": "running",
            "input": input_data,
            "metadata": metadata,
        }

    time_data = state.get("time") if isinstance(state.get("time"), dict) else {}
    created = _integer(time_data.get("start"), int(time.time() * 1000))
    result = {
        "type": "tool",
        "id": _string(part.get("callID")) or _string(part.get("id")) or "tool",
        "name": _string(part.get("tool")) or "tool",
        "state": projected_state,
        "time": {"created": created},
    }
    completed = time_data.get("end")
    if isinstance(completed, (int, float)):
        result["time"]["completed"] = int(completed)
    return result


def _model_ref(value: dict[str, Any]) -> dict[str, Any] | None:
    provider_id = _string(value.get("providerID"))
    model_id = _string(value.get("modelID"))
    nested = value.get("model")
    if isinstance(nested, dict):
        provider_id = provider_id or _string(nested.get("providerID"))
        model_id = (
            model_id or _string(nested.get("id")) or _string(nested.get("modelID"))
        )
    if not provider_id or not model_id:
        return None
    result = {"providerID": provider_id, "id": model_id}
    variant = _string(value.get("variant")) or (
        _string(nested.get("variant")) if isinstance(nested, dict) else None
    )
    if variant:
        result["variant"] = variant
    return result


def _tokens(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {**_EMPTY_TOKENS, "cache": dict(_EMPTY_TOKENS["cache"])}
    cache = value.get("cache") if isinstance(value.get("cache"), dict) else {}
    return {
        "input": _non_negative_number(value.get("input")),
        "output": _non_negative_number(value.get("output")),
        "reasoning": _non_negative_number(value.get("reasoning")),
        "cache": {
            "read": _non_negative_number(cache.get("read")),
            "write": _non_negative_number(cache.get("write")),
        },
    }


def _session_time(value: Any) -> dict[str, int]:
    value = value if isinstance(value, dict) else {}
    created = _integer(value.get("created"), int(time.time() * 1000))
    result = {
        "created": created,
        "updated": _integer(value.get("updated"), created),
    }
    archived = _optional_integer(value.get("archived"))
    if archived is not None:
        result["archived"] = archived
    return result


def _message_time(value: Any) -> dict[str, int]:
    value = value if isinstance(value, dict) else {}
    result = {
        "created": _integer(value.get("created"), int(time.time() * 1000)),
    }
    completed = _optional_integer(value.get("completed"))
    if completed is not None:
        result["completed"] = completed
    return result


def _error(value: dict[str, Any]) -> dict[str, Any]:
    data = value.get("data") if isinstance(value.get("data"), dict) else {}
    result: dict[str, Any] = {
        "type": _string(value.get("type"))
        or _string(value.get("name"))
        or "provider.error",
        "message": _string(value.get("message"))
        or _string(data.get("message"))
        or "Provider request failed",
    }
    status = value.get("status") or data.get("statusCode")
    if isinstance(status, int):
        result["status"] = status
    return result


def _event_session(properties: dict[str, Any]) -> str | None:
    direct = _string(properties.get("sessionID")) or _string(
        properties.get("session_id")
    )
    info = properties.get("info")
    return direct or (_string(info.get("id")) if isinstance(info, dict) else None)


def _event_directory(properties: dict[str, Any]) -> str | None:
    direct = _string(properties.get("directory"))
    info = properties.get("info")
    return direct or (
        _string(info.get("directory")) if isinstance(info, dict) else None
    )


def _event_id(source: str, suffix: str) -> str:
    digest = hashlib.sha256(f"{source}:{suffix}".encode()).hexdigest()[:24]
    return f"evt_{digest}"


def _string(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _optional_string_field(payload: dict[str, Any], key: str) -> str | None:
    value = payload.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise OpenCodeV2Error(f"{key} must be a string")
    return value.strip() or None


def _required_string_field(payload: dict[str, Any], key: str) -> str:
    value = _optional_string_field(payload, key)
    if value is None:
        raise OpenCodeV2Error(f"{key} must be a non-empty string")
    return value


def _optional_agent(value: Any) -> str | None:
    if value is None:
        return None
    agent = _string(value)
    if agent not in {"build", "plan"}:
        raise OpenCodeV2Error("agent must be one of: build, plan")
    return agent


def _integer(value: Any, default: int) -> int:
    if isinstance(value, bool):
        return default
    if isinstance(value, (int, float)):
        return int(value)
    return default


def _positive_integer(value: Any, default: int) -> int:
    parsed = _integer(value, default)
    return parsed if parsed > 0 else default


def _optional_integer(value: Any) -> int | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return _integer(value, 0)
    return None


def _non_negative_number(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0
    return max(float(value), 0)


__all__ = [
    "PROJECT_ID",
    "UPSTREAM_V2_COMMIT",
    "OpenCodeV2Error",
    "active_sessions_payload",
    "agent_catalog_payload",
    "create_session_payload",
    "delete_sessions",
    "deletion_order",
    "event_payload",
    "filesystem_list_payload",
    "get_session_payload",
    "health_payload",
    "list_sessions_payload",
    "located_payload",
    "location_payload",
    "message_payload",
    "messages_payload",
    "model_catalog_payload",
    "project_current_payload",
    "projects_payload",
    "prompt_payload",
    "provider_catalog_payload",
    "rename_session",
    "session_payload",
    "switch_session_agent",
    "switch_session_model",
    "vcs_payload",
]
