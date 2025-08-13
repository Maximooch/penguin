#!/usr/bin/env python3
"""
Penguin CLI - Slim entrypoint that defaults to TUI.

This is the new minimal CLI that:
- Launches TUI by default when no arguments provided
- Handles global flags and headless commands
- Delegates to old_cli.py when --old-cli is used
"""
import os
import sys
import signal
from pathlib import Path
from typing import Optional, List, Any, Dict
import json

# Lazy imports for performance
typer = None
Console = None


def lazy_imports():
    """Import heavy dependencies only when needed."""
    global typer, Console
    if typer is None:
        import typer as _typer
        typer = _typer
    if Console is None:
        from rich.console import Console as _Console
        Console = _Console


# Create app with lazy loading
def create_app():
    lazy_imports()
    app = typer.Typer(
        help="Penguin AI Assistant - Your intelligent coding companion.\n"
             "Run without arguments to start the TUI, or use headless commands.",
        no_args_is_help=False,  # Allow running without args for TUI
        add_completion=True,
        rich_markup_mode="rich"
    )
    return app


app = create_app()


# Exit codes
EXIT_SUCCESS = 0
EXIT_ERROR = 1
EXIT_INTERRUPT = 130


def setup_signal_handlers():
    """Setup graceful signal handling."""
    def signal_handler(signum, frame):
        if Console:
            console = Console(stderr=True)
            console.print("\n[yellow]Interrupted by user[/yellow]")
        sys.exit(EXIT_INTERRUPT)
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)


@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    # Global flags
    old_cli: bool = typer.Option(False, "--old-cli", help="Use the legacy Rich-based CLI"),
    no_tui: bool = typer.Option(False, "--no-tui", help="Force headless mode (no TUI)"),
    project: Optional[str] = typer.Option(None, "--project", help="Route tasks to specified project"),
    
    # One-shot prompt
    prompt: Optional[str] = typer.Option(None, "-p", "--prompt", help="Run single prompt and exit. Use '-' for stdin."),
    
    # Output control
    output_format: str = typer.Option("text", "--output-format", help="Output format: text, json"),
    quiet: bool = typer.Option(False, "--quiet", "-q", help="Minimal output"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Verbose output"),
    no_color: bool = typer.Option(False, "--no-color", help="Disable colored output"),
    
    # Model/workspace settings
    model: Optional[str] = typer.Option(None, "--model", "-m", help="Model to use (e.g., 'anthropic/claude-3-5-sonnet')"),
    workspace: Optional[Path] = typer.Option(None, "--workspace", "-w", help="Custom workspace path"),
    
    # Execution modes
    continue_last: bool = typer.Option(False, "--continue", "-c", help="Continue most recent conversation"),
    resume: Optional[str] = typer.Option(None, "--resume", help="Resume specific conversation by ID"),
    run: Optional[str] = typer.Option(None, "--run", help="Run task/project in autonomous mode"),
    continuous: bool = typer.Option(False, "--247", "--continuous", help="Run continuously until stopped"),
    time_limit: Optional[int] = typer.Option(None, "--time-limit", help="Time limit in minutes"),
    description: Optional[str] = typer.Option(None, "--description", help="Task description for --run"),
    
    # Performance/streaming
    no_streaming: bool = typer.Option(False, "--no-streaming", help="Disable streaming responses"),
    fast_startup: bool = typer.Option(True, "--fast-startup", help="Enable fast startup mode"),
    
    # Version
    version: bool = typer.Option(False, "--version", "-V", help="Show version and exit"),
):
    """Penguin AI - Intelligent coding assistant."""
    
    # Handle version first
    if version:
        lazy_imports()
        console = Console()
        try:
            from penguin import __version__
            console.print(f"Penguin AI v{__version__}")
        except:
            console.print("Penguin AI (version unknown)")
        return
    
    # Store global project in context for subcommands
    ctx.ensure_object(dict)
    ctx.obj["project"] = project
    ctx.obj["output_format"] = output_format
    ctx.obj["quiet"] = quiet
    ctx.obj["verbose"] = verbose
    
    # Configure output/logging based on flags
    if no_color:
        os.environ["NO_COLOR"] = "1"
    
    # Check for --old-cli first
    if old_cli:
        # Hand off to legacy CLI
        from penguin.cli.old_cli import main as old_main
        # Reconstruct args without --old-cli
        args = [arg for arg in sys.argv[1:] if arg != "--old-cli"]
        sys.argv = [sys.argv[0]] + args
        old_main()
        return
    
    # Determine if we should run headless
    headless_mode = any([
        no_tui,
        prompt is not None,
        continue_last,
        resume,
        run,
        continuous,
        ctx.invoked_subcommand is not None  # Any subcommand
    ])
    
    if headless_mode:
        # Running headless - handle one-shot prompt or delegate to subcommand
        if prompt is not None:
            # One-shot prompt mode
            run_prompt(prompt, model, workspace, output_format, no_streaming, fast_startup)
        elif continue_last or resume:
            # Continue/resume conversation
            run_continue_resume(continue_last, resume, model, workspace, output_format, no_streaming, fast_startup)
        elif run or continuous:
            # Run mode
            run_autonomous(run, continuous, time_limit, description, project, model, workspace, 
                          output_format, no_streaming, fast_startup)
        # Otherwise subcommand will be invoked by typer
    else:
        # No headless flags and no subcommand - launch TUI
        if ctx.invoked_subcommand is None:
            launch_tui()


