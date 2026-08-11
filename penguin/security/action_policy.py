"""Request-scoped authorization for model-emitted ActionXML actions."""

from __future__ import annotations

import asyncio
import json
import logging
import math
from typing import Any, Mapping

from penguin.security.approval import ApprovalStatus, get_approval_manager
from penguin.system.execution_context import get_current_execution_context

logger = logging.getLogger(__name__)


# ActionXML handlers in this table mutate state without a complete ToolManager
# permission route, so they need an equivalent request-scoped gate at the
# dispatch boundary. Tool-backed actions with a canonical permission mapping
# are intentionally omitted: their normal ToolManager dispatch owns approval
# resumption.
DIRECT_ACTION_POLICY_KEYS: dict[str, str] = {
    "add_summary_note": "fileWrite",
    "process_start": "shell",
    "process_list": "shell",
    "process_enter": "shell",
    "process_stop": "shell",
    "process_send": "shell",
    "process_exit": "fileWrite",
    "project_create": "fileWrite",
    "project_update": "fileWrite",
    "project_delete": "fileDelete",
    "task_create": "fileWrite",
    "task_update": "fileWrite",
    "task_complete": "fileWrite",
    "task_delete": "fileDelete",
    "finish_task": "fileWrite",
    "task_completed": "fileWrite",
    "todowrite": "fileWrite",
    "send_message": "network",
    "spawn_sub_agent": "default",
    "stop_sub_agent": "default",
    "resume_sub_agent": "default",
    "delegate": "network",
    "delegate_explore_task": "network",
    "browser_navigate": "network",
    "browser_interact": "network",
    "browser_screenshot": "fileWrite",
    "pydoll_browser_navigate": "network",
    "pydoll_browser_interact": "network",
    "pydoll_browser_screenshot": "fileWrite",
    "pydoll_browser_scroll": "network",
    "pydoll_debug_toggle": "default",
}


SAFE_ACTION_NAMES = frozenset(
    {
        "memory_search",
        "process_status",
        "todoread",
        "question",
        "task_list",
        "task_display",
        "finish_response",
        "list_skills",
        "activate_skill",
        "project_list",
        "project_display",
        "dependency_display",
        "wait_for_agents",
    }
)


TOOL_MANAGED_ACTION_NAMES = frozenset(
    {
        "execute",
        "execute_command",
        "search",
        "add_declarative_note",
        "list_files_filtered",
        "find_files_enhanced",
        "enhanced_diff",
        "analyze_project",
        "read_file",
        "read_image",
        "publish_artifact",
        "enhanced_read",
        "enhanced_write",
        "write_file",
        "edit_file",
        "apply_patch",
        "apply_diff",
        "patch_file",
        "multiedit",
        "patch_files",
        "edit_with_pattern",
        "replace_lines",
        "insert_lines",
        "delete_lines",
        "perplexity_search",
        "workspace_search",
        "analyze_codebase",
        "reindex_workspace",
        "browser_status",
        "browser_cleanup",
        "browser_open_tab",
        "browser_page_info",
        "browser_harness_screenshot",
        "browser_click",
        "browser_type",
        "browser_key",
        "browser_fill",
        "browser_wait",
        "browser_js",
        "browser_list_tabs",
        "browser_switch_tab",
        "get_agent_status",
        "get_context_info",
        "sync_context",
        "get_repository_status",
        "create_and_switch_branch",
        "commit_and_push_changes",
        "create_improvement_pr",
        "create_feature_pr",
        "create_bugfix_pr",
    }
)


def policy_timeout_seconds(policy: Mapping[str, Any]) -> float | None:
    """Return a bounded policy timeout, preserving a missing timeout."""
    raw_timeout = policy.get("timeout_seconds")
    if raw_timeout is None:
        return None
    if isinstance(raw_timeout, bool):
        return 0.0
    try:
        parsed_timeout = float(raw_timeout)
    except (TypeError, ValueError):
        return 0.0
    if not math.isfinite(parsed_timeout):
        return 0.0
    return min(3600.0, max(0.0, parsed_timeout))


