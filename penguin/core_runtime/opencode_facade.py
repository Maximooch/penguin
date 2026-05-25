"""OpenCode/TUI compatibility facade methods for ``PenguinCore``."""

from __future__ import annotations

import logging
from typing import Any

from penguin.system.execution_context import get_current_execution_context

from . import (
    action_events as core_action_events,
    action_mapping as core_action_mapping,
    opencode_adapters as core_opencode_adapters,
    opencode_bridge as core_opencode_bridge,
    opencode_persistence as core_opencode_persistence,
    session_lookup as core_session_lookup,
    stream_events as core_stream_events,
)

__all__ = ["OpenCodeCoreFacade"]

logger = logging.getLogger("penguin.core")


class OpenCodeCoreFacade:
    """Compatibility methods for OpenCode/TUI bridge integrations."""

    def _subscribe_to_stream_events(self) -> None:
        """Subscribe to Penguin stream events and translate to OpenCode format."""
        core_stream_events.subscribe_to_stream_events(self)

    def _get_tui_adapter(self, session_id: str | None) -> Any:
        """Return a session-scoped TUI adapter to avoid cross-session bleed."""
        return core_opencode_adapters.get_tui_adapter(
            self,
            session_id,
            execution_context=get_current_execution_context(),
        )

    async def _on_tui_stream_chunk(
        self,
        event_type: str,
        data: dict[str, Any],
    ) -> None:
        """Handle stream chunk lifecycle and emit OpenCode deltas."""
        await core_stream_events.handle_tui_stream_chunk(
            self,
            event_type,
            data,
            logger=logger,
        )

    def _strip_diff_fences(self, diff_content: str) -> str:
        return core_action_mapping.strip_diff_fences(diff_content)

    def _ensure_unified_diff(self, file_path: str, diff_content: str) -> str:
        return core_action_mapping.ensure_unified_diff(file_path, diff_content)

    def _extract_unified_diff_from_result(self, result: Any) -> str:
        return core_action_mapping.extract_unified_diff_from_result(result)

    def _extract_tool_file_path(self, tool_input: Any) -> str:
        return core_action_mapping.extract_tool_file_path(tool_input)

    def _normalize_todo_items(self, value: Any) -> list[dict[str, str]]:
        return core_action_mapping.normalize_todo_items(value)

    def _extract_todos_from_result(self, result: Any) -> list[dict[str, str]]:
        return core_action_mapping.extract_todos_from_result(result)

    def _parse_action_payload(self, params: Any) -> dict[str, Any]:
        return core_action_mapping.parse_action_payload(params)

    def _extract_result_file_paths(self, result: Any) -> list[str]:
        return core_action_mapping.extract_result_file_paths(result)

    def _humanize_subagent_name(self, value: Any) -> str:
        return core_action_mapping.humanize_subagent_name(value)

    def _summarize_subagent_description(self, value: Any, fallback: str) -> str:
        return core_action_mapping.summarize_subagent_description(value, fallback)

    def _build_task_card_summary(
        self,
        label: str,
        status: str,
        *,
        item_id: str | None = None,
        title: str | None = None,
    ) -> list[dict[str, Any]]:
        return core_action_mapping.build_task_card_summary(
            label,
            status,
            item_id=item_id,
            title=title,
        )

    def _summary_status(self, metadata: dict[str, Any], default: str) -> str:
        return core_action_mapping.summary_status(metadata, default)

    def _build_spawn_subagent_task_card(
        self,
        params: Any,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        return core_action_mapping.build_spawn_subagent_task_card(params)

    def _map_action_to_tool(
        self,
        action: str,
        params: Any,
    ) -> tuple[str, dict[str, Any], dict[str, Any]]:
        return core_action_mapping.map_action_to_tool(action, params)

    def _map_action_result_metadata(
        self,
        action: str,
        result: Any,
        existing: dict[str, Any] | None = None,
        tool_input: dict[str, Any] | None = None,
        status: str | None = None,
        event_metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return core_action_mapping.map_action_result_metadata(
            action,
            result,
            existing=existing,
            tool_input=tool_input,
            status=status,
            event_metadata=event_metadata,
        )

    async def _on_tui_action(self, event_type: str, data: dict[str, Any]) -> None:
        await core_action_events.handle_tui_action(self, event_type, data)

    async def _on_tui_action_result(
        self,
        event_type: str,
        data: dict[str, Any],
    ) -> None:
        await core_action_events.handle_tui_action_result(self, event_type, data)

    async def _on_tui_todo_updated(
        self,
        event_type: str,
        data: dict[str, Any],
    ) -> None:
        await core_action_events.handle_tui_todo_updated(
            self,
            event_type,
            data,
            execution_context=get_current_execution_context(),
            session_directories=getattr(self, "_opencode_session_directories", None),
        )

    async def _on_tui_lsp_updated(
        self,
        event_type: str,
        data: dict[str, Any],
    ) -> None:
        await core_action_events.handle_tui_lsp_updated(
            self,
            event_type,
            data,
            execution_context=get_current_execution_context(),
            session_directories=getattr(self, "_opencode_session_directories", None),
        )

    async def _on_tui_lsp_diagnostics(
        self,
        event_type: str,
        data: dict[str, Any],
    ) -> None:
        await core_action_events.handle_tui_lsp_diagnostics(
            self,
            event_type,
            data,
            execution_context=get_current_execution_context(),
            session_directories=getattr(self, "_opencode_session_directories", None),
        )

    def _find_session_store(self, session_id: str) -> tuple[Any | None, Any | None]:
        """Locate session and owning session manager for a given session id."""
        return core_session_lookup.find_session_store(self, session_id)

    def _resolve_opencode_model_state(
        self,
        *,
        session_id: str | None = None,
        model_id: str | None = None,
        provider_id: str | None = None,
        variant: str | None = None,
    ) -> dict[str, str | None]:
        """Resolve model/provider/variant for OpenCode event persistence."""
        return core_opencode_persistence.resolve_opencode_model_state(
            self,
            session_id=session_id,
            model_id=model_id,
            provider_id=provider_id,
            variant=variant,
        )

    async def _persist_opencode_event(
        self,
        event_type: str,
        properties: dict[str, Any],
    ) -> None:
        """Persist OpenCode message/part events for replay via session history."""
        await core_opencode_persistence.persist_opencode_event(
            self,
            event_type=event_type,
            properties=properties,
            logger=logger,
            execution_context=get_current_execution_context(),
        )

    async def _emit_opencode_stream_start(
        self,
        agent_id: str = "default",
        model_id: str | None = None,
        provider_id: str | None = None,
    ) -> tuple[str, str]:
        """Initialize OpenCode streaming and create message/part records."""
        return await core_stream_events.emit_opencode_stream_start(
            self,
            agent_id=agent_id,
            model_id=model_id,
            provider_id=provider_id,
            execution_context=get_current_execution_context(),
        )

    async def _emit_opencode_stream_chunk(
        self,
        message_id: str,
        part_id: str,
        chunk: str,
        message_type: str = "assistant",
    ) -> None:
        """Emit an OpenCode-compatible stream chunk with delta."""
        await core_stream_events.emit_opencode_stream_chunk(
            self,
            message_id,
            part_id,
            chunk,
            message_type,
        )

    async def _emit_opencode_stream_end(self, message_id: str, part_id: str) -> None:
        """Finalize OpenCode streaming."""
        await core_stream_events.emit_opencode_stream_end(self, message_id, part_id)

    def _latest_model_usage(self) -> dict[str, Any]:
        """Return normalized usage metadata from active model handler."""
        return core_opencode_bridge.latest_model_usage(
            getattr(self, "api_client", None)
        )

    async def _apply_opencode_usage_to_latest_message(
        self,
        session_id: str | None,
        usage: dict[str, Any],
    ) -> None:
        await core_opencode_bridge.apply_usage_to_core_latest_message(
            self,
            session_id,
            usage,
            logger=logger,
        )

    async def _emit_opencode_user_message(self, content: str) -> str:
        """Emit user message in OpenCode format."""
        return await self._emit_opencode_user_message_with_metadata(content)

    async def _emit_opencode_user_message_with_metadata(
        self,
        content: str,
        *,
        message_id: str | None = None,
        agent_id: str | None = None,
    ) -> str:
        """Emit user message in OpenCode format with stable message metadata."""
        return await core_stream_events.emit_opencode_user_message_with_metadata(
            self,
            content,
            message_id=message_id,
            agent_id=agent_id,
            execution_context=get_current_execution_context(),
        )