def launch_tui():
    """Launch the Textual-based TUI."""
    try:
        from penguin.cli.tui import TUI
        TUI.run()
    except ImportError as e:
        lazy_imports()
        console = Console(stderr=True)
        console.print(f"[red]Error:[/red] Failed to import TUI: {e}")
        console.print("Please ensure Textual is installed: pip install textual")
        sys.exit(EXIT_ERROR)
    except Exception as e:
        lazy_imports()
        console = Console(stderr=True)
        console.print(f"[red]Error launching TUI:[/red] {e}")
        sys.exit(EXIT_ERROR)


def run_prompt(prompt: str, model: Optional[str], workspace: Optional[Path], 
               output_format: str, no_streaming: bool, fast_startup: bool):
    """Run a single prompt in headless mode."""
    lazy_imports()
    console = Console()
    
    try:
        # Read from stdin if prompt is '-'
        if prompt == "-":
            import sys
            prompt = sys.stdin.read().strip()
            if not prompt:
                console.print("[red]Error:[/red] No input provided via stdin", file=sys.stderr)
                sys.exit(EXIT_ERROR)
        
        # Use interface for consistency
        from penguin.cli.interface import PenguinInterface
        from penguin.core import PenguinCore
        
        # Create core with settings
        import asyncio
        
        async def run():
            core = await PenguinCore.create(
                model=model,
                workspace_path=str(workspace) if workspace else None,
                fast_startup=fast_startup,
                show_progress=False
            )
            interface = PenguinInterface(core)
            
            # Process the prompt
            result = await interface.process_input({
                "text": prompt,
                "streaming": not no_streaming
            })
            
            # Format output
            if output_format == "json":
                output = {
                    "status": "success",
                    "prompt": prompt,
                    "response": result.get("response", ""),
                    "model": result.get("model_used", model),
                    "tokens": result.get("tokens_used", 0)
                }
                print(json.dumps(output, indent=2))
            else:
                # Text format - just print the response
                if result.get("response"):
                    print(result["response"])
        
        asyncio.run(run())
        
    except KeyboardInterrupt:
        console.print("\n[yellow]Interrupted[/yellow]", file=sys.stderr)
        sys.exit(EXIT_INTERRUPT)
    except Exception as e:
        if output_format == "json":
            output = {
                "status": "error",
                "error": str(e),
                "prompt": prompt
            }
            print(json.dumps(output, indent=2))
        else:
            console.print(f"[red]Error:[/red] {e}", file=sys.stderr)
        sys.exit(EXIT_ERROR)


