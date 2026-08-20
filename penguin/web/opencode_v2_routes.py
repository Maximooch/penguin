"""Thin OpenCode 2 HTTP compatibility routes."""

# FastAPI evaluates endpoint annotations at runtime on Python 3.9.
# ruff: noqa: UP045

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from typing import Any, AsyncIterator, Optional, cast

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse

from penguin.core import PenguinCore  # noqa: TC001
from penguin.web.services.opencode_events import emit_opencode_event
from penguin.web.services.opencode_v2 import (
    OpenCodeV2Error,
    active_sessions_payload,
    agent_catalog_payload,
    create_session_payload,
    delete_sessions,
    deletion_order,
    event_payload,
    filesystem_list_payload,
    get_session_payload,
    health_payload,
    list_sessions_payload,
    located_payload,
    location_payload,
    messages_payload,
    model_catalog_payload,
    project_current_payload,
    projects_payload,
    prompt_payload,
    provider_catalog_payload,
    rename_session,
    switch_session_agent,
    switch_session_model,
    vcs_payload,
)
from penguin.web.services.opencode_v2_events import (
    OpenCodeV2EventProjector,
    server_connected_event,
)
from penguin.web.services.opencode_v2_interactions import (
    InteractionNotFoundError,
    InteractionPayloadError,
    InteractionSettledError,
    cancel_form_request,
    get_form_payload,
    get_permission_payload,
    list_form_payloads,
    list_permission_payloads,
    reply_form_request,
    reply_permission_request,
)
from penguin.web.services.session_events import (
    emit_session_created_event,
    emit_session_deleted_event,
    emit_session_updated_event,
)
from penguin.web.services.session_view import get_session_info

logger = logging.getLogger(__name__)
router = APIRouter(tags=["OpenCode 2 compatibility"])
router.core = None  # type: ignore[attr-defined]

_EVENT_QUEUE_SIZE = 4096
_HEARTBEAT_SECONDS = 15.0
_NATIVE_LIFECYCLE_SOURCE_TYPES = frozenset(
    {
        "message.part.updated",
        "message.updated",
        "session.created",
        "session.execution.interrupted",
        "session.status",
    }
)


class OpenCodeV2HTTPError(Exception):
    """HTTP failure with an exact OpenCode 2 wire payload."""

    def __init__(self, status_code: int, payload: dict[str, Any]) -> None:
        message = payload.get("message") or payload.get("_tag") or status_code
        super().__init__(str(message))
        self.status_code = status_code
        self.payload = payload


async def handle_http_error(
    _request: Request, exc: OpenCodeV2HTTPError
) -> JSONResponse:
    """Render a generated-client-decodable OpenCode 2 error."""
    return JSONResponse(status_code=exc.status_code, content=exc.payload)


def get_core() -> PenguinCore:
    """Return the application-owned Penguin core."""
    core = getattr(router, "core", None)
    if core is None:
        raise RuntimeError("OpenCode 2 router core is not initialized")
    return cast("PenguinCore", core)


def _bad_request(exc: OpenCodeV2Error) -> OpenCodeV2HTTPError:
    return OpenCodeV2HTTPError(
        400,
        {"_tag": "InvalidRequestError", "message": str(exc)},
    )


def _session_busy(session_id: str) -> OpenCodeV2HTTPError:
    return OpenCodeV2HTTPError(
        409,
        {
            "_tag": "SessionBusyError",
            "sessionID": session_id,
            "message": f"Session is already running: {session_id}",
        },
    )


def _not_found(session_id: str) -> OpenCodeV2HTTPError:
    return OpenCodeV2HTTPError(
        404,
        {
            "_tag": "SessionNotFoundError",
            "message": f"Session not found: {session_id}",
            "sessionID": session_id,
        },
    )


def _permission_not_found(request_id: str) -> OpenCodeV2HTTPError:
    return OpenCodeV2HTTPError(
        404,
        {
            "_tag": "PermissionNotFoundError",
            "message": f"Permission request not found: {request_id}",
            "requestID": request_id,
        },
    )


