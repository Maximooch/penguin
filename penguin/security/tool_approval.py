"""Pause tool dispatch for a user reply without returning ASK to the model."""

from __future__ import annotations

import asyncio
import json
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
from typing import TYPE_CHECKING, Any

from penguin.security.approval import ApprovalStatus, get_approval_manager
from penguin.security.tool_permissions import (
    extract_resources_from_input,
    get_highest_risk_operation,
    get_tool_operations,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

_authorized_paths: ContextVar[frozenset[Path]] = ContextVar(
    "authorized_tool_paths", default=frozenset()
)

_authorized_call: ContextVar[str | None] = ContextVar(
    "authorized_tool_call", default=None
)


def _call_key(tool: str, arguments: dict[str, Any], context: dict[str, Any]) -> str:
    # The process dispatcher adds this control signal after approval. It is not
    # authority, and must not turn an approved call into another ASK.
    authority = {
        key: value for key, value in context.items() if key != "process_cancel_event"
    }
    return json.dumps([tool, arguments, authority], sort_keys=True, default=str)


def is_call_authorized(
    tool: str, arguments: dict[str, Any], context: dict[str, Any]
) -> bool:
    """Check the internal dispatch grant; tool arguments cannot supply grants."""
    return _authorized_call.get() == _call_key(tool, arguments, context)


@contextmanager
def authorized_call(
    tool: str, arguments: dict[str, Any], context: dict[str, Any], resources: list[str]
) -> Iterator[None]:
    """Scope a grant to one dispatch, including its synchronous worker thread."""
    token = _authorized_call.set(_call_key(tool, arguments, context))
    paths = (
        frozenset(Path(resource) for resource in resources)
        if any(op.category == "filesystem" for op in get_tool_operations(tool))
        else frozenset()
    )
    path_token = _authorized_paths.set(paths)
    try:
        yield
    finally:
        _authorized_paths.reset(path_token)
        _authorized_call.reset(token)


def is_path_authorized(path: Path) -> bool:
    """Allow only exact resolved targets of the current authorized dispatch."""
    return path.expanduser().resolve() in _authorized_paths.get()


def approval_identity(
    tool: str, arguments: dict[str, Any], context: dict[str, Any]
) -> tuple[str, str, list[str]]:
    """Describe the operation and every target covered by an approval."""
    operation = get_highest_risk_operation(tool)
    resources = extract_resources_from_input(tool, arguments, context)
    # Unknown tools have no resource extractor: bind approval to their arguments.
    resource = (
        resources[0]
        if len(resources) == 1
        else json.dumps(resources or arguments, sort_keys=True)
    )
    return operation.value if operation else f"tool.{tool}", resource, resources


async def wait_for_tool_approval(response: str | dict[str, Any]) -> bool:
    """Wait for approval, expiring or rejecting the request on cancellation."""
    payload = json.loads(response) if isinstance(response, str) else response
    manager = get_approval_manager()
    request_id = payload["approval_id"]
    try:
        while True:
            manager.get_pending()
            request = manager.get_request(request_id)
            if request is None:
                return False
            if request.status != ApprovalStatus.PENDING:
                return request.status == ApprovalStatus.APPROVED
            await asyncio.sleep(0.05)
    except asyncio.CancelledError:
        manager.deny(request_id)
        raise


__all__ = [
    "approval_identity",
    "authorized_call",
    "is_call_authorized",
    "is_path_authorized",
    "wait_for_tool_approval",
]
