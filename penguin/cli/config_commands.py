"""Configuration and permission command registration."""

from __future__ import annotations

import json
import os
import platform
import sys
import traceback
from collections.abc import Callable
from typing import Any, Optional

import typer

__all__ = ["bind_config_commands"]


def bind_config_commands(
    config_app: typer.Typer,
    permissions_app: typer.Typer,
    console: Any,
    *,
    setup_available: bool,
    setup_import_error: str | None,
    run_setup_wizard_sync: Callable[[], dict[str, Any]],
    check_config_completeness: Callable[[], bool],
    check_first_run: Callable[[], bool],
) -> dict[str, Callable[..., Any]]:
    """Register config/security commands and return compatibility exports."""

    @config_app.command("setup")
    def config_setup():
        """Run the setup wizard to configure Penguin"""
        console.print("[bold cyan]🐧 Penguin Setup Wizard[/bold cyan]")
        console.print("Configuring your Penguin environment...\n")

        if not setup_available:
            console.print(
                f"[red]Setup wizard not available: {setup_import_error}[/red]"
            )
            console.print(
                "[yellow]You may need to install additional dependencies:[/yellow]"
            )
            console.print("[yellow]  pip install questionary PyYAML rich[/yellow]")
            console.print("[yellow]Or install with setup extras:[/yellow]")
            console.print("[yellow]  pip install penguin-ai[/yellow]")
            raise typer.Exit(code=1)

        try:
            config_result = run_setup_wizard_sync()
            if config_result:
                if "error" in config_result:
                    console.print(f"[red]Setup error: {config_result['error']}[/red]")
                    if "Missing dependencies" in config_result["error"]:
                        console.print(
                            "[yellow]Please install the missing dependencies and try again.[/yellow]"
                        )
                    raise typer.Exit(code=1)
                else:
                    console.print(
                        "[bold green]Setup completed successfully![/bold green]"
                    )
            else:
                console.print("[yellow]Setup was cancelled.[/yellow]")
                raise typer.Exit(code=0)
        except KeyboardInterrupt:
            console.print("\n[yellow]Setup interrupted.[/yellow]")
            raise typer.Exit(code=0)
        except Exception as e:
            console.print(f"[red]Setup failed: {e}[/red]")
            console.print(f"[dim]Error details: {traceback.format_exc()}[/dim]")
            raise typer.Exit(code=1)

    @config_app.command("edit")
    def config_edit():
        """Open the config file in your default editor"""
        from penguin.setup.wizard import get_config_path, open_in_default_editor

        config_path = get_config_path()
        if not config_path.exists():
            console.print(f"[red]Config file not found at {config_path}[/red]")
            console.print("Run 'penguin config setup' to create initial configuration.")
            raise typer.Exit(code=1)

        if open_in_default_editor(config_path):
            console.print(f"[green]✓ Opened config file:[/green] {config_path}")
        else:
            console.print(
                f"[yellow]Could not open editor. Config file is located at:[/yellow] {config_path}"
            )

    @config_app.command("check")
    def config_check():
        """Check if the current configuration is complete and valid"""
        if check_config_completeness():
            console.print("[green]✓ Configuration is complete and valid![/green]")
        else:
            console.print("[yellow]⚠️ Configuration is incomplete or invalid.[/yellow]")
            console.print("Run 'penguin config setup' to fix configuration issues.")
            raise typer.Exit(code=1)

    @config_app.command("test-routing")
    def config_test_routing():
        """Test the provider routing logic for model selection"""
        if not setup_available:
            console.print(
                f"[red]Setup wizard not available: {setup_import_error}[/red]"
            )
            console.print(
                "[yellow]Install setup dependencies first: pip install questionary PyYAML rich[/yellow]"
            )
            raise typer.Exit(code=1)

        try:
            from penguin.setup.wizard import test_provider_routing

            test_provider_routing()
        except Exception as e:
            console.print(f"[red]Error running provider routing test: {e}[/red]")
            console.print(f"[dim]Error details: {traceback.format_exc()}[/dim]")
            raise typer.Exit(code=1)

    @config_app.command("debug")
    def config_debug():
        """Debug configuration and setup issues"""
        console.print("[bold cyan]🔍 Penguin Configuration Debug[/bold cyan]\n")

        # Check setup availability
        console.print("[bold]Setup Wizard Status:[/bold]")
        if setup_available:
            console.print("  ✓ Setup wizard available")

            # Check individual dependencies
            try:
                from penguin.setup.wizard import check_setup_dependencies

                deps_ok, missing = check_setup_dependencies()
                if deps_ok:
                    console.print("  ✓ All setup dependencies available")
                else:
                    console.print(f"  ⚠️ Missing dependencies: {', '.join(missing)}")
            except Exception as e:
                console.print(f"  ⚠️ Error checking dependencies: {e}")
        else:
            console.print(f"  ❌ Setup wizard unavailable: {setup_import_error}")

        # Check config paths and files
        console.print("\n[bold]Configuration Files:[/bold]")

        # Show where we're looking for config
        if setup_available:
            try:
                from penguin.setup.wizard import get_config_path

                setup_config_path = get_config_path()
                console.print(
                    f"  Setup wizard looks for config at: {setup_config_path}"
                )
                console.print(
                    f"    Exists: {'✓' if setup_config_path.exists() else '❌'}"
                )
            except Exception as e:
                console.print(f"  Error getting setup config path: {e}")

        # Show main app config loading
        try:
            from penguin.config import load_config

            config_data = load_config()
            if config_data:
                console.print("  ✓ Main app found config data")

                # Check key config sections
                required_sections = ["model", "workspace"]
                for section in required_sections:
                    if section in config_data:
                        console.print(f"    ✓ {section} section present")
                    else:
                        console.print(f"    ❌ {section} section missing")
            else:
                console.print(
                    "  ⚠️ Main app using default config (no config file found)"
                )
        except Exception as e:
            console.print(f"  ❌ Error loading main config: {e}")

        # Check first run status
        console.print("\n[bold]First Run Detection:[/bold]")
        try:
            is_first_run = check_first_run()
            console.print(f"  First run needed: {'Yes' if is_first_run else 'No'}")

            if setup_available:
                from penguin.setup.wizard import check_config_completeness

                is_complete = check_config_completeness()
                console.print(f"  Config complete: {'Yes' if is_complete else 'No'}")
        except Exception as e:
            console.print(f"  Error checking first run status: {e}")

        # Environment variables
        console.print("\n[bold]Environment Variables:[/bold]")
        env_vars = [
            "PENGUIN_CONFIG_PATH",
            "PENGUIN_ROOT",
            "PENGUIN_WORKSPACE",
            "XDG_CONFIG_HOME",
            "APPDATA",
        ]

        for var in env_vars:
            value = os.environ.get(var)
            if value:
                console.print(f"  {var}: {value}")
            else:
                console.print(f"  {var}: [dim]not set[/dim]")

        console.print(
            f"\n[dim]Platform: {platform.system()} {platform.release()}[/dim]"
        )
        console.print(f"[dim]Python: {sys.version}[/dim]")

    @permissions_app.command("list")
    def permissions_list(
        json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
        verbose: bool = typer.Option(
            False, "-v", "--verbose", help="Show detailed info"
        ),
    ):
        """List current permission settings and capabilities.

        Shows:
        - Current security mode (read_only, workspace, full)
        - Allowed/denied paths
        - Operations requiring approval
        - Agent-specific permissions (if any)
        """
        from rich.panel import Panel
        from rich.table import Table

        try:
            from penguin.config import load_config, SecurityConfig
            from penguin.security.agent_permissions import _agent_policies

            config = load_config()
            security_data = config.get("security", {})
            security_config = SecurityConfig.from_dict(security_data)

            if json_output:
                output = {
                    "mode": security_config.mode,
                    "enabled": security_config.enabled,
                    "allowed_paths": security_config.allowed_paths,
                    "denied_paths": security_config.denied_paths,
                    "require_approval": security_config.require_approval,
                    "audit": security_config.audit.to_dict(),
                    "agent_policies": list(_agent_policies.keys()),
                }
                console.print(json.dumps(output, indent=2))
                return

            # Display header
            mode_color = {
                "read_only": "yellow",
                "workspace": "green",
                "full": "red",
            }.get(security_config.mode, "white")
            console.print(
                Panel(
                    f"[bold]Security Mode:[/bold] [{mode_color}]{security_config.mode.upper()}[/{mode_color}]\n"
                    f"[bold]Enabled:[/bold] {'✅ Yes' if security_config.enabled else '❌ No'}",
                    title="🔐 Permission Settings",
                    border_style="cyan",
                )
            )

            # Paths table
            if verbose or security_config.allowed_paths or security_config.denied_paths:
                path_table = Table(title="Path Restrictions", show_header=True)
                path_table.add_column("Type", style="bold")
                path_table.add_column("Patterns")

                if security_config.allowed_paths:
                    path_table.add_row(
                        "[green]Allowed[/green]",
                        ", ".join(security_config.allowed_paths) or "(none)",
                    )
                if security_config.denied_paths:
                    path_table.add_row(
                        "[red]Denied[/red]",
                        ", ".join(security_config.denied_paths[:5])
                        + (
                            f" (+{len(security_config.denied_paths) - 5} more)"
                            if len(security_config.denied_paths) > 5
                            else ""
                        ),
                    )

                console.print(path_table)

            # Operations requiring approval
            if security_config.require_approval:
                console.print("\n[bold]Operations requiring approval:[/bold]")
                for op in security_config.require_approval:
                    console.print(f"  • {op}")

            # Audit settings
            if verbose:
                console.print("\n[bold]Audit Settings:[/bold]")
                console.print(f"  Enabled: {security_config.audit.enabled}")
                console.print(f"  Log file: {security_config.audit.log_file}")
                console.print(f"  Categories: {security_config.audit.categories}")

            # Agent policies
            if _agent_policies:
                console.print(
                    f"\n[bold]Agent Policies:[/bold] {len(_agent_policies)} registered"
                )
                if verbose:
                    for agent_id, policy in _agent_policies.items():
                        console.print(
                            f"  • {agent_id}: mode={policy.agent_config.mode}"
                        )

        except ImportError as e:
            console.print(f"[red]Security module not available: {e}[/red]")
            raise typer.Exit(code=1)
        except Exception as e:
            console.print(f"[red]Error reading permissions: {e}[/red]")
            if verbose:
                console.print(f"[dim]{traceback.format_exc()}[/dim]")
            raise typer.Exit(code=1)

    @permissions_app.command("audit")
    def permissions_audit(
        limit: int = typer.Option(
            20, "-n", "--limit", help="Number of entries to show"
        ),
        result: Optional[str] = typer.Option(
            None, "-r", "--result", help="Filter by result (allow/ask/deny)"
        ),
        category: Optional[str] = typer.Option(
            None, "-c", "--category", help="Filter by category"
        ),
        json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
    ):
        """Show recent permission audit log entries.

        Displays recent permission checks with their results, useful for debugging
        why operations were allowed or denied.
        """
        from rich.table import Table

        try:
            from penguin.security.audit import get_audit_logger

            audit_logger = get_audit_logger()
            entries = audit_logger.get_recent_entries(
                limit=limit,
                result_filter=result,
                category_filter=category,
            )

            if json_output:
                console.print(json.dumps([e.to_dict() for e in entries], indent=2))
                return

            if not entries:
                console.print("[yellow]No audit entries found.[/yellow]")
                if not audit_logger._enabled:
                    console.print(
                        "[dim]Hint: Audit logging may be disabled in config.[/dim]"
                    )
                return

            table = Table(
                title=f"Recent Permission Checks (last {len(entries)})",
                show_header=True,
            )
            table.add_column("Time", style="dim", width=12)
            table.add_column("Operation", style="cyan")
            table.add_column("Resource", style="white", max_width=30)
            table.add_column("Result", style="bold")
            table.add_column("Reason", max_width=35)

            for entry in entries:
                # Parse timestamp to show just time
                time_str = (
                    entry.timestamp.split("T")[1][:8]
                    if "T" in entry.timestamp
                    else entry.timestamp[:8]
                )

                # Color result
                result_color = {"allow": "green", "ask": "yellow", "deny": "red"}.get(
                    entry.result, "white"
                )
                result_display = (
                    f"[{result_color}]{entry.result.upper()}[/{result_color}]"
                )

                # Truncate resource if needed
                resource = entry.resource
                if len(resource) > 30:
                    resource = "..." + resource[-27:]

                table.add_row(
                    time_str,
                    entry.operation,
                    resource,
                    result_display,
                    entry.reason[:35] + "..."
                    if len(entry.reason) > 35
                    else entry.reason,
                )

            console.print(table)

            # Show summary
            stats = audit_logger.get_stats()
            console.print(
                f"\n[dim]Total: {stats['total']} checks | "
                f"Allow: {stats['allow']} | Ask: {stats['ask']} | Deny: {stats['deny']}[/dim]"
            )

        except ImportError as e:
            console.print(f"[red]Audit module not available: {e}[/red]")
            raise typer.Exit(code=1)
        except Exception as e:
            console.print(f"[red]Error reading audit log: {e}[/red]")
            raise typer.Exit(code=1)

    @permissions_app.command("summary")
    def permissions_summary():
        """Show a summary of permission audit activity."""
        try:
            from penguin.security.audit import get_audit_logger

            audit_logger = get_audit_logger()
            summary = audit_logger.get_summary()
            console.print(summary)

        except ImportError as e:
            console.print(f"[red]Audit module not available: {e}[/red]")
            raise typer.Exit(code=1)
        except Exception as e:
            console.print(f"[red]Error generating summary: {e}[/red]")
            raise typer.Exit(code=1)

    # Agent Management Commands

    return {
        "config_setup": config_setup,
        "config_edit": config_edit,
        "config_check": config_check,
        "config_test_routing": config_test_routing,
        "config_debug": config_debug,
        "permissions_list": permissions_list,
        "permissions_audit": permissions_audit,
        "permissions_summary": permissions_summary,
    }
