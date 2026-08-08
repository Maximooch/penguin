"""Agent-management command registration and execution."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any, Dict, List, Optional

import typer

__all__ = ["bind_agent_commands"]


Initialize = Callable[..., Awaitable[None]]


def bind_agent_commands(
    agent_app: typer.Typer,
    initialize: Initialize,
    core_getter: Callable[[], Any],
    console: Any,
) -> dict[str, Callable[..., Any]]:
    """Register agent commands and return compatibility exports."""

    _core: Any = None

    async def _initialize_core_components_globally(**kwargs: Any) -> None:
        nonlocal _core
        await initialize(**kwargs)
        _core = core_getter()

    @agent_app.command("personas")
    def agent_personas(
        json_output: bool = typer.Option(
            False, "--json", help="Emit persona catalog as JSON"
        ),
        workspace: Optional[Path] = typer.Option(
            None, "--workspace", help="Workspace path override"
        ),
    ):
        """List configured agent personas."""

        async def _run() -> None:
            await _initialize_core_components_globally(workspace_override=workspace)
            if not _core:
                console.print("[red]Core not initialized[/red]")
                raise typer.Exit(code=1)

            personas = _core.get_persona_catalog()
            if json_output:
                console.print(json.dumps(personas, indent=2))
                return

            if not personas:
                console.print(
                    "[yellow]No personas defined. Add entries under 'agents:' in config.yml.[/yellow]"
                )
                return

            from rich.table import Table

            table = Table(show_header=True, header_style="bold magenta")
            table.add_column("Persona", style="cyan")
            table.add_column("Description", style="white")
            table.add_column("Model", style="green")
            table.add_column("Tools", style="magenta")
            table.add_column("Auto-Activate", style="yellow")

            for entry in personas:
                name = entry.get("name", "--")
                description = entry.get("description") or ""
                model_block = entry.get("model") or {}
                model_label = (
                    model_block.get("model") or model_block.get("id") or "(default)"
                )
                tools = entry.get("default_tools") or entry.get("tools") or []
                if isinstance(tools, str):
                    tools = [tools]
                tools_label = ", ".join(tools) if tools else "--"
                auto_activate = "yes" if entry.get("activate", False) else "no"
                table.add_row(
                    name, description, model_label, tools_label, auto_activate
                )

            console.print(table)

        asyncio.run(_run())

    @agent_app.command("list")
    def agent_list(
        json_output: bool = typer.Option(
            False, "--json", help="Emit agent roster as JSON"
        ),
        workspace: Optional[Path] = typer.Option(
            None, "--workspace", help="Workspace path override"
        ),
    ):
        """List registered agents and sub-agents."""

        async def _run() -> None:
            await _initialize_core_components_globally(workspace_override=workspace)
            if not _core:
                console.print("[red]Core not initialized[/red]")
                raise typer.Exit(code=1)

            roster = _core.get_agent_roster()
            if json_output:
                console.print(json.dumps(roster, indent=2))
                return

            if not roster:
                console.print("[yellow]No agents are currently registered.[/yellow]")
                return

            from rich.table import Table

            table = Table(show_header=True, header_style="bold magenta")
            table.add_column("Agent", style="cyan")
            table.add_column("Type", style="white")
            table.add_column("Persona", style="green")
            table.add_column("Model", style="white")
            table.add_column("Parent", style="yellow")
            table.add_column("Children", style="dim")
            table.add_column("Tools", style="magenta")
            table.add_column("Active", style="blue")
            table.add_column("Paused", style="yellow")

            for entry in roster:
                agent_id = entry.get("id", "--")
                agent_type = "sub" if entry.get("is_sub_agent") else "primary"
                persona_label = entry.get("persona") or "--"
                model_info = entry.get("model") or {}
                model_label = model_info.get("model") or "(default)"
                parent = entry.get("parent") or "--"
                children = entry.get("children") or []
                children_label = ", ".join(children) if children else "--"
                tools = entry.get("default_tools") or []
                tools_label = ", ".join(tools[:3]) if tools else "--"
                if len(tools) > 3:
                    tools_label += ", …"
                active_label = "yes" if entry.get("active") else ""
                paused_label = "yes" if entry.get("paused") else ""
                style = "bold" if entry.get("active") else None
                table.add_row(
                    agent_id,
                    agent_type,
                    persona_label,
                    model_label,
                    parent,
                    children_label,
                    tools_label,
                    active_label,
                    paused_label,
                    style=style,
                )

            console.print(table)

        asyncio.run(_run())

    @agent_app.command("spawn")
    def agent_spawn(
        agent_id: str = typer.Argument(..., help="New agent identifier"),
        persona: Optional[str] = typer.Option(
            None, "--persona", "-p", help="Persona id from config to apply"
        ),
        system_prompt: Optional[str] = typer.Option(
            None, "--system-prompt", "-s", help="Override system prompt"
        ),
        parent_agent_id: Optional[str] = typer.Option(
            None, "--parent", "-P", help="Parent agent id to share session with"
        ),
        share_session: bool = typer.Option(
            True,
            "--share-session/--isolate-session",
            help="Share conversation session with parent",
        ),
        share_context_window: bool = typer.Option(
            True,
            "--share-context/--isolate-context",
            help="Share context window with parent",
        ),
        shared_context_window_max_tokens: Optional[int] = typer.Option(
            None, "--shared-cw-max", help="Clamp shared context window tokens"
        ),
        model_output_max_tokens: Optional[int] = typer.Option(
            None, "--model-max-tokens", help="Clamp agent context window tokens"
        ),
        model_config_id: Optional[str] = typer.Option(
            None, "--model-id", help="Model config id override"
        ),
        default_tools: Optional[List[str]] = typer.Option(
            None,
            "--tool",
            "-t",
            help="Restrict tools available to the agent (repeatable)",
        ),
        activate: bool = typer.Option(
            False, "--activate/--no-activate", help="Make this agent active"
        ),
        workspace: Optional[Path] = typer.Option(
            None, "--workspace", help="Workspace path override"
        ),
    ):
        """Register a new agent or sub-agent."""

        async def _run() -> None:
            await _initialize_core_components_globally(workspace_override=workspace)
            if not _core:
                console.print("[red]Core not initialized[/red]")
                raise typer.Exit(code=1)

            personas = {
                entry.get("name"): entry for entry in _core.get_persona_catalog()
            }
            if persona and persona not in personas:
                console.print(
                    f"[red]Persona '{persona}' not found in configuration.[/red]"
                )
                raise typer.Exit(code=1)

            model_configs = getattr(_core.config, "model_configs", {}) or {}
            if model_config_id and model_config_id not in model_configs:
                console.print(
                    f"[red]Model id '{model_config_id}' not found in configuration.[/red]"
                )
                raise typer.Exit(code=1)

            try:
                if parent_agent_id:
                    _core.create_sub_agent(
                        agent_id,
                        parent_agent_id=parent_agent_id,
                        system_prompt=system_prompt,
                        share_session=share_session,
                        share_context_window=share_context_window,
                        shared_context_window_max_tokens=shared_context_window_max_tokens,
                    )
                else:
                    _core.ensure_agent_conversation(
                        agent_id, system_prompt=system_prompt
                    )

                # Store persona in conversation metadata if specified
                if persona:
                    conv = _core.conversation_manager.get_agent_conversation(agent_id)
                    if conv and hasattr(conv, "session") and conv.session:
                        conv.session.metadata["persona"] = persona

                if activate:
                    _core.set_active_agent(agent_id)

                console.print(
                    f"[green]Registered agent[/green] {agent_id}{f' using persona {persona}' if persona else ''}."
                )
            except Exception as exc:
                console.print(f"[red]Failed to register agent: {exc}[/red]")
                raise typer.Exit(code=1)

        asyncio.run(_run())

    @agent_app.command("set-persona")
    def agent_set_persona(
        agent_id: str = typer.Argument(..., help="Existing agent identifier"),
        persona: str = typer.Argument(..., help="Persona id to apply"),
        activate: bool = typer.Option(
            False,
            "--activate/--no-activate",
            help="Make this agent active after switching",
        ),
        system_prompt: Optional[str] = typer.Option(
            None, "--system-prompt", "-s", help="Override system prompt"
        ),
        model_config_id: Optional[str] = typer.Option(
            None, "--model-id", help="Model config id override"
        ),
        default_tools: Optional[List[str]] = typer.Option(
            None, "--tool", "-t", help="Override default tools (repeatable)"
        ),
        workspace: Optional[Path] = typer.Option(
            None, "--workspace", help="Workspace path override"
        ),
    ):
        """Apply a persona to an existing agent."""

        async def _run() -> None:
            await _initialize_core_components_globally(workspace_override=workspace)
            if not _core:
                console.print("[red]Core not initialized[/red]")
                raise typer.Exit(code=1)

            personas = {
                entry.get("name"): entry for entry in _core.get_persona_catalog()
            }
            if persona not in personas:
                console.print(
                    f"[red]Persona '{persona}' not found in configuration.[/red]"
                )
                raise typer.Exit(code=1)

            model_configs = getattr(_core.config, "model_configs", {}) or {}
            if model_config_id and model_config_id not in model_configs:
                console.print(
                    f"[red]Model id '{model_config_id}' not found in configuration.[/red]"
                )
                raise typer.Exit(code=1)

            parent_map = (
                getattr(_core.conversation_manager, "sub_agent_parent", {}) or {}
            )
            parent = parent_map.get(agent_id)

            try:
                if parent:
                    _core.create_sub_agent(
                        agent_id,
                        parent_agent_id=parent,
                        system_prompt=system_prompt,
                    )
                else:
                    _core.ensure_agent_conversation(
                        agent_id, system_prompt=system_prompt
                    )

                # Store persona in conversation metadata
                conv = _core.conversation_manager.get_agent_conversation(agent_id)
                if conv and hasattr(conv, "session") and conv.session:
                    conv.session.metadata["persona"] = persona

                if activate:
                    _core.set_active_agent(agent_id)

                console.print(
                    f"[green]Applied persona[/green] {persona} to agent {agent_id}."
                )
            except Exception as exc:
                console.print(f"[red]Failed to apply persona: {exc}[/red]")
                raise typer.Exit(code=1)

        asyncio.run(_run())

    @agent_app.command("pause")
    def agent_pause(
        agent_id: str = typer.Argument(..., help="Agent identifier to pause"),
        workspace: Optional[Path] = typer.Option(
            None, "--workspace", help="Workspace path override"
        ),
    ):
        """Pause an agent (sub-agent) – stops engine-driven actions, messages still log."""

        async def _run() -> None:
            await _initialize_core_components_globally(workspace_override=workspace)
            if not _core:
                console.print("[red]Core not initialized[/red]")
                raise typer.Exit(code=1)
            try:
                _core.set_agent_paused(agent_id, True)
                console.print(f"[yellow]Paused[/yellow] agent {agent_id}.")
            except Exception as exc:
                console.print(f"[red]Failed to pause agent: {exc}[/red]")
                raise typer.Exit(code=1)

        asyncio.run(_run())

    @agent_app.command("resume")
    def agent_resume(
        agent_id: str = typer.Argument(..., help="Agent identifier to resume"),
        workspace: Optional[Path] = typer.Option(
            None, "--workspace", help="Workspace path override"
        ),
    ):
        """Resume a paused agent."""

        async def _run() -> None:
            await _initialize_core_components_globally(workspace_override=workspace)
            if not _core:
                console.print("[red]Core not initialized[/red]")
                raise typer.Exit(code=1)
            try:
                _core.set_agent_paused(agent_id, False)
                console.print(f"[green]Resumed[/green] agent {agent_id}.")
            except Exception as exc:
                console.print(f"[red]Failed to resume agent: {exc}[/red]")
                raise typer.Exit(code=1)

        asyncio.run(_run())

    @agent_app.command("activate")
    def agent_activate(
        agent_id: str = typer.Argument(..., help="Agent identifier"),
        workspace: Optional[Path] = typer.Option(
            None, "--workspace", help="Workspace path override"
        ),
    ):
        """Set the active agent for subsequent operations."""

        async def _run() -> None:
            await _initialize_core_components_globally(workspace_override=workspace)
            if not _core:
                console.print("[red]Core not initialized[/red]")
                raise typer.Exit(code=1)

            try:
                _core.set_active_agent(agent_id)
                console.print(f"[green]Active agent set to[/green] {agent_id}")
            except Exception as exc:
                console.print(f"[red]Failed to activate agent: {exc}[/red]")
                raise typer.Exit(code=1)

        asyncio.run(_run())

    @agent_app.command("status")
    def agent_status(
        agent_id: Optional[str] = typer.Argument(
            None, help="Agent identifier (omit for all agents)"
        ),
        json_output: bool = typer.Option(False, "--json", help="Emit status as JSON"),
        watch: bool = typer.Option(
            False, "--watch", "-w", help="Watch mode: refresh every 2 seconds"
        ),
        workspace: Optional[Path] = typer.Option(
            None, "--workspace", help="Workspace path override"
        ),
    ):
        """Show background task status for agents.

        Displays the execution state of background agents spawned via
        spawn_sub_agent(background=True) or delegate(background=True).

        States: PENDING, RUNNING, PAUSED, COMPLETED, FAILED, CANCELLED
        """
        from rich.table import Table
        from rich.live import Live

        async def _run() -> None:
            await _initialize_core_components_globally(workspace_override=workspace)
            if not _core:
                console.print("[red]Core not initialized[/red]")
                raise typer.Exit(code=1)

            try:
                from penguin.multi.executor import get_executor

                executor = get_executor()
            except ImportError:
                executor = None

            def get_status_data():
                """Gather status data from executor and conversation manager."""
                data = []

                # Get executor status if available
                executor_status = {}
                if executor:
                    executor_status = executor.get_all_status()

                # Get agent roster from core
                roster = _core.get_agent_roster()

                for entry in roster:
                    aid = entry.get("id", "--")
                    if agent_id and aid != agent_id:
                        continue

                    exec_info = executor_status.get(aid, {})
                    state = exec_info.get("state", "IDLE")
                    result_preview = ""
                    error = exec_info.get("error", "")

                    if exec_info.get("result"):
                        result_preview = str(exec_info["result"])[:50]
                        if len(str(exec_info["result"])) > 50:
                            result_preview += "..."

                    data.append(
                        {
                            "id": aid,
                            "state": state,
                            "active": entry.get("active", False),
                            "paused": entry.get("paused", False),
                            "parent": entry.get("parent") or "--",
                            "result_preview": result_preview,
                            "error": error[:50] if error else "",
                        }
                    )

                return data

            def render_table(data):
                """Render status as a Rich table."""
                table = Table(
                    title="Agent Status", show_header=True, header_style="bold magenta"
                )
                table.add_column("Agent", style="cyan")
                table.add_column("State", style="bold")
                table.add_column("Active", style="green")
                table.add_column("Paused", style="yellow")
                table.add_column("Parent", style="dim")
                table.add_column("Result/Error", max_width=50)

                state_colors = {
                    "PENDING": "dim",
                    "RUNNING": "blue",
                    "PAUSED": "yellow",
                    "COMPLETED": "green",
                    "FAILED": "red",
                    "CANCELLED": "dim red",
                    "IDLE": "dim",
                }

                for row in data:
                    state = row["state"]
                    state_color = state_colors.get(state, "white")

                    result_or_error = (
                        row["error"] if row["error"] else row["result_preview"]
                    )
                    if row["error"]:
                        result_or_error = f"[red]{result_or_error}[/red]"

                    table.add_row(
                        row["id"],
                        f"[{state_color}]{state}[/{state_color}]",
                        "✓" if row["active"] else "",
                        "⏸" if row["paused"] else "",
                        row["parent"],
                        result_or_error or "--",
                    )

                return table

            if json_output:
                data = get_status_data()
                console.print(json.dumps(data, indent=2))
                return

            if watch:
                with Live(
                    render_table(get_status_data()),
                    refresh_per_second=0.5,
                    console=console,
                ) as live:
                    import time as time_module

                    try:
                        while True:
                            time_module.sleep(2)
                            live.update(render_table(get_status_data()))
                    except KeyboardInterrupt:
                        pass
            else:
                data = get_status_data()
                if not data:
                    console.print("[yellow]No agents found.[/yellow]")
                    return
                console.print(render_table(data))

        asyncio.run(_run())

    @agent_app.command("tree")
    def agent_tree(
        json_output: bool = typer.Option(False, "--json", help="Emit tree as JSON"),
        workspace: Optional[Path] = typer.Option(
            None, "--workspace", help="Workspace path override"
        ),
    ):
        """Show agent hierarchy with context sharing relationships.

        Displays a tree view of agents showing:
        - Parent/child relationships
        - Context sharing status (shared vs isolated)
        - Current execution state
        """
        from rich.tree import Tree

        async def _run() -> None:
            await _initialize_core_components_globally(workspace_override=workspace)
            if not _core:
                console.print("[red]Core not initialized[/red]")
                raise typer.Exit(code=1)

            roster = _core.get_agent_roster()
            if not roster:
                console.print("[yellow]No agents found.[/yellow]")
                return

            # Build parent->children map
            children_map: Dict[str, List[str]] = {}
            parent_map: Dict[str, Optional[str]] = {}
            agent_info: Dict[str, Dict] = {}

            for entry in roster:
                aid = entry.get("id", "")
                parent = entry.get("parent")
                agent_info[aid] = entry
                parent_map[aid] = parent

                if parent:
                    if parent not in children_map:
                        children_map[parent] = []
                    children_map[parent].append(aid)

            # Get context sharing info from conversation manager
            cm = _core.conversation_manager
            sharing_info: Dict[str, Dict] = {}
            for aid in agent_info:
                try:
                    sharing_info[aid] = cm.get_context_sharing_info(aid)
                except Exception:
                    sharing_info[aid] = {}

            if json_output:
                output = {
                    "agents": agent_info,
                    "hierarchy": children_map,
                    "context_sharing": sharing_info,
                }
                console.print(json.dumps(output, indent=2))
                return

            # Find root agents (no parent)
            roots = [aid for aid, parent in parent_map.items() if not parent]
            if not roots:
                roots = list(agent_info.keys())[:1]  # Fallback

            def build_branch(tree_node, agent_id: str):
                """Recursively build tree branches."""
                info = agent_info.get(agent_id, {})
                share_info = sharing_info.get(agent_id, {})

                # Build label with status indicators
                state_icon = ""
                if info.get("active"):
                    state_icon = " [green]●[/green]"
                elif info.get("paused"):
                    state_icon = " [yellow]⏸[/yellow]"

                # Context sharing indicator
                shares_with_parent = share_info.get("shares_with_parent", False)
                context_icon = (
                    " [cyan]⟷[/cyan]" if shares_with_parent else " [dim]○[/dim]"
                )

                label = f"[bold]{agent_id}[/bold]{state_icon}{context_icon}"

                # Add children
                for child_id in children_map.get(agent_id, []):
                    tree_node.add(label if tree_node == tree else "")
                    build_branch(
                        tree_node.add(
                            f"[bold]{child_id}[/bold]"
                            + (
                                " [green]●[/green]"
                                if agent_info.get(child_id, {}).get("active")
                                else ""
                            )
                            + (
                                " [yellow]⏸[/yellow]"
                                if agent_info.get(child_id, {}).get("paused")
                                else ""
                            )
                            + (
                                " [cyan]⟷[/cyan]"
                                if sharing_info.get(child_id, {}).get(
                                    "shares_with_parent"
                                )
                                else " [dim]○[/dim]"
                            )
                        ),
                        child_id,
                    )

            # Build the tree
            tree = Tree("[bold cyan]🐧 Agent Hierarchy[/bold cyan]")

            for root_id in roots:
                info = agent_info.get(root_id, {})
                state_icon = ""
                if info.get("active"):
                    state_icon = " [green]●[/green]"
                elif info.get("paused"):
                    state_icon = " [yellow]⏸[/yellow]"

                root_branch = tree.add(f"[bold]{root_id}[/bold]{state_icon}")

                for child_id in children_map.get(root_id, []):
                    child_info = agent_info.get(child_id, {})
                    child_share = sharing_info.get(child_id, {})

                    child_state = ""
                    if child_info.get("active"):
                        child_state = " [green]●[/green]"
                    elif child_info.get("paused"):
                        child_state = " [yellow]⏸[/yellow]"

                    context_icon = (
                        " [cyan]⟷[/cyan]"
                        if child_share.get("shares_with_parent")
                        else " [dim]○[/dim]"
                    )

                    child_branch = root_branch.add(
                        f"{child_id}{child_state}{context_icon}"
                    )

                    # Add grandchildren
                    for grandchild_id in children_map.get(child_id, []):
                        gc_info = agent_info.get(grandchild_id, {})
                        gc_share = sharing_info.get(grandchild_id, {})
                        gc_state = ""
                        if gc_info.get("active"):
                            gc_state = " [green]●[/green]"
                        elif gc_info.get("paused"):
                            gc_state = " [yellow]⏸[/yellow]"
                        gc_context = (
                            " [cyan]⟷[/cyan]"
                            if gc_share.get("shares_with_parent")
                            else " [dim]○[/dim]"
                        )
                        child_branch.add(f"{grandchild_id}{gc_state}{gc_context}")

            console.print(tree)
            console.print(
                "\n[dim]Legend: ● active  ⏸ paused  ⟷ shares context  ○ isolated[/dim]"
            )

        asyncio.run(_run())

    @agent_app.command("tasks")
    def agent_tasks(
        json_output: bool = typer.Option(False, "--json", help="Emit tasks as JSON"),
        watch: bool = typer.Option(
            False, "--watch", "-w", help="Watch mode: refresh every 2 seconds"
        ),
        workspace: Optional[Path] = typer.Option(
            None, "--workspace", help="Workspace path override"
        ),
    ):
        """Show all background agent tasks and their states.

        Displays tasks spawned with background=True, including:
        - Current state (PENDING, RUNNING, COMPLETED, FAILED, CANCELLED)
        - Elapsed time for running tasks
        - Results or errors for completed/failed tasks
        """
        from rich.table import Table
        from rich.live import Live

        async def _run() -> None:
            await _initialize_core_components_globally(workspace_override=workspace)
            if not _core:
                console.print("[red]Core not initialized[/red]")
                raise typer.Exit(code=1)

            try:
                from penguin.multi.executor import get_executor

                executor = get_executor()
            except ImportError:
                executor = None

            def get_tasks_data():
                """Gather all task data from executor."""
                if not executor:
                    return []

                all_status = executor.get_all_status()
                stats = executor.get_stats()

                data = []
                for agent_id, status in all_status.items():
                    data.append(
                        {
                            "agent_id": agent_id,
                            "state": status.get("state", "UNKNOWN"),
                            "result": status.get("result"),
                            "error": status.get("error"),
                            "metadata": status.get("metadata", {}),
                        }
                    )

                return data, stats

            def render_table(data, stats):
                """Render tasks as a Rich table."""
                table = Table(
                    title="Background Agent Tasks",
                    show_header=True,
                    header_style="bold magenta",
                )
                table.add_column("Agent ID", style="cyan")
                table.add_column("State", style="bold")
                table.add_column("Result/Error", max_width=60)

                state_colors = {
                    "PENDING": "dim",
                    "RUNNING": "blue",
                    "PAUSED": "yellow",
                    "COMPLETED": "green",
                    "FAILED": "red",
                    "CANCELLED": "dim red",
                }

                for row in data:
                    state = row["state"]
                    state_color = state_colors.get(state, "white")

                    result_or_error = ""
                    if row["error"]:
                        result_or_error = f"[red]{str(row['error'])[:60]}[/red]"
                    elif row["result"]:
                        result_or_error = str(row["result"])[:60]
                        if len(str(row["result"])) > 60:
                            result_or_error += "..."

                    table.add_row(
                        row["agent_id"],
                        f"[{state_color}]{state}[/{state_color}]",
                        result_or_error or "--",
                    )

                return table

            if not executor:
                console.print(
                    "[yellow]AgentExecutor not initialized. No background tasks available.[/yellow]"
                )
                console.print(
                    "[dim]Background tasks are created when using spawn_sub_agent(background=True)[/dim]"
                )
                return

            if json_output:
                data, stats = get_tasks_data()
                console.print(json.dumps({"tasks": data, "stats": stats}, indent=2))
                return

            if watch:
                with Live(console=console, refresh_per_second=0.5) as live:
                    import time as time_module

                    try:
                        while True:
                            data, stats = get_tasks_data()
                            if data:
                                table = render_table(data, stats)
                                stats_line = f"\n[dim]Running: {stats['running']} | Completed: {stats['completed']} | Failed: {stats['failed']} | Concurrent limit: {stats['max_concurrent']}[/dim]"
                                from rich.console import Group

                                live.update(Group(table, stats_line))
                            else:
                                live.update("[dim]No background tasks running.[/dim]")
                            time_module.sleep(2)
                    except KeyboardInterrupt:
                        pass
            else:
                data, stats = get_tasks_data()
                if not data:
                    console.print("[dim]No background tasks.[/dim]")
                    return
                console.print(render_table(data, stats))
                console.print(
                    f"\n[dim]Running: {stats['running']} | Completed: {stats['completed']} | Failed: {stats['failed']} | Concurrent limit: {stats['max_concurrent']}[/dim]"
                )

        asyncio.run(_run())

    @agent_app.command("info")
    def agent_info(
        agent_id: str = typer.Argument(..., help="Agent identifier"),
        json_output: bool = typer.Option(False, "--json", help="Emit profile as JSON"),
        workspace: Optional[Path] = typer.Option(
            None, "--workspace", help="Workspace path override"
        ),
    ):
        """Show detailed information for an agent."""

        async def _run() -> None:
            await _initialize_core_components_globally(workspace_override=workspace)
            if not _core:
                console.print("[red]Core not initialized[/red]")
                raise typer.Exit(code=1)

            profile = _core.get_agent_profile(agent_id)
            if not profile:
                console.print(f"[yellow]Agent '{agent_id}' not found.[/yellow]")
                raise typer.Exit(code=1)

            if json_output:
                console.print(json.dumps(profile, indent=2))
                return

            from rich.table import Table

            table = Table(show_header=False)
            for key in (
                "id",
                "persona",
                "persona_description",
                "model",
                "parent",
                "children",
                "default_tools",
                "active",
                "is_sub_agent",
                "system_prompt_preview",
            ):
                value = profile.get(key)
                if key == "model" and isinstance(value, dict):
                    value = ", ".join(
                        f"{k}={v}" for k, v in value.items() if v is not None
                    )
                if key == "children" and isinstance(value, list):
                    value = ", ".join(value) if value else "--"
                if key == "default_tools" and isinstance(value, list):
                    value = ", ".join(value) if value else "--"
                if key == "active":
                    value = "yes" if value else "no"
                if key == "is_sub_agent":
                    value = "yes" if value else "no"
                if value is None or value == "":
                    value = "--"
                table.add_row(key.replace("_", " ").title(), str(value))

            console.print(table)

        asyncio.run(_run())

    # Project Management Commands

    return {
        "agent_personas": agent_personas,
        "agent_list": agent_list,
        "agent_spawn": agent_spawn,
        "agent_set_persona": agent_set_persona,
        "agent_pause": agent_pause,
        "agent_resume": agent_resume,
        "agent_activate": agent_activate,
        "agent_status": agent_status,
        "agent_tree": agent_tree,
        "agent_tasks": agent_tasks,
        "agent_info": agent_info,
    }