def _form_not_found(form_id: str) -> OpenCodeV2HTTPError:
    return OpenCodeV2HTTPError(
        404,
        {
            "_tag": "FormNotFoundError",
            "message": f"Form not found: {form_id}",
            "id": form_id,
        },
    )


def _form_settled(form_id: str) -> OpenCodeV2HTTPError:
    return OpenCodeV2HTTPError(
        409,
        {
            "_tag": "FormAlreadySettledError",
            "message": f"Form already settled: {form_id}",
            "id": form_id,
        },
    )


def _form_invalid(form_id: str, message: str) -> OpenCodeV2HTTPError:
    return OpenCodeV2HTTPError(
        400,
        {
            "_tag": "FormInvalidAnswerError",
            "message": message,
            "id": form_id,
        },
    )


def _located_response(
    core: PenguinCore,
    data: Any,
    *,
    directory: Optional[str],
    workspace: Optional[str],
) -> dict[str, Any]:
    try:
        return located_payload(
            core,
            data,
            directory=directory,
            workspace_id=workspace,
        )
    except OpenCodeV2Error as exc:
        raise _bad_request(exc) from exc


@router.get("/api/health")
async def health() -> dict[str, Any]:
    """Return the OpenCode 2 process health shape."""
    return health_payload()


@router.get("/api/location")
async def location(
    core: PenguinCore = Depends(get_core),
    directory: Optional[str] = Query(None, alias="location[directory]"),
    workspace: Optional[str] = Query(None, alias="location[workspace]"),
) -> dict[str, Any]:
    """Resolve a deep-object V2 location query."""
    try:
        return location_payload(core, directory=directory, workspace_id=workspace)
    except OpenCodeV2Error as exc:
        raise _bad_request(exc) from exc


@router.get("/api/fs/list")
async def filesystem_list(
    core: PenguinCore = Depends(get_core),
    directory: Optional[str] = Query(None, alias="location[directory]"),
    workspace: Optional[str] = Query(None, alias="location[workspace]"),
    path: Optional[str] = Query(None),
) -> dict[str, Any]:
    """List direct children in the requested location."""
    try:
        return filesystem_list_payload(
            core,
            directory=directory,
            workspace_id=workspace,
            path=path,
        )
    except OpenCodeV2Error as exc:
        raise _bad_request(exc) from exc


@router.get("/api/vcs")
async def vcs_get(
    core: PenguinCore = Depends(get_core),
    directory: Optional[str] = Query(None, alias="location[directory]"),
    workspace: Optional[str] = Query(None, alias="location[workspace]"),
) -> dict[str, Any]:
    """Return the current VCS branch."""
    try:
        return vcs_payload(
            core,
            directory=directory,
            workspace_id=workspace,
        )
    except OpenCodeV2Error as exc:
        raise _bad_request(exc) from exc


@router.get("/api/project/current")
async def project_current(
    core: PenguinCore = Depends(get_core),
    directory: Optional[str] = Query(None, alias="location[directory]"),
    workspace: Optional[str] = Query(None, alias="location[workspace]"),
) -> dict[str, str]:
    """Resolve the project for a requested location."""
    try:
        return project_current_payload(
            core,
            directory=directory,
            workspace_id=workspace,
        )
    except OpenCodeV2Error as exc:
        raise _bad_request(exc) from exc


@router.get("/api/project")
async def project_list(
    core: PenguinCore = Depends(get_core),
) -> list[dict[str, Any]]:
    """List the current Penguin project."""
    return projects_payload(core)


@router.get("/api/agent")
async def agent_list(
    core: PenguinCore = Depends(get_core),
    directory: Optional[str] = Query(None, alias="location[directory]"),
    workspace: Optional[str] = Query(None, alias="location[workspace]"),
) -> dict[str, Any]:
    """List usable Penguin agents in V2 shape."""
    return _located_response(
        core,
        agent_catalog_payload(core),
        directory=directory,
        workspace=workspace,
    )


