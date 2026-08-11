"""Telegram command handling kept outside the gateway lifecycle."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from penguin.config import WORKSPACE_PATH

if TYPE_CHECKING:
    from penguin.channels.schema import InboundEnvelope


async def handle_command(
    manager: Any,
    command: str,
    arguments: str,
    envelope: InboundEnvelope,
    binding: Any,
) -> str | None:
    """Execute one already-authorized Telegram command."""

    store = manager.store
    assert store is not None
    if command in {"start", "help"}:
        return (
            "Penguin is ready. Send a message or use /new, /status, /stop, "
            "/session, /mode, /model, /goal, /project, /activation, /topic, "
            "/pair, or /whoami."
        )
    if command == "whoami":
        return (
            f"Telegram user ID: {envelope.sender_id}\n"
            f"Chat ID: {envelope.address.chat_id}\n"
            f"Topic ID: {envelope.address.topic_id or 'none'}"
        )
    if command == "status":
        return (
            f"Penguin Telegram: running\nSession: {binding.session_id}\n"
            f"Mode: {getattr(binding, 'agent_mode', None) or 'build'}"
        )
    if command == "session":
        return f"Penguin session: {binding.session_id}"
    if command == "new":
        replacement = await manager._new_binding(envelope.address, binding)
        return f"Started a new Penguin session: {replacement.session_id}"
    if command == "stop":
        abort = getattr(manager.core, "abort_session", None)
        stopped = bool(await abort(binding.session_id)) if callable(abort) else False
        return "Stopped the active Penguin turn." if stopped else "No active turn."
    if command == "mode":
        normalized = arguments.strip().lower()
        if not normalized:
            return f"Mode: {getattr(binding, 'agent_mode', None) or 'build'}"
        if normalized not in {"plan", "build"}:
            return "Usage: /mode plan|build"
        updated = await asyncio.to_thread(
            store.upsert_binding,
            envelope.address.lane_key,
            binding.session_id,
            directory=getattr(binding, "directory", None),
            agent_id=getattr(binding, "agent_id", None),
            agent_mode=normalized,
            settings=getattr(binding, "settings", {}),
            expected_version=binding.version,
        )
        return f"Mode set to {updated.agent_mode}."
    if command == "activation":
        if envelope.metadata.get("chat_type") == "private":
            return "/activation is only available in groups and topics."
        activation = arguments.strip().lower()
        if activation not in {"mention", "always"}:
            return "Usage: /activation mention|always"
        settings = dict(getattr(binding, "settings", {}) or {})
        settings["activation"] = activation
        await asyncio.to_thread(
            store.upsert_binding,
            envelope.address.lane_key,
            binding.session_id,
            directory=getattr(binding, "directory", None),
            agent_id=getattr(binding, "agent_id", None),
            agent_mode=getattr(binding, "agent_mode", None),
            settings=settings,
            expected_version=binding.version,
        )
        return f"Activation set to {activation}."
    if command == "topic":
        return (
            f"Topic binding: {envelope.address.topic_id or 'none'}\n"
            f"Session: {binding.session_id}"
        )
    if command == "model":
        model_config = getattr(manager.core, "model_config", None)
        model = getattr(model_config, "model", None) or "not configured"
        return f"Active Penguin model: {model}"
    if command == "project":
        directory = getattr(binding, "directory", None) or WORKSPACE_PATH
        return f"Project directory: {directory}"
    if command == "goal":
        from penguin.web.services.session_goal_command import (
            execute_session_goal_command,
            parse_session_goal_command,
        )

        parsed = parse_session_goal_command(f"/goal {arguments}".rstrip())
        if parsed is None:
            return "Invalid /goal command."
        result = await execute_session_goal_command(
            manager.core,
            binding.session_id,
            parsed,
            directory=getattr(binding, "directory", None),
        )
        if result.get("assistant_response"):
            return str(result["assistant_response"])
        goal = result.get("goal")
        return "No active goal." if goal is None else f"Goal: {goal}"
    if command == "pair":
        return "This Telegram identity is already authorized."
    return "Unknown command. Use /help for supported commands."


__all__ = ["handle_command"]