def run_continue_resume(continue_last: bool, resume_id: Optional[str], 
                       model: Optional[str], workspace: Optional[Path],
                       output_format: str, no_streaming: bool, fast_startup: bool):
    """Continue or resume a conversation."""
    # Delegate to interface
    lazy_imports()
    console = Console()
    console.print("[yellow]Continue/resume functionality coming soon[/yellow]")
    console.print("For now, please use --old-cli for this feature")
    sys.exit(EXIT_ERROR)


def run_autonomous(run_task: Optional[str], continuous: bool, time_limit: Optional[int],
                  description: Optional[str], project: Optional[str], model: Optional[str],
                  workspace: Optional[Path], output_format: str, no_streaming: bool, 
                  fast_startup: bool):
    """Run in autonomous mode."""
    # Delegate to interface 
    lazy_imports()
    console = Console()
    console.print("[yellow]Autonomous mode functionality coming soon[/yellow]")
    console.print("For now, please use --old-cli for this feature")
    sys.exit(EXIT_ERROR)


# Subcommands
@app.command()
def setup():
    """Run initial setup wizard."""
    lazy_imports()
    console = Console()
    
    try:
        from penguin.setup.wizard import SetupWizard
        wizard = SetupWizard()
        wizard.run()
    except Exception as e:
        console.print(f"[red]Setup failed:[/red] {e}", file=sys.stderr)
        sys.exit(EXIT_ERROR)


@app.command()
def delegate(
    ctx: typer.Context,
    task: str = typer.Argument(..., help="Task description to delegate"),
    context: Optional[List[str]] = typer.Option(None, "--context", "-c", help="Context files or URLs"),
    async_mode: bool = typer.Option(False, "--async", help="Run asynchronously and return task ID"),
):
    """Delegate a task to Penguin."""
    project = ctx.obj.get("project")
    output_format = ctx.obj.get("output_format", "text")
    
    lazy_imports()
    console = Console()
    
    try:
        # Validate context paths/URLs
        validated_context = []
        if context:
            for item in context:
                if item.startswith(("http://", "https://")):
                    validated_context.append({"type": "url", "value": item})
                else:
                    path = Path(item)
                    if path.exists():
                        validated_context.append({"type": "file", "value": str(path.absolute())})
                    else:
                        console.print(f"[yellow]Warning:[/yellow] Context file not found: {item}", file=sys.stderr)
        
        # Create task
        task_data = {
            "description": task,
            "context": validated_context,
            "project": project,
            "async": async_mode
        }
        
        if output_format == "json":
            # TODO: Implement actual delegation
            output = {
                "status": "created",
                "task": task_data,
                "id": "task_123"  # Placeholder
            }
            print(json.dumps(output, indent=2))
        else:
            console.print(f"[green]Task delegated:[/green] {task}")
            if project:
                console.print(f"Project: {project}")
            if validated_context:
                console.print(f"Context: {len(validated_context)} items")
            if async_mode:
                console.print("Task ID: task_123")  # Placeholder
    
    except Exception as e:
        if output_format == "json":
            output = {"status": "error", "error": str(e)}
            print(json.dumps(output, indent=2))
        else:
            console.print(f"[red]Error:[/red] {e}", file=sys.stderr)
        sys.exit(EXIT_ERROR)


# Project management commands
project_app = typer.Typer(help="Project management commands")
app.add_typer(project_app, name="project")


@project_app.command("create")
def project_create(
    ctx: typer.Context,
    name: str = typer.Argument(..., help="Project name"),
    description: Optional[str] = typer.Option(None, "--description", "-d", help="Project description"),
):
    """Create a new project."""
    output_format = ctx.obj.get("output_format", "text")
    lazy_imports()
    console = Console()
    
    # TODO: Implement via interface
    if output_format == "json":
        output = {"status": "created", "project": {"name": name, "description": description}}
        print(json.dumps(output, indent=2))
    else:
        console.print(f"[green]Project created:[/green] {name}")


@project_app.command("list")
def project_list(ctx: typer.Context):
    """List all projects."""
    output_format = ctx.obj.get("output_format", "text")
    lazy_imports()
    console = Console()
    
    # TODO: Implement via interface
    if output_format == "json":
        output = {"status": "success", "projects": []}
        print(json.dumps(output, indent=2))
    else:
        console.print("No projects found")