@router.get("/api/model")
async def model_list(
    core: PenguinCore = Depends(get_core),
    directory: Optional[str] = Query(None, alias="location[directory]"),
    workspace: Optional[str] = Query(None, alias="location[workspace]"),
) -> dict[str, Any]:
    """List the active Penguin model in V2 shape."""
    return _located_response(
        core,
        model_catalog_payload(core),
        directory=directory,
        workspace=workspace,
    )


@router.get("/api/provider")
async def provider_list(
    core: PenguinCore = Depends(get_core),
    directory: Optional[str] = Query(None, alias="location[directory]"),
    workspace: Optional[str] = Query(None, alias="location[workspace]"),
) -> dict[str, Any]:
    """List providers referenced by Penguin's model catalog."""
    return _located_response(
        core,
        provider_catalog_payload(core),
        directory=directory,
        workspace=workspace,
    )


@router.get("/api/command")
@router.get("/api/integration")
@router.get("/api/mcp")
@router.get("/api/reference")
@router.get("/api/skill")
@router.get("/api/shell")
async def empty_location_catalog(
    core: PenguinCore = Depends(get_core),
    directory: Optional[str] = Query(None, alias="location[directory]"),
    workspace: Optional[str] = Query(None, alias="location[workspace]"),
) -> dict[str, Any]:
    """Return an exact empty V2 location catalog for unsupported features."""
    return _located_response(
        core,
        [],
        directory=directory,
        workspace=workspace,
    )


@router.get("/api/permission/request")
async def permission_requests(
    core: PenguinCore = Depends(get_core),
    directory: Optional[str] = Query(None, alias="location[directory]"),
    workspace: Optional[str] = Query(None, alias="location[workspace]"),
) -> dict[str, Any]:
    """List pending Penguin approvals for the requested location."""
    return _located_response(
        core,
        list_permission_payloads(),
        directory=directory,
        workspace=workspace,
    )


@router.get("/api/form/request")
async def form_requests(
    core: PenguinCore = Depends(get_core),
    directory: Optional[str] = Query(None, alias="location[directory]"),
    workspace: Optional[str] = Query(None, alias="location[workspace]"),
) -> dict[str, Any]:
    """List pending Penguin questions for the requested location."""
    return _located_response(
        core,
        list_form_payloads(),
        directory=directory,
        workspace=workspace,
    )


@router.get("/api/mcp/resource")
async def mcp_resource_catalog(
    core: PenguinCore = Depends(get_core),
    directory: Optional[str] = Query(None, alias="location[directory]"),
    workspace: Optional[str] = Query(None, alias="location[workspace]"),
) -> dict[str, Any]:
    """Return the exact empty MCP resource catalog shape."""
    return _located_response(
        core,
        {"resources": [], "templates": []},
        directory=directory,
        workspace=workspace,
    )


@router.get("/api/experimental/migration/v1")
async def migration_v1_status() -> dict[str, str]:
    """Report that Penguin does not require OpenCode's V1 history migration."""
    return {"status": "completed"}


@router.get("/api/session/active")
async def session_active(core: PenguinCore = Depends(get_core)) -> dict[str, Any]:
    """List sessions currently executing in Penguin."""
    return active_sessions_payload(core)


@router.get("/api/session")
async def session_list(
    request: Request,
    core: PenguinCore = Depends(get_core),
    directory: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    limit: int = Query(50),
    order: str = Query("desc"),
    cursor: Optional[str] = Query(None),
) -> dict[str, Any]:
    """List the first page of sessions in V2 shape."""
    if cursor:
        raise _bad_request(OpenCodeV2Error("Pagination cursors are not supported yet"))
    parent: Optional[object] = ...
    if "parentID" in request.query_params:
        raw_parent = request.query_params.get("parentID")
        parent = None if raw_parent == "null" else raw_parent
    try:
        return list_sessions_payload(
            core,
            directory=directory,
            search=search,
            parent_id=parent,
            limit=limit,
            order=order,
        )
    except OpenCodeV2Error as exc:
        raise _bad_request(exc) from exc


