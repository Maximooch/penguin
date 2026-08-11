"""Async-first dispatch for tools that own coroutine lifecycles."""

from __future__ import annotations

import asyncio
import json
import logging
import math
from typing import TYPE_CHECKING, Any, Awaitable, Callable

from penguin.multi.policy import (
    SUBAGENT_TOOL_NAMES,
    disabled_subagent_result,
    subagents_enabled,
)
from penguin.security.approval import ApprovalStatus, get_approval_manager
from penguin.utils.profiling import profile_operation

if TYPE_CHECKING:
    from penguin.tools.tool_manager import ToolManager

logger = logging.getLogger(__name__)

ASYNC_TOOL_NAMES = frozenset(
    {
        "browser_interact",
        "browser_navigate",
        "browser_screenshot",
        "delegate",
        "delegate_explore_task",
        "get_agent_status",
        "get_context_info",
        "memory_search",
        "pydoll_browser_interact",
        "pydoll_browser_navigate",
        "pydoll_browser_screenshot",
        "reindex_workspace",
        "resume_sub_agent",
        "send_message",
        "spawn_sub_agent",
        "stop_sub_agent",
        "sync_context",
        "wait_for_agents",
    }
)


class AsyncToolDispatcher:
    """Execute coroutine-backed tools on the caller's owning event loop."""

    def __init__(self, tool_manager: ToolManager) -> None:
        """Initialize a dispatcher for one ToolManager instance."""

        self._tool_manager = tool_manager

    def _build_call(
        self,
        tool_name: str,
        tool_input: dict[str, Any],
    ) -> Awaitable[Any]:
        """Build the selected async tool coroutine without scheduling it."""

        manager = self._tool_manager
        tool_map: dict[str, Callable[[], Awaitable[Any]]] = {
            "memory_search": lambda: manager.perform_memory_search(
                tool_input["query"],
                tool_input.get("k", 5),
                tool_input.get("memory_type"),
                tool_input.get("categories"),
            ),
            "browser_navigate": lambda: manager.execute_browser_navigate(
                tool_input["url"]
            ),
            "browser_interact": lambda: manager.execute_browser_interact(
                tool_input["action"],
                tool_input["selector"],
                tool_input.get("text"),
            ),
            "browser_screenshot": manager.execute_browser_screenshot,
            "pydoll_browser_navigate": lambda: manager.execute_pydoll_browser_navigate(
                tool_input["url"]
            ),
            "pydoll_browser_interact": lambda: manager.execute_pydoll_browser_interact(
                tool_input["action"],
                tool_input["selector"],
                tool_input.get("selector_type", "css"),
                tool_input.get("text"),
            ),
            "pydoll_browser_screenshot": manager.execute_pydoll_browser_screenshot,
            "reindex_workspace": lambda: manager.reindex_workspace(
                tool_input.get("directory"),
                tool_input.get("force_full", False),
                tool_input.get("file_types"),
            ),
            "send_message": lambda: manager._execute_send_message(tool_input),
            "spawn_sub_agent": lambda: manager._execute_spawn_sub_agent(tool_input),
            "stop_sub_agent": lambda: manager._execute_stop_sub_agent(tool_input),
            "resume_sub_agent": lambda: manager._execute_resume_sub_agent(tool_input),
            "get_agent_status": lambda: manager._execute_get_agent_status(tool_input),
            "wait_for_agents": lambda: manager._execute_wait_for_agents(tool_input),
            "get_context_info": lambda: manager._execute_get_context_info(tool_input),
            "sync_context": lambda: manager._execute_sync_context(tool_input),
            "delegate": lambda: manager._execute_delegate(tool_input),
            "delegate_explore_task": lambda: manager._execute_delegate_explore_task(
                tool_input
            ),
        }
        return tool_map[tool_name]()

    @staticmethod
    def _approval_wait_settings(
        context: dict[str, Any],
    ) -> tuple[bool, float | None]:
        """Read the opt-in resumable approval settings from a request context."""
        policy = context.get("approval_policy")
        if (
            not isinstance(policy, dict)
            or policy.get("wait_for_resolution") is not True
        ):
            return False, None

        raw_timeout = policy.get("timeout_seconds")
        if raw_timeout is None:
            return True, None
        if isinstance(raw_timeout, bool):
            return True, 0.0
        try:
            timeout = float(raw_timeout)
        except (TypeError, ValueError):
            return True, 0.0
        if not math.isfinite(timeout):
            return True, 0.0
        return True, max(timeout, 0.0)

    @staticmethod
    def _pending_approval_id(
        permission_response: str | dict[str, Any],
    ) -> str | None:
        """Extract a pending approval ID from a permission response."""
        payload: Any = permission_response
        if isinstance(permission_response, str):
            try:
                payload = json.loads(permission_response)
            except json.JSONDecodeError:
                return None
        if not isinstance(payload, dict):
            return None
        if payload.get("status") != "pending_approval":
            return None
        request_id = payload.get("approval_id")
        return request_id if isinstance(request_id, str) and request_id else None

    @staticmethod
    def _approval_failure_response(
        request_id: str,
        status: ApprovalStatus | None,
        tool_name: str,
    ) -> str:
        """Build a stable terminal response for a non-approved request."""
        status_value = status.value if status is not None else "unavailable"
        error = {
            ApprovalStatus.DENIED: "approval_denied",
            ApprovalStatus.EXPIRED: "approval_expired",
        }.get(status, "approval_unavailable")
        return json.dumps(
            {
                "error": error,
                "status": status_value,
                "approval_id": request_id,
                "tool": tool_name,
            }
        )

    async def _resolve_permission(
        self,
        tool_name: str,
        tool_input: dict[str, Any],
        context: dict[str, Any],
    ) -> tuple[str | dict[str, Any] | None, str | None]:
        """Check permission and optionally await an approval off-loop."""
        manager = self._tool_manager
        wait_for_resolution, timeout_seconds = self._approval_wait_settings(context)
        if wait_for_resolution:
            permission_response = await asyncio.to_thread(
                manager._permission_response,
                tool_name,
                tool_input,
                context,
            )
        else:
            # Preserve the existing HTTP callback/event-loop behavior when the
            # request has not opted into a blocking approval lifecycle.
            permission_response = manager._permission_response(
                tool_name,
                tool_input,
                context,
            )
        if permission_response is None:
            return None, None

        request_id = self._pending_approval_id(permission_response)
        if not wait_for_resolution or request_id is None:
            return permission_response, None

        approval_manager = get_approval_manager()
        try:
            resolved = await asyncio.to_thread(
                approval_manager.wait_for_resolution,
                request_id,
                timeout_seconds,
            )
        except asyncio.CancelledError:
            # Cancelled channel/server work must not strand a worker thread or
            # leave a stale approval capable of resuming later.
            await asyncio.to_thread(approval_manager.deny, request_id)
            raise
        if resolved is not None and resolved.status == ApprovalStatus.APPROVED:
            return None, request_id
        return (
            self._approval_failure_response(
                request_id,
                resolved.status if resolved is not None else None,
                tool_name,
            ),
            None,
        )

    async def execute(
        self,
        tool_name: str,
        tool_input: dict[str, Any],
        context: dict[str, Any] | None = None,
    ) -> str | dict[str, Any]:
        """Execute a tool without blocking the caller's event loop."""

        manager = self._tool_manager
        requested_name = tool_name
        canonical_name = manager._canonical_tool_name(tool_name)
        effective_context = manager._merged_execution_context(context)
        if canonical_name in SUBAGENT_TOOL_NAMES and not subagents_enabled(
            effective_context
        ):
            return json.dumps(disabled_subagent_result(canonical_name))
        wait_for_resolution, _ = self._approval_wait_settings(effective_context)
        if canonical_name not in ASYNC_TOOL_NAMES and not wait_for_resolution:
            return await asyncio.to_thread(
                manager.execute_tool,
                requested_name,
                tool_input,
                context,
            )

        with profile_operation(f"ToolManager.execute_tool_async.{canonical_name}"):
            file_root = manager._resolve_file_root(effective_context)
            effective_context.setdefault("directory", file_root)
            effective_context.setdefault("project_root", file_root)
            effective_context.setdefault("workspace_root", file_root)
            normalized_input = manager._normalize_tool_input_paths(
                tool_input if isinstance(tool_input, dict) else {},
                file_root,
            )

            permission_response, approval_id = await self._resolve_permission(
                canonical_name,
                normalized_input,
                effective_context,
            )
            if permission_response is not None:
                return permission_response

            if canonical_name not in ASYNC_TOOL_NAMES:
                resume_context = effective_context
                if approval_id is not None:
                    resume_context = manager._with_approval_grant(
                        effective_context,
                        approval_id,
                    )
                return await asyncio.to_thread(
                    manager.execute_tool,
                    requested_name,
                    normalized_input,
                    resume_context,
                )

            if approval_id is not None:
                resume_context = manager._with_approval_grant(
                    effective_context,
                    approval_id,
                )
                consumed = await asyncio.to_thread(
                    manager._consume_approval_grant,
                    canonical_name,
                    normalized_input,
                    resume_context,
                )
                if consumed is not True:
                    return json.dumps(
                        {
                            "error": "approval_grant_invalid",
                            "approval_id": approval_id,
                            "tool": canonical_name,
                        }
                    )

            diagnostic_input = manager._redact_tool_input_for_diagnostics(
                canonical_name,
                normalized_input,
            )
            logger.info(
                "Executing async tool: %s (canonical=%s) with input: %s",
                requested_name,
                canonical_name,
                diagnostic_input,
            )
            try:
                result = await self._build_call(canonical_name, normalized_input)
                if result is None or (isinstance(result, list) and not result):
                    result = {"result": "No results found or empty directory."}
                manager.add_message_to_search(
                    {"role": "assistant", "content": f"Tool use: {canonical_name}"}
                )
                manager.add_message_to_search(
                    {"role": "user", "content": f"Tool result: {result}"}
                )
                logger.info(
                    "Tool %s executed successfully with result: %s",
                    canonical_name,
                    result,
                )
                return result
            except Exception as exc:
                error_message = f"Error executing tool {canonical_name}: {exc}"
                logger.error(error_message)
                manager.log_error(
                    exc,
                    f"Error occurred while executing tool: {canonical_name}",
                )
                return {"error": error_message}


__all__ = ["ASYNC_TOOL_NAMES", "AsyncToolDispatcher"]