@project_app.command("delete")
def project_delete(
    ctx: typer.Context,
    name: str = typer.Argument(..., help="Project name"),
    force: bool = typer.Option(False, "--force", "-f", help="Skip confirmation"),
):
    """Delete a project."""
    output_format = ctx.obj.get("output_format", "text")
    lazy_imports()
    console = Console()
    
    if not force:
        confirm = typer.confirm(f"Are you sure you want to delete project '{name}'?")
        if not confirm:
            raise typer.Abort()
    
    # TODO: Implement via interface
    if output_format == "json":
        output = {"status": "deleted", "project": name}
        print(json.dumps(output, indent=2))
    else:
        console.print(f"[green]Project deleted:[/green] {name}")


# Task management commands  
task_app = typer.Typer(help="Task management commands")
app.add_typer(task_app, name="task")


@task_app.command("create")
def task_create(
    ctx: typer.Context,
    title: str = typer.Argument(..., help="Task title"),
    project: Optional[str] = typer.Option(None, "--project", "-p", help="Associate with project"),
    priority: int = typer.Option(2, "--priority", help="Priority (1-5, 1=highest)"),
):
    """Create a new task."""
    # Use global project if not specified
    if not project:
        project = ctx.obj.get("project")
    
    output_format = ctx.obj.get("output_format", "text")
    lazy_imports()
    console = Console()
    
    # TODO: Implement via interface
    if output_format == "json":
        output = {
            "status": "created",
            "task": {"title": title, "project": project, "priority": priority}
        }
        print(json.dumps(output, indent=2))
    else:
        console.print(f"[green]Task created:[/green] {title}")
        if project:
            console.print(f"Project: {project}")


@task_app.command("list")  
def task_list(
    ctx: typer.Context,
    project: Optional[str] = typer.Option(None, "--project", "-p", help="Filter by project"),
    status: Optional[str] = typer.Option(None, "--status", "-s", help="Filter by status"),
):
    """List tasks."""
    # Use global project if not specified
    if not project:
        project = ctx.obj.get("project")
        
    output_format = ctx.obj.get("output_format", "text")
    lazy_imports()
    console = Console()
    
    # TODO: Implement via interface
    if output_format == "json":
        output = {"status": "success", "tasks": []}
        print(json.dumps(output, indent=2))
    else:
        console.print("No tasks found")


# Performance testing
@app.command("perf-test")
def perf_test(
    iterations: int = typer.Option(3, "--iterations", "-i", help="Number of iterations"),
    show_report: bool = typer.Option(True, "--report/--no-report", help="Show detailed report"),
):
    """Run performance tests."""
    lazy_imports()
    console = Console()
    
    try:
        # Delegate to old CLI for now
        console.print("[yellow]Running performance test via legacy CLI...[/yellow]")
        from penguin.cli.old_cli import perf_test as old_perf_test
        old_perf_test(iterations=iterations, show_report=show_report)
    except Exception as e:
        console.print(f"[red]Performance test failed:[/red] {e}", file=sys.stderr)
        sys.exit(EXIT_ERROR)


# Profiling
@app.command()
def profile(
    output_file: str = typer.Option("penguin_profile", "--output", "-o", help="Output file name"),
    view: bool = typer.Option(False, "--view", "-v", help="Open visualization after saving"),
):
    """Profile Penguin execution."""
    lazy_imports()
    console = Console()
    
    try:
        # Delegate to old CLI for now
        console.print("[yellow]Running profiler via legacy CLI...[/yellow]")
        from penguin.cli.old_cli import profile as old_profile
        old_profile(output_file=output_file, view=view)
    except Exception as e:
        console.print(f"[red]Profiling failed:[/red] {e}", file=sys.stderr)
        sys.exit(EXIT_ERROR)


def main():
    """Main entry point."""
    setup_signal_handlers()
    app()


if __name__ == "__main__":
    main()