@router.post("/api/session")
async def session_create(
    payload: Optional[dict[str, Any]] = None,
    core: PenguinCore = Depends(get_core),
) -> dict[str, Any]:
    """Create a Penguin-owned session through the V2 contract."""
    request_payload = payload or {}
    parent_id = request_payload.get("parentID")
    if isinstance(parent_id, str) and parent_id in _deleting_sessions(core):
        raise _session_busy(parent_id)
    try:
        default = location_payload(core)["directory"]
        projected = create_session_payload(
            core,
            request_payload,
            default_directory=default,
        )
    except OpenCodeV2Error as exc:
        raise _bad_request(exc) from exc
    info = get_session_info(core, projected["id"])
    if isinstance(info, dict):
        await emit_session_created_event(core, info)
    return {"data": projected}


@router.get("/api/session/{session_id}")
async def session_get(
    session_id: str,
    core: PenguinCore = Depends(get_core),
) -> dict[str, Any]:
    """Get one projected session."""
    session = get_session_payload(core, session_id)
    if session is None:
        raise _not_found(session_id)
    return {"data": session}


@router.delete("/api/session/{session_id}")
async def session_remove(
    session_id: str,
    core: PenguinCore = Depends(get_core),
) -> Response:
    """Delete one Penguin session and all of its descendants."""
    deleting = _deleting_sessions(core)
    if session_id in deleting:
        raise _session_busy(session_id)
    try:
        removed_sessions = deletion_order(core, session_id)
    except OpenCodeV2Error as exc:
        raise _bad_request(exc) from exc
    if removed_sessions is None:
        raise _not_found(session_id)
    removed_ids = {removed["id"] for removed in removed_sessions}
    if removed_ids & deleting:
        raise _session_busy(session_id)
    active = _active_session_ids(core)
    deleting.update(removed_ids)
    try:
        for removed in removed_sessions:
            removed_id = removed["id"]
            if removed_id in active:
                await _interrupt_active_session(core, removed_id)
            await _await_session_idle(core, removed_id)
        try:
            delete_sessions(core, removed_sessions)
        except OpenCodeV2Error as exc:
            raise _bad_request(exc) from exc
        for removed in removed_sessions:
            await emit_session_deleted_event(core, _v1_session(removed))
    finally:
        deleting.difference_update(removed_ids)
    return Response(status_code=204)


@router.post("/api/session/{session_id}/rename")
async def session_rename(
    session_id: str,
    payload: dict[str, Any],
    core: PenguinCore = Depends(get_core),
) -> Response:
    """Rename one session."""
    try:
        updated = rename_session(core, session_id, payload.get("title"))
    except OpenCodeV2Error as exc:
        raise _bad_request(exc) from exc
    await _emit_updated_or_404(core, session_id, updated)
    return Response(status_code=204)


@router.post("/api/session/{session_id}/agent")
async def session_switch_agent(
    session_id: str,
    payload: dict[str, Any],
    core: PenguinCore = Depends(get_core),
) -> Response:
    """Persist a session-scoped Penguin agent mode."""
    try:
        updated = switch_session_agent(core, session_id, payload.get("agent"))
    except OpenCodeV2Error as exc:
        raise _bad_request(exc) from exc
    if updated is None:
        raise _not_found(session_id)
    await emit_opencode_event(
        core,
        "session.agent.selected",
        {
            "sessionID": session_id,
            "agent": updated["agent"],
            "directory": updated["location"]["directory"],
        },
    )
    return Response(status_code=204)


@router.post("/api/session/{session_id}/model")
async def session_switch_model(
    session_id: str,
    payload: dict[str, Any],
    core: PenguinCore = Depends(get_core),
) -> Response:
    """Persist a session-scoped model selection."""
    try:
        updated = switch_session_model(core, session_id, payload.get("model"))
    except OpenCodeV2Error as exc:
        raise _bad_request(exc) from exc
    if updated is None:
        raise _not_found(session_id)
    await emit_opencode_event(
        core,
        "session.model.selected",
        {
            "sessionID": session_id,
            "model": updated["model"],
            "directory": updated["location"]["directory"],
        },
    )
    return Response(status_code=204)


