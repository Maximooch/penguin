"""Messaging and multi-agent coordinator command registration."""

from __future__ import annotations

import asyncio
from pathlib import Path  # noqa: TC003 - Typer evaluates command annotations at runtime
from typing import TYPE_CHECKING, Any

import typer

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

__all__ = ["bind_coordination_commands"]


def bind_coordination_commands(
    msg_app: typer.Typer,
    coord_app: typer.Typer,
    initialize: Callable[..., Awaitable[None]],
    core_getter: Callable[[], Any],
    console_getter: Callable[[], Any],
    coordinator_getter: Callable[[], Any],
) -> dict[str, Any]:
    """Register messaging/coordinator commands and return compatibility exports."""

    _core: Any = None

    async def _initialize_core_components_globally(**kwargs: Any) -> None:
        nonlocal _core
        await initialize(**kwargs)
        _core = core_getter()

    def _console() -> Any:
        return console_getter()

    def _coordinator_type() -> Any:
        return coordinator_getter()

    @msg_app.command("to-agent")
    def msg_to_agent(
        agent_id: str = typer.Argument(..., help="Target agent id"),
        content: str = typer.Argument(..., help="Message content"),
        message_type: str = typer.Option(
            "message", "--type", help="Envelope message_type: message|action|status"
        ),
        workspace: Path | None = typer.Option(
            None, "--workspace", help="Workspace path override"
        ),
    ):
        """Send a directed message to an agent via MessageBus."""

        async def _run():
            await _initialize_core_components_globally(workspace_override=workspace)
            assert _core is not None
            ok = await _core.send_to_agent(agent_id, content, message_type=message_type)
            _console().print(f"[bold green]Sent[/bold green] to {agent_id}: {ok}")

        asyncio.run(_run())

    # ---------------------------- Coordinator CLI ----------------------------

    def _get_coordinator() -> Any:
        coordinator_type = _coordinator_type()
        if coordinator_type is None:
            raise RuntimeError("Coordinator not available")
        assert _core is not None
        return coordinator_type(_core)

    @coord_app.command("spawn")
    def coord_spawn(
        agent_id: str = typer.Argument(..., help="New agent id"),
        role: str = typer.Option(
            ...,
            "--role",
            "-r",
            help="Agent role (e.g., planner, researcher, implementer)",
        ),
        system_prompt: str | None = typer.Option(
            None, "--system-prompt", "-s", help="Optional system prompt override"
        ),
        model_output_max_tokens: int | None = typer.Option(
            None, "--model-max-tokens", help="Clamp child CWM at this size"
        ),
        activate: bool = typer.Option(
            False, "--activate/--no-activate", help="Make this agent active by default"
        ),
        persona: str | None = typer.Option(
            None, "--persona", "-p", help="Persona id from config to apply"
        ),
        model_config_id: str | None = typer.Option(
            None, "--model-id", help="Model config id override"
        ),
        default_tools: list[str] | None = typer.Option(
            None,
            "--tool",
            "-t",
            help="Restrict tools available to the agent (repeatable)",
        ),
        shared_context_window_max_tokens: int | None = typer.Option(
            None, "--shared-cw-max", help="Clamp shared context window tokens"
        ),
        workspace: Path | None = typer.Option(
            None, "--workspace", help="Workspace path override"
        ),
    ):
        async def _run():
            await _initialize_core_components_globally(workspace_override=workspace)
            assert _core is not None
            coord = _get_coordinator()
            personas = {entry.get("name") for entry in _core.get_persona_catalog()}
            if persona and persona not in personas:
                _console().print(
                    f"[red]Persona '{persona}' not found in configuration.[/red]"
                )
                raise typer.Exit(code=1)
            model_configs = getattr(_core.config, "model_configs", {}) or {}
            if model_config_id and model_config_id not in model_configs:
                _console().print(
                    "[red]Model id "
                    f"'{model_config_id}' not found in configuration.[/red]"
                )
                raise typer.Exit(code=1)
            tools_tuple = tuple(default_tools) if default_tools else None
            await coord.spawn_agent(
                agent_id,
                role=role,
                system_prompt=system_prompt,
                model_output_max_tokens=model_output_max_tokens,
                activate=activate,
                persona=persona,
                model_config_id=model_config_id,
                default_tools=tools_tuple,
                shared_context_window_max_tokens=shared_context_window_max_tokens,
            )
            _console().print(
                f"[green]Spawned agent[/green] {agent_id} with role '{role}'"
            )

        asyncio.run(_run())

    @coord_app.command("destroy")
    def coord_destroy(
        agent_id: str = typer.Argument(..., help="Agent id to destroy"),
        workspace: Path | None = typer.Option(
            None, "--workspace", help="Workspace path override"
        ),
    ):
        async def _run():
            await _initialize_core_components_globally(workspace_override=workspace)
            coord = _get_coordinator()
            await coord.destroy_agent(agent_id)
            _console().print(
                f"[yellow]Destroyed agent[/yellow] {agent_id} (conversation persists)"
            )

        asyncio.run(_run())

    @coord_app.command("register")
    def coord_register(
        agent_id: str = typer.Argument(..., help="Existing agent id"),
        role: str = typer.Option(..., "--role", "-r", help="Role to register under"),
        workspace: Path | None = typer.Option(
            None, "--workspace", help="Workspace path override"
        ),
    ):
        async def _run():
            await _initialize_core_components_globally(workspace_override=workspace)
            coord = _get_coordinator()
            coord.register_existing(agent_id, role=role)
            _console().print(
                f"[green]Registered agent[/green] {agent_id} to role '{role}'"
            )

        asyncio.run(_run())

    @coord_app.command("send-role")
    def coord_send_role(
        role: str = typer.Option(..., "--role", "-r", help="Target role"),
        content: str = typer.Argument(..., help="Message content"),
        message_type: str = typer.Option(
            "message", "--type", help="Envelope message_type"
        ),
        workspace: Path | None = typer.Option(
            None, "--workspace", help="Workspace path override"
        ),
    ):
        async def _run():
            await _initialize_core_components_globally(workspace_override=workspace)
            coord = _get_coordinator()
            target = await coord.send_to_role(role, content, message_type=message_type)
            _console().print(f"Sent to role '{role}' agent: [cyan]{target}[/cyan]")

        asyncio.run(_run())

    @coord_app.command("broadcast")
    def coord_broadcast(
        roles: str = typer.Option(
            ..., "--roles", help="Comma-separated roles to broadcast to"
        ),
        content: str = typer.Argument(..., help="Message content"),
        message_type: str = typer.Option(
            "message", "--type", help="Envelope message_type"
        ),
        workspace: Path | None = typer.Option(
            None, "--workspace", help="Workspace path override"
        ),
    ):
        async def _run():
            await _initialize_core_components_globally(workspace_override=workspace)
            coord = _get_coordinator()
            role_list = [r.strip() for r in roles.split(",") if r.strip()]
            sent = await coord.broadcast(role_list, content, message_type=message_type)
            _console().print(
                f"Broadcast sent to: {', '.join(sent) if sent else '(none)'}"
            )

        asyncio.run(_run())

    @coord_app.command("rr-workflow")
    def coord_rr_workflow(
        role: str = typer.Option(..., "--role", "-r", help="Role to round-robin"),
        prompts: list[str] = typer.Argument(..., help="List of prompts"),
        workspace: Path | None = typer.Option(
            None, "--workspace", help="Workspace path override"
        ),
    ):
        async def _run():
            await _initialize_core_components_globally(workspace_override=workspace)
            coord = _get_coordinator()
            await coord.simple_round_robin_workflow(prompts, role=role)
            _console().print("[green]Round-robin workflow complete[/green]")

        asyncio.run(_run())

    @coord_app.command("role-chain")
    def coord_role_chain(
        roles: str = typer.Option(
            ...,
            "--roles",
            help="Comma-separated role chain (e.g., planner,researcher,implementer)",
        ),
        content: str = typer.Argument(..., help="Initial content"),
        workspace: Path | None = typer.Option(
            None, "--workspace", help="Workspace path override"
        ),
    ):
        async def _run():
            await _initialize_core_components_globally(workspace_override=workspace)
            coord = _get_coordinator()
            role_chain = [r.strip() for r in roles.split(",") if r.strip()]
            await coord.role_chain_workflow(content, roles=role_chain)
            _console().print("[green]Role-chain workflow complete[/green]")

        asyncio.run(_run())

    @msg_app.command("to-human")
    def msg_to_human(
        content: str = typer.Argument(..., help="Message content"),
        message_type: str = typer.Option(
            "status", "--type", help="Envelope message_type: message|action|status"
        ),
        workspace: Path | None = typer.Option(
            None, "--workspace", help="Workspace path override"
        ),
    ):
        """Send a message to the human recipient via MessageBus."""

        async def _run():
            await _initialize_core_components_globally(workspace_override=workspace)
            assert _core is not None
            ok = await _core.send_to_human(content, message_type=message_type)
            _console().print(f"[bold green]Sent[/bold green] to human: {ok}")

        asyncio.run(_run())

    @msg_app.command("human-reply")
    def msg_human_reply(
        agent_id: str = typer.Argument(..., help="Target agent id"),
        content: str = typer.Argument(..., help="Reply content"),
        message_type: str = typer.Option(
            "message", "--type", help="Envelope message_type"
        ),
        workspace: Path | None = typer.Option(
            None, "--workspace", help="Workspace path override"
        ),
    ):
        """Send a human reply to a specific agent (sender set to 'human')."""

        async def _run():
            await _initialize_core_components_globally(workspace_override=workspace)
            assert _core is not None
            ok = await _core.human_reply(agent_id, content, message_type=message_type)
            _console().print(
                f"[bold green]Human reply sent[/bold green] to {agent_id}: {ok}"
            )

        asyncio.run(_run())

    return {
        "msg_to_agent": msg_to_agent,
        "_get_coordinator": _get_coordinator,
        "coord_spawn": coord_spawn,
        "coord_destroy": coord_destroy,
        "coord_register": coord_register,
        "coord_send_role": coord_send_role,
        "coord_broadcast": coord_broadcast,
        "coord_rr_workflow": coord_rr_workflow,
        "coord_role_chain": coord_role_chain,
        "msg_to_human": msg_to_human,
        "msg_human_reply": msg_human_reply,
    }