async def authorize_direct_action(action_name: str, params: Any) -> str | None:
    """Authorize a direct ActionXML mutation under the active request policy."""
    context = get_current_execution_context()
    if context is None:
        return None
    if action_name in SAFE_ACTION_NAMES:
        return None
    if action_name in TOOL_MANAGED_ACTION_NAMES:
        return None

    policy_key = DIRECT_ACTION_POLICY_KEYS.get(action_name, "default")

    if str(context.permission_mode or "").strip().lower() == "read_only":
        return json.dumps(
            {
                "error": "permission_denied",
                "action": action_name,
                "reason": "Request-scoped read-only mode blocks mutating actions",
            }
        )

    approval_policy = context.approval_policy
    if not isinstance(approval_policy, dict):
        return None
    decision = (
        str(
            approval_policy.get(
                policy_key,
                approval_policy.get("default", ""),
            )
        )
        .strip()
        .lower()
    )
    if decision == "deny":
        return json.dumps(
            {
                "error": "permission_denied",
                "action": action_name,
                "reason": "Request-scoped approval policy denies this action",
            }
        )
    if decision != "ask":
        return None

    if approval_policy.get("default") == "deny":
        return json.dumps(
            {
                "error": "permission_denied",
                "action": action_name,
                "reason": "Remote approval policy denies prompted actions",
            }
        )

    try:
        manager = get_approval_manager()
        operation = f"action.{action_name}"
        resource = str(params or "").strip()[:500]
        session_id = context.session_id or context.conversation_id
        if manager.check_pre_approved(operation, resource, session_id):
            return None

        timeout_seconds = policy_timeout_seconds(approval_policy)
        request = manager.create_request(
            tool_name=action_name,
            operation=operation,
            resource=resource,
            reason="Request-scoped approval policy requires approval",
            session_id=session_id,
            context={
                "action": action_name,
                "agent_id": context.agent_id,
                "request_id": context.request_id,
            },
            ttl_seconds=timeout_seconds,
        )

        if approval_policy.get("wait_for_resolution") is not True:
            return json.dumps(
                {
                    "status": "pending_approval",
                    "approval_id": request.id,
                    "action": action_name,
                    "operation": operation,
                    "resource": resource,
                }
            )

        try:
            resolved = await asyncio.to_thread(
                manager.wait_for_resolution,
                request.id,
                timeout_seconds,
            )
        except asyncio.CancelledError:
            await asyncio.to_thread(manager.deny, request.id)
            raise

        if resolved is not None and resolved.status == ApprovalStatus.APPROVED:
            consumed = await asyncio.to_thread(
                manager.consume_approved_request,
                request.id,
                tool_name=action_name,
                operation=operation,
                resource=resource,
                session_id=session_id,
            )
            if consumed:
                return None
            return json.dumps(
                {
                    "error": "approval_grant_invalid",
                    "approval_id": request.id,
                    "action": action_name,
                }
            )

        status = resolved.status if resolved is not None else None
        error = {
            ApprovalStatus.DENIED: "approval_denied",
            ApprovalStatus.EXPIRED: "approval_expired",
        }.get(status, "approval_unavailable")
        return json.dumps(
            {
                "error": error,
                "status": status.value if status is not None else "unavailable",
                "approval_id": request.id,
                "action": action_name,
            }
        )
    except asyncio.CancelledError:
        raise
    except Exception as error:
        logger.error(
            "Failed to authorize direct ActionXML action %s: %s",
            action_name,
            error,
        )
        return json.dumps(
            {
                "error": "approval_error",
                "action": action_name,
                "message": str(error),
            }
        )


async def deny_pending_approvals_for_current_request() -> None:
    """Deny this turn's pending approvals after ActionXML cancellation."""
    context = get_current_execution_context()
    if context is None:
        return
    request_id = context.request_id
    session_id = context.session_id or context.conversation_id
    if not request_id or not session_id:
        return

    def _deny_matching() -> int:
        manager = get_approval_manager()
        denied = 0
        for request in manager.get_pending(session_id=session_id):
            request_context = getattr(request, "context", None)
            if not isinstance(request_context, dict):
                continue
            if request_context.get("request_id") != request_id:
                continue
            if manager.deny(request.id) is not None:
                denied += 1
        return denied

    try:
        await asyncio.to_thread(_deny_matching)
    except Exception:
        logger.exception(
            "Failed to deny cancelled ActionXML approvals request=%s",
            request_id,
        )


__all__ = [
    "DIRECT_ACTION_POLICY_KEYS",
    "SAFE_ACTION_NAMES",
    "TOOL_MANAGED_ACTION_NAMES",
    "authorize_direct_action",
    "deny_pending_approvals_for_current_request",
    "policy_timeout_seconds",
]