@router.get("/api/session/{session_id}/message")
async def session_messages(
    session_id: str,
    core: PenguinCore = Depends(get_core),
    limit: int = Query(50),
    order: str = Query("desc"),
    cursor: Optional[str] = Query(None),
) -> dict[str, Any]:
    """List projected V2 session messages."""
    if cursor:
        raise _bad_request(OpenCodeV2Error("Pagination cursors are not supported yet"))
    try:
        result = messages_payload(core, session_id, limit=limit, order=order)
    except OpenCodeV2Error as exc:
        raise _bad_request(exc) from exc
    if result is None:
        raise _not_found(session_id)
    return result


@router.get("/api/session/{session_id}/pending")
async def session_pending(
    session_id: str,
    core: PenguinCore = Depends(get_core),
) -> dict[str, Any]:
    """Return pending work; Penguin promotes admitted prompts immediately."""
    if get_session_payload(core, session_id) is None:
        raise _not_found(session_id)
    return {"data": []}


@router.get("/api/session/{session_id}/permission")
async def session_permissions(
    session_id: str,
    core: PenguinCore = Depends(get_core),
) -> dict[str, Any]:
    """List pending Penguin approvals owned by a session."""
    if get_session_payload(core, session_id) is None:
        raise _not_found(session_id)
    return {"data": list_permission_payloads(session_id)}


@router.get("/api/session/{session_id}/permission/{request_id}")
async def session_permission_get(
    session_id: str,
    request_id: str,
    core: PenguinCore = Depends(get_core),
) -> dict[str, Any]:
    """Get one pending Penguin approval owned by a session."""
    if get_session_payload(core, session_id) is None:
        raise _not_found(session_id)
    permission = get_permission_payload(session_id, request_id)
    if permission is None:
        raise _permission_not_found(request_id)
    return {"data": permission}


@router.post("/api/session/{session_id}/permission/{request_id}/reply")
async def session_permission_reply(
    session_id: str,
    request_id: str,
    payload: dict[str, Any],
    core: PenguinCore = Depends(get_core),
) -> Response:
    """Reply to one pending Penguin approval."""
    if get_session_payload(core, session_id) is None:
        raise _not_found(session_id)
    try:
        reply_permission_request(session_id, request_id, payload)
    except InteractionPayloadError as exc:
        raise _bad_request(OpenCodeV2Error(str(exc))) from exc
    except InteractionNotFoundError as exc:
        raise _permission_not_found(request_id) from exc
    return Response(status_code=204)


@router.get("/api/session/{session_id}/form")
async def session_forms(
    session_id: str,
    core: PenguinCore = Depends(get_core),
) -> dict[str, Any]:
    """List pending Penguin questions projected as V2 forms."""
    if get_session_payload(core, session_id) is None:
        raise _not_found(session_id)
    return {"data": list_form_payloads(session_id)}


@router.get("/api/session/{session_id}/form/{form_id}")
async def session_form_get(
    session_id: str,
    form_id: str,
    core: PenguinCore = Depends(get_core),
) -> dict[str, Any]:
    """Get one Penguin question projected as a V2 form."""
    if get_session_payload(core, session_id) is None:
        raise _not_found(session_id)
    form = get_form_payload(session_id, form_id)
    if form is None:
        raise _form_not_found(form_id)
    return {"data": form}


@router.post("/api/session/{session_id}/form/{form_id}/reply")
async def session_form_reply(
    session_id: str,
    form_id: str,
    payload: dict[str, Any],
    core: PenguinCore = Depends(get_core),
) -> Response:
    """Translate a V2 form answer into ordered Penguin question answers."""
    if get_session_payload(core, session_id) is None:
        raise _not_found(session_id)
    try:
        reply_form_request(session_id, form_id, payload)
    except InteractionNotFoundError as exc:
        raise _form_not_found(form_id) from exc
    except InteractionSettledError as exc:
        raise _form_settled(form_id) from exc
    except InteractionPayloadError as exc:
        raise _form_invalid(form_id, str(exc)) from exc
    return Response(status_code=204)


