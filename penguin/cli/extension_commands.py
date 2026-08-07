"""Agent Skills and MCP command registration."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any, List, Optional

import typer
from rich.markdown import Markdown
from rich.panel import Panel

__all__ = ["bind_extension_commands"]


def bind_extension_commands(
    skill_app: typer.Typer,
    mcp_app: typer.Typer,
    get_skill_manager: Callable[[Optional[Path]], Awaitable[Any]],
    tool_manager_getter: Callable[[], Any],
    console: Any,
) -> dict[str, Callable[..., Any]]:
    """Register Skills/MCP commands and return compatibility exports."""

    async def _get_skill_manager_for_cli(workspace: Optional[Path] = None) -> Any:
        return await get_skill_manager(workspace)

    def _current_tool_manager() -> Any:
        return tool_manager_getter()

    def _print_skill_diagnostics(diagnostics: List[Any]) -> None:
        """Print skill diagnostics clearly for humans."""
        if not diagnostics:
            console.print("[green]✓ No invalid skill diagnostics.[/green]")
            return

        from rich.table import Table

        table = Table(title="Skill Diagnostics")
        table.add_column("Severity", style="bold")
        table.add_column("Code")
        table.add_column("Source")
        table.add_column("Path")
        table.add_column("Message")
        for diagnostic in diagnostics:
            severity = getattr(diagnostic, "severity", "unknown")
            color = "red" if severity == "error" else "yellow"
            table.add_row(
                f"[{color}]{severity}[/{color}]",
                str(getattr(diagnostic, "code", "")),
                str(getattr(diagnostic, "source", "")),
                str(getattr(diagnostic, "path", "")),
                str(getattr(diagnostic, "message", "")),
            )
        console.print(table)

    def _manual_skill_install_message() -> str:
        return (
            "Manual install: copy a skill folder containing SKILL.md into "
            "~/.penguin/skills/<skill-name>/ for user skills or "
            ".penguin/skills/<skill-name>/ for trusted project skills."
        )

    def _mcp_tool_manager() -> Any:
        """Create a lightweight ToolManager for MCP host diagnostics."""
        from penguin.config import load_config
        from penguin.tools.tool_manager import ToolManager

        loaded_config = load_config()
        return ToolManager(
            loaded_config, lambda *_args, **_kwargs: None, fast_startup=True
        )

    def _print_mcp_status(status: dict[str, Any], json_output: bool) -> None:
        """Print MCP host status in JSON or human-readable form."""
        if json_output:
            console.print(json.dumps(status, indent=2, sort_keys=True))
            return

        console.print(
            f"MCP SDK available: {status.get('available')} | "
            f"discovered: {status.get('discovered')} | "
            f"servers: {status.get('server_count', 0)} | "
            f"tools: {status.get('tool_count', 0)}"
        )
        for name, server in (status.get("servers") or {}).items():
            console.print(
                f"- {name}: {server.get('status')} "
                f"transport={server.get('transport')} "
                f"tools={server.get('tool_count', 0)}"
            )
            if server.get("error"):
                console.print(f"  error: {server['error']}")
            if server.get("list_changed"):
                console.print("  list changed: refresh recommended")

    @mcp_app.command("status")
    def mcp_status(
        refresh: bool = typer.Option(
            False, "--refresh", help="Refresh tools before status."
        ),
        json_output: bool = typer.Option(False, "--json", help="Output JSON."),
    ) -> None:
        """Show configured MCP server status and tool counts."""
        manager = _mcp_tool_manager()
        try:
            if refresh:
                manager.refresh_mcp_tools()
            _print_mcp_status(manager.get_mcp_status(), json_output)
        finally:
            manager.close_mcp()

    @mcp_app.command("refresh")
    def mcp_refresh(
        json_output: bool = typer.Option(False, "--json", help="Output JSON."),
    ) -> None:
        """Refresh discovered MCP tools for configured servers."""
        manager = _mcp_tool_manager()
        try:
            tools = manager.refresh_mcp_tools()
            status = manager.get_mcp_status()
            status["refreshed_tools"] = [tool.get("name") for tool in tools]
            _print_mcp_status(status, json_output)
        finally:
            manager.close_mcp()

    @mcp_app.command("reconnect")
    def mcp_reconnect(
        server: Optional[str] = typer.Argument(None, help="Optional MCP server name."),
        json_output: bool = typer.Option(False, "--json", help="Output JSON."),
    ) -> None:
        """Reconnect one MCP server or all servers."""
        manager = _mcp_tool_manager()
        try:
            status = manager.reconnect_mcp(server)
            _print_mcp_status(status, json_output)
        finally:
            manager.close_mcp()

    @mcp_app.command("close")
    def mcp_close(
        json_output: bool = typer.Option(False, "--json", help="Output JSON."),
    ) -> None:
        """Close active MCP client sessions."""
        manager = _mcp_tool_manager()
        status = manager.close_mcp()
        _print_mcp_status(status, json_output)

    @skill_app.command("list")
    def skill_list(
        json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
        workspace: Optional[Path] = typer.Option(
            None, "--workspace", help="Workspace path override"
        ),
    ):
        """List discovered Agent Skills."""

        async def _run() -> None:
            manager = await _get_skill_manager_for_cli(workspace)
            payload = manager.list_payload()
            if json_output:
                print(json.dumps(payload, indent=2))
                return

            from rich.table import Table

            skills = payload.get("skills", [])
            if not skills:
                console.print("[yellow]No skills discovered.[/yellow]")
                console.print(f"[dim]{_manual_skill_install_message()}[/dim]")
            else:
                table = Table(title="Agent Skills")
                table.add_column("Name", style="cyan")
                table.add_column("Source")
                table.add_column("Description")
                table.add_column("Path", style="dim")
                for skill in skills:
                    table.add_row(
                        str(skill.get("name", "")),
                        str(skill.get("source", "")),
                        str(skill.get("description", "")),
                        str(skill.get("path", "")),
                    )
                console.print(table)

            diagnostics = payload.get("diagnostics", [])
            if diagnostics:
                console.print(
                    f"[yellow]{len(diagnostics)} invalid skill diagnostic(s). Run `penguin skill doctor` for details.[/yellow]"
                )

        asyncio.run(_run())

    @skill_app.command("show")
    def skill_show(
        name: str = typer.Argument(..., help="Skill name"),
        json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
        workspace: Optional[Path] = typer.Option(
            None, "--workspace", help="Workspace path override"
        ),
    ):
        """Show full SKILL.md instructions for a discovered skill."""

        async def _run() -> None:
            manager = await _get_skill_manager_for_cli(workspace)
            skill = manager.get(name)
            if skill is None:
                available = [entry.name for entry in manager.catalog()]
                if json_output:
                    print(
                        json.dumps(
                            {
                                "error": f"Skill not found: {name}",
                                "available_skills": available,
                            },
                            indent=2,
                        )
                    )
                else:
                    console.print(f"[red]Skill not found:[/red] {name}")
                    if available:
                        console.print(f"[dim]Available: {', '.join(available)}[/dim]")
                raise typer.Exit(code=1)

            payload = {
                "name": skill.name,
                "description": skill.description,
                "source": skill.source,
                "path": str(skill.path),
                "skill_file": str(skill.skill_file),
                "allowed_tools": skill.allowed_tools,
                "frontmatter": skill.frontmatter,
                "body": skill.body,
            }
            if json_output:
                print(json.dumps(payload, indent=2))
                return

            console.print(
                Panel(
                    Markdown(skill.body or "_No body content._"),
                    title=f"Skill: {skill.name}",
                    subtitle=f"{skill.source} · {skill.path}",
                    border_style="cyan",
                )
            )
            console.print(f"[bold]Description:[/bold] {skill.description}")
            if skill.allowed_tools:
                console.print(
                    f"[bold]Allowed tools hint:[/bold] {', '.join(skill.allowed_tools)}"
                )

        asyncio.run(_run())

    @skill_app.command("activate")
    def skill_activate(
        name: str = typer.Argument(..., help="Skill name"),
        json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
        show_content: bool = typer.Option(
            False, "--show-content", help="Print rendered activation content"
        ),
        workspace: Optional[Path] = typer.Option(
            None, "--workspace", help="Workspace path override"
        ),
    ):
        """Activate a skill and load it into the current session as CONTEXT."""

        async def _run() -> None:
            await _get_skill_manager_for_cli(workspace)
            skill_tools = (
                getattr(_current_tool_manager(), "skill_tools", None)
                if _current_tool_manager() is not None
                else None
            )
            if skill_tools is None:
                console.print("[red]Error: Skill tools not available[/red]")
                raise typer.Exit(code=1)

            result = json.loads(skill_tools.activate_skill(name))
            if json_output:
                print(json.dumps(result, indent=2))
                return

            status = result.get("status")
            if status == "not_found":
                console.print(f"[red]{result.get('error', 'Skill not found')}[/red]")
                available = result.get("available_skills", [])
                if available:
                    console.print(f"[dim]Available: {', '.join(available)}[/dim]")
                raise typer.Exit(code=1)

            skill = result.get("skill", {})
            duplicate = bool(result.get("duplicate"))
            verb = "Already active" if duplicate else "Activated"
            console.print(f"[green]✓ {verb} skill:[/green] {skill.get('name', name)}")
            console.print(
                "[dim]Activation content is loaded as a MessageCategory.CONTEXT message for this runtime session.[/dim]"
            )
            console.print(f"[dim]Path: {skill.get('path', '')}[/dim]")
            if show_content:
                console.print(
                    Panel(
                        result.get("content", ""),
                        title="Activation Content",
                        border_style="cyan",
                    )
                )

        asyncio.run(_run())

    @skill_app.command("doctor")
    def skill_doctor(
        json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
        workspace: Optional[Path] = typer.Option(
            None, "--workspace", help="Workspace path override"
        ),
    ):
        """Validate discovered skill directories and show install guidance."""

        async def _run() -> None:
            manager = await _get_skill_manager_for_cli(workspace)
            payload = manager.list_payload()
            diagnostics = manager.diagnostics
            if json_output:
                print(json.dumps(payload, indent=2))
                return

            console.print("[bold cyan]Agent Skills Doctor[/bold cyan]")
            console.print(
                f"Discovered valid skills: [bold]{len(payload.get('skills', []))}[/bold]"
            )
            _print_skill_diagnostics(diagnostics)
            console.print(f"[dim]{_manual_skill_install_message()}[/dim]")
            console.print(
                "[dim]Project skills are ignored unless project skill trust is enabled in config.[/dim]"
            )

        asyncio.run(_run())

    return {
        "mcp_status": mcp_status,
        "mcp_refresh": mcp_refresh,
        "mcp_reconnect": mcp_reconnect,
        "mcp_close": mcp_close,
        "skill_list": skill_list,
        "skill_show": skill_show,
        "skill_activate": skill_activate,
        "skill_doctor": skill_doctor,
    }