@router.post("/api/session/{session_id}/form/{form_id}/cancel")
async def session_form_cancel(
    session_id: str,
    form_id: str,
    core: PenguinCore = Depends(get_core),
) -> Response:
    """Cancel one pending Penguin question through the V2 form contract."""
    if get_session_payload(core, session_id) is None:
        raise _not_found(session_id)
    try:
        cancel_form_request(session_id, form_id)
    except InteractionNotFoundError as exc:
        raise _form_not_found(form_id) from exc
    except InteractionSettledError as exc:
        raise _form_settled(form_id) from exc
    return Response(status_code=204)


@router.post("/api/session/{session_id}/prompt")
async def session_prompt(
    session_id: str,
    payload: dict[str, Any],
    core: PenguinCore = Depends(get_core),
) -> dict[str, Any]:
    """Admit a text prompt and run it through Penguin's existing chat path."""
    try:
        admitted = prompt_payload(core, session_id, payload)
    except OpenCodeV2Error as exc:
        raise _bad_request(exc) from exc
    if admitted is None:
        raise _not_found(session_id)
    reservations = _prompt_reservations(core)
    if session_id in _active_session_ids(core):
        raise _session_busy(session_id)
    reservations.add(session_id)
    pending, request_payload = admitted
    task = asyncio.create_task(_run_prompt(core, request_payload))
    _prompt_tasks(core)[session_id] = task
    return {"data": pending}


@router.post("/api/session/{session_id}/interrupt")
async def session_interrupt(
    session_id: str,
    core: PenguinCore = Depends(get_core),
) -> Response:
    """Interrupt a running Penguin session; idle interruption is a no-op."""
    if get_session_payload(core, session_id) is None:
        raise _not_found(session_id)
    if session_id not in _active_session_ids(core):
        return Response(status_code=204)
    await _interrupt_active_session(core, session_id)
    return Response(status_code=204)


@router.get("/api/event")
async def event_stream(core: PenguinCore = Depends(get_core)) -> StreamingResponse:
    """Expose a volatile V2 event projection over Penguin's existing EventBus."""
    return StreamingResponse(
        _events(core),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
            "X-Content-Type-Options": "nosniff",
        },
    )


async def _emit_updated_or_404(
    core: PenguinCore,
    session_id: str,
    updated: Optional[dict[str, Any]],
) -> None:
    if updated is None:
        raise _not_found(session_id)
    info = get_session_info(core, session_id)
    if isinstance(info, dict):
        await emit_session_updated_event(core, info)


async def _run_prompt(core: PenguinCore, payload: dict[str, Any]) -> None:
    from penguin.web.routes import MessageRequest, handle_chat_message

    try:
        await handle_chat_message(
            MessageRequest(**payload), core=core, http_request=None
        )
    except Exception as exc:
        logger.exception("OpenCode 2 background prompt failed")
        await _emit_prompt_failure(core, payload, exc)
    finally:
        session_id = payload.get("session_id")
        if isinstance(session_id, str):
            _prompt_reservations(core).discard(session_id)
            current = asyncio.current_task()
            if _prompt_tasks(core).get(session_id) is current:
                _prompt_tasks(core).pop(session_id, None)


async def _emit_prompt_failure(
    core: PenguinCore,
    payload: dict[str, Any],
    exc: Exception,
) -> None:
    """Terminate a V2 run when the shared chat path fails before streaming."""
    session_id = payload.get("session_id")
    if not isinstance(session_id, str) or not session_id:
        return

    detail = getattr(exc, "detail", None)
    message = detail if isinstance(detail, str) and detail else str(exc)
    if not message:
        message = "Penguin prompt failed before execution"
    error_data: dict[str, Any] = {"message": message}
    status_code = getattr(exc, "status_code", None)
    if isinstance(status_code, int) and not isinstance(status_code, bool):
        error_data["statusCode"] = status_code

    model = payload.get("model")
    provider_id = "penguin"
    model_id = "penguin-default"
    if isinstance(model, str) and "/" in model:
        provider_id, model_id = model.split("/", 1)
    created = int(time.time() * 1000)
    message_id = payload.get("client_message_id")
    part_id = payload.get("client_part_id")
    if isinstance(message_id, str) and isinstance(part_id, str):
        await emit_opencode_event(
            core,
            "message.updated",
            {
                "id": message_id,
                "sessionID": session_id,
                "role": "user",
                "directory": payload.get("directory"),
                "metadata": payload.get("context"),
                "delivery": "steer",
                "time": {"created": created},
            },
        )
        await emit_opencode_event(
            core,
            "message.part.updated",
            {
                "part": {
                    "id": part_id,
                    "messageID": message_id,
                    "sessionID": session_id,
                    "type": "text",
                    "text": payload.get("text") or "",
                }
            },
        )
    await emit_opencode_event(
        core,
        "message.updated",
        {
            "id": f"msg_{uuid.uuid4().hex}",
            "sessionID": session_id,
            "role": "assistant",
            "agent": payload.get("agent_id") or "build",
            "providerID": provider_id,
            "modelID": model_id,
            "directory": payload.get("directory"),
            "time": {"created": created, "completed": created},
            "error": {"name": "APIError", "data": error_data},
        },
    )


async def _events(core: PenguinCore) -> AsyncIterator[str]:
    queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=_EVENT_QUEUE_SIZE)
    overflowed = asyncio.Event()
    event_bus = getattr(core, "event_bus", None)
    projector = OpenCodeV2EventProjector()
    durable_sequences: dict[str, int] = {}

    def handler(event_type: str, data: Any) -> None:
        if event_type != "opencode_event" or not isinstance(data, dict):
            return
        source = _interrupt_source(core, data)
        projected = projector.project(source)
        if not projected and source.get("type") not in _NATIVE_LIFECYCLE_SOURCE_TYPES:
            fallback = event_payload(source)
            if fallback is not None:
                projected = [fallback]
        for projected_item in projected:
            item = _sequence_durable_event(projected_item, durable_sequences)
            try:
                queue.put_nowait(item)
            except asyncio.QueueFull:
                logger.warning("OpenCode 2 event subscriber overflowed")
                overflowed.set()
                break

    subscribe = getattr(event_bus, "subscribe", None)
    unsubscribe = getattr(event_bus, "unsubscribe", None)
    if callable(subscribe):
        subscribe("opencode_event", handler)
    try:
        yield _frame(server_connected_event(uuid.uuid4().hex))
        while True:
            queued = asyncio.create_task(queue.get())
            failed = asyncio.create_task(overflowed.wait())
            done, pending = await asyncio.wait(
                {queued, failed},
                timeout=_HEARTBEAT_SECONDS,
                return_when=asyncio.FIRST_COMPLETED,
            )
            for task in pending:
                task.cancel()
            if pending:
                await asyncio.gather(*pending, return_exceptions=True)
            if failed in done:
                if queued in done:
                    queued.result()
                return
            if queued in done:
                yield _frame(queued.result())
            else:
                yield ": heartbeat\n\n"
    except asyncio.CancelledError:
        return
    finally:
        if callable(unsubscribe):
            unsubscribe("opencode_event", handler)


def _interrupt_intents(core: PenguinCore) -> set[str]:
    intents = getattr(core, "_opencode_v2_interrupt_intents", None)
    if not isinstance(intents, set):
        intents = set()
        setattr(core, "_opencode_v2_interrupt_intents", intents)
    return cast("set[str]", intents)


def _prompt_reservations(core: PenguinCore) -> set[str]:
    reservations = getattr(core, "_opencode_v2_prompt_reservations", None)
    if not isinstance(reservations, set):
        reservations = set()
        setattr(core, "_opencode_v2_prompt_reservations", reservations)
    return cast("set[str]", reservations)


def _prompt_tasks(core: PenguinCore) -> dict[str, asyncio.Task[None]]:
    tasks = getattr(core, "_opencode_v2_prompt_tasks", None)
    if not isinstance(tasks, dict):
        tasks = {}
        setattr(core, "_opencode_v2_prompt_tasks", tasks)
    return cast("dict[str, asyncio.Task[None]]", tasks)


def _deleting_sessions(core: PenguinCore) -> set[str]:
    sessions = getattr(core, "_opencode_v2_deleting_sessions", None)
    if not isinstance(sessions, set):
        sessions = set()
        setattr(core, "_opencode_v2_deleting_sessions", sessions)
    return cast("set[str]", sessions)


def _active_session_ids(core: PenguinCore) -> set[str]:
    active = active_sessions_payload(core).get("data", {})
    return set(active) if isinstance(active, dict) else set()


async def _interrupt_active_session(core: PenguinCore, session_id: str) -> None:
    """Route V2 interruption through Penguin and settle its admitted task."""
    intents = _interrupt_intents(core)
    intents.add(session_id)
    task = _prompt_tasks(core).get(session_id)
    interrupted = False
    try:
        handler = getattr(core, "abort_session", None)
        if callable(handler):
            interrupted = await handler(session_id) is not False
        if task is not None and task is not asyncio.current_task() and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            interrupted = True
        if interrupted:
            await emit_opencode_event(
                core,
                "session.execution.interrupted",
                {"sessionID": session_id, "reason": "user"},
            )
    finally:
        intents.discard(session_id)
        _prompt_reservations(core).discard(session_id)


async def _await_session_idle(core: PenguinCore, session_id: str) -> None:
    """Wait for Penguin's existing request tasks to settle after cancellation."""
    tasks_map = getattr(core, "_opencode_process_tasks", None)
    tasks = tasks_map.get(session_id, set()) if isinstance(tasks_map, dict) else set()
    pending = [task for task in tasks if isinstance(task, asyncio.Task)]
    if pending:
        await asyncio.gather(*pending, return_exceptions=True)
    _prompt_reservations(core).discard(session_id)


def _sequence_durable_event(
    event: dict[str, Any],
    sequences: dict[str, int],
) -> dict[str, Any]:
    """Assign one connection-local contiguous sequence to every durable event."""
    durable = event.get("durable")
    if not isinstance(durable, dict):
        return event
    aggregate_id = durable.get("aggregateID")
    if not isinstance(aggregate_id, str) or not aggregate_id:
        return event
    sequence = sequences.get(aggregate_id, 0)
    sequences[aggregate_id] = sequence + 1
    normalized = dict(event)
    normalized["durable"] = {**durable, "seq": sequence}
    return normalized


def _interrupt_source(core: PenguinCore, data: dict[str, Any]) -> dict[str, Any]:
    """Translate the legacy idle emitted during a V2 cancel into interruption."""
    if data.get("type") != "session.status":
        return data
    properties = data.get("properties")
    if not isinstance(properties, dict):
        return data
    status = properties.get("status")
    session_id = properties.get("sessionID")
    if (
        not isinstance(status, dict)
        or status.get("type") != "idle"
        or not isinstance(session_id, str)
        or session_id not in _interrupt_intents(core)
    ):
        return data
    translated = dict(data)
    translated["type"] = "session.execution.interrupted"
    translated["properties"] = {
        "sessionID": session_id,
        "reason": "user",
        "directory": properties.get("directory"),
    }
    return translated


def _frame(event: dict[str, Any]) -> str:
    return f"data: {json.dumps(event, separators=(',', ':'))}\n\n"


def _v1_session(projected: dict[str, Any]) -> dict[str, Any]:
    """Build the minimum legacy info needed by the shared delete emitter."""
    return {
        "id": projected["id"],
        "title": projected.get("title", ""),
        "directory": projected["location"]["directory"],
    }


__all__ = ["OpenCodeV2HTTPError", "get_core", "handle_http_error", "router"]
