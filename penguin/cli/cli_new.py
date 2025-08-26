# # Context subcommands (headless parity)
# @app.command("context")
# def context_cmd(
#     action: str = typer.Argument(..., help="list|paths|write|edit|remove|note|add"),
#     arg1: Optional[str] = typer.Argument(None, help="Primary argument (file/relpath/title)"),
#     arg2: Optional[str] = typer.Argument(None, help="Secondary argument"),
#     workspace_flag: bool = typer.Option(False, "--workspace", help="Treat input as workspace-rooted for add"),
#     as_name: Optional[str] = typer.Option(None, "--as", help="Destination filename for add"),
#     body: Optional[str] = typer.Option(None, "--body", help="Body text for write/note"),
#     replace: Optional[str] = typer.Option(None, "--replace", help="Text to replace for edit"),
#     with_text: Optional[str] = typer.Option(None, "--with", help="Replacement text for edit"),
# ):
#     """Headless /context parity."""
#     # Reuse Interface handlers for consistent behavior
#     try:
#         import asyncio
#         from penguin.core import PenguinCore
#         from penguin.cli.interface import PenguinInterface

#         async def run():
#             core = await PenguinCore.create(show_progress=False, fast_startup=True)
#             interface = PenguinInterface(core)
#             args: list[str] = [action]
#             if action == 'list' or action == 'paths':
#                 pass
#             elif action == 'load':
#                 if not arg1:
#                     raise typer.BadParameter("/context load requires a file path")
#                 args.append(arg1)
#             elif action == 'write':
#                 if not arg1 or body is None:
#                     raise typer.BadParameter("/context write requires <relpath> and --body")
#                 args += [arg1, "--body", body]
#             elif action == 'edit':
#                 if not arg1 or replace is None or with_text is None:
#                     raise typer.BadParameter("/context edit requires <relpath>, --replace and --with")
#                 args += [arg1, "--replace", replace, "--with", with_text]
#             elif action == 'remove':
#                 if not arg1:
#                     raise typer.BadParameter("/context remove requires <relpath>")
#                 args.append(arg1)
#             elif action == 'note':
#                 if not arg1 or body is None:
#                     raise typer.BadParameter("/context note requires <Title> and --body")
#                 args += [arg1, "--body", body]
#             elif action == 'add':
#                 if not arg1:
#                     raise typer.BadParameter("/context add requires a source path")
#                 args.append(arg1)
#                 if workspace_flag:
#                     args.append("--workspace")
#                 else:
#                     args.append("--project")
#                 if as_name:
#                     args += ["--as", as_name]
#             else:
#                 raise typer.BadParameter("Unknown context action")
#             result = await interface._handle_context_command(args)
#             # Print a friendly status or JSON
#             status = result.get("status")
#             if status:
#                 print(status)
#             else:
#                 print(json.dumps(result, indent=2))

#         asyncio.run(run())
#     except Exception as e:
#         print(json.dumps({"status": "error", "error": str(e)}, indent=2))
#         raise typer.Exit(code=1)
# #!/usr/bin/env python3
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
    cwd: Optional[Path] = typer.Option(None, "--cwd", help="Operate as if launched from this directory"),
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
    # Set explicit working directory for config/project root detection
    if cwd is not None:
        os.environ["PENGUIN_CWD"] = str(cwd.resolve())
    
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
def config(
    ctx: typer.Context,
    action: str = typer.Argument(..., help="list|get|set|add|remove|paths|validate"),
    key: Optional[str] = typer.Argument(None, help="Dot path key (for get/set/add/remove)"),
    value: Optional[str] = typer.Argument(None, help="Value to set or add/remove"),
    global_scope: bool = typer.Option(False, "-g", "--global", help="Operate on user config instead of project"),
    output_format: str = typer.Option("text", "--output-format", help="text or json"),
    cwd: Optional[Path] = typer.Option(None, "--cwd", help="Operate as if launched from this directory"),
):
    """Manage Penguin configuration (project/user)."""
    lazy_imports()
    console = Console()
    try:
        from penguin.config import (
            load_config as _load_config,
            set_config_value as _set_config_value,
            get_config_value as _get_config_value,
            get_user_config_path as _get_user_config_path,
            get_project_config_paths as _get_project_config_paths,
        )

        scope = 'global' if global_scope else 'project'
        cwd_str = str(cwd.resolve()) if cwd else os.environ.get('PENGUIN_CWD')

        if action == 'list':
            cfg = _load_config()
            if output_format == 'json':
                print(json.dumps(cfg, indent=2))
            else:
                console.print("[cyan]Effective configuration (merged):[/cyan]")
                console.print(json.dumps(cfg, indent=2))
            return

        if action == 'paths':
            from penguin.utils.path_utils import get_allowed_roots
            prj_root, ws_root, proj_extra, ctx_extra = get_allowed_roots(cwd_str)
            data = {
                "project_root": str(prj_root),
                "workspace_root": str(ws_root),
                "project_additional": [str(p) for p in proj_extra],
                "context_additional": [str(p) for p in ctx_extra],
            }
            if output_format == 'json':
                print(json.dumps(data, indent=2))
            else:
                console.print(json.dumps(data, indent=2))
            return

        if action == 'validate':
            # Light schema check: warn unknown top-level keys and type mismatches for known ones
            cfg = _load_config()
            known = {"workspace", "model", "api", "tools", "diagnostics", "project", "context", "defaults", "model_configs", "paths"}
            warnings = []
            for k in cfg.keys():
                if k not in known:
                    warnings.append(f"Unknown top-level key: {k}")
            # Type checks
            if not isinstance(cfg.get("project", {}), dict):
                warnings.append("'project' should be a mapping")
            if not isinstance(cfg.get("context", {}), dict):
                warnings.append("'context' should be a mapping")
            if not isinstance(cfg.get("defaults", {}), dict):
                warnings.append("'defaults' should be a mapping")
            result = {"status": "ok" if not warnings else "warn", "warnings": warnings}
            if output_format == 'json':
                print(json.dumps(result, indent=2))
            else:
                console.print(json.dumps(result, indent=2))
            return

        if action == 'get':
            if not key:
                console.print("[red]Error:[/red] 'get' requires a key")
                raise typer.Exit(code=1)
            val = _get_config_value(key, default=None, cwd_override=cwd_str)
            if output_format == 'json':
                print(json.dumps({"key": key, "value": val}, indent=2))
            else:
                console.print(f"{key} = {val!r}")
            return

        if action in ('set', 'add', 'remove'):
            if not key:
                console.print(f"[red]Error:[/red] '{action}' requires a key")
                raise typer.Exit(code=1)
            if action == 'set' and value is None:
                console.print("[red]Error:[/red] 'set' requires a value")
                raise typer.Exit(code=1)
            # Try to parse JSON values when possible
            parsed_val: Any = value
            if value is not None:
                try:
                    parsed_val = json.loads(value)
                except Exception:
                    parsed_val = value
            list_op = None
            if action in ('add', 'remove'):
                list_op = action
            written_path = _set_config_value(key, parsed_val, scope=scope, cwd_override=cwd_str, list_op=list_op)
            if output_format == 'json':
                print(json.dumps({"status": "ok", "written": str(written_path), "action": action, "key": key, "value": parsed_val}, indent=2))
            else:
                console.print(f"[green]Updated[/green] {action} {key} -> {parsed_val!r} in {written_path}")
            return

        console.print("[red]Error:[/red] Unknown action. Use list|get|set|add|remove|paths|validate")
        raise typer.Exit(code=1)

    except Exception as e:
        if output_format == 'json':
            print(json.dumps({"status": "error", "error": str(e)}, indent=2))
        else:
            console.print(f"[red]Error:[/red] {e}", file=sys.stderr)
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


# Context subcommands (headless parity) - registered after app exists
@app.command("context")
def context_cmd(
    action: str = typer.Argument(..., help="list|paths|write|edit|remove|note|add"),
    arg1: Optional[str] = typer.Argument(None, help="Primary argument (file/relpath/title)"),
    arg2: Optional[str] = typer.Argument(None, help="Secondary argument"),
    workspace_flag: bool = typer.Option(False, "--workspace", help="Treat input as workspace-rooted for add"),
    as_name: Optional[str] = typer.Option(None, "--as", help="Destination filename for add"),
    body: Optional[str] = typer.Option(None, "--body", help="Body text for write/note"),
    replace: Optional[str] = typer.Option(None, "--replace", help="Text to replace for edit"),
    with_text: Optional[str] = typer.Option(None, "--with", help="Replacement text for edit"),
):
    """Headless /context parity."""
    try:
        import asyncio
        import os as _os

        # Force a low-impact, no-network client preference during tests or when keys are absent
        no_network_flag = _os.environ.get("PENGUIN_NO_NETWORK", "0") == "1"
        no_keys_present = not (_os.environ.get("OPENROUTER_API_KEY") or _os.environ.get("OPENAI_API_KEY") or _os.environ.get("ANTHROPIC_API_KEY"))
        if no_network_flag or no_keys_present:
            _os.environ["PENGUIN_CLIENT_PREFERENCE"] = "litellm"
            # Keep defaults simple; LiteLLM won't contact network until actually used
            _os.environ.setdefault("PENGUIN_DEFAULT_PROVIDER", "openai")
            _os.environ.setdefault("PENGUIN_DEFAULT_MODEL", "gpt-4o-mini")
            # Ensure gateways that require API keys can initialize without network calls
            _os.environ.setdefault("OPENROUTER_API_KEY", "DUMMY")
            _os.environ.setdefault("OPENAI_API_KEY", "DUMMY")
            _os.environ.setdefault("ANTHROPIC_API_KEY", "DUMMY")

        # Import after environment overrides so config/model selection sees them
        from penguin.core import PenguinCore
        from penguin.cli.interface import PenguinInterface

        async def run():
            # When forcing no-network, also pass explicit model/provider to bypass config defaults
            if no_network_flag or no_keys_present:
                core = await PenguinCore.create(
                    show_progress=False,
                    fast_startup=True,
                    model=_os.environ.get("PENGUIN_DEFAULT_MODEL", "gpt-4o-mini"),
                    provider=_os.environ.get("PENGUIN_DEFAULT_PROVIDER", "openai"),
                )
            else:
                core = await PenguinCore.create(show_progress=False, fast_startup=True)
            interface = PenguinInterface(core)
            args: list[str] = [action]
            if action in ('list', 'paths'):
                pass
            elif action == 'load':
                if not arg1:
                    raise typer.BadParameter("/context load requires a file path")
                args.append(arg1)
            elif action == 'write':
                if not arg1 or body is None:
                    raise typer.BadParameter("/context write requires <relpath> and --body")
                args += [arg1, "--body", body]
            elif action == 'edit':
                if not arg1 or replace is None or with_text is None:
                    raise typer.BadParameter("/context edit requires <relpath>, --replace and --with")
                args += [arg1, "--replace", replace, "--with", with_text]
            elif action == 'remove':
                if not arg1:
                    raise typer.BadParameter("/context remove requires <relpath>")
                args.append(arg1)
            elif action == 'note':
                if not arg1 or body is None:
                    raise typer.BadParameter("/context note requires <Title> and --body")
                args += [arg1, "--body", body]
            elif action == 'add':
                if not arg1:
                    raise typer.BadParameter("/context add requires a source path")
                args.append(arg1)
                if workspace_flag:
                    args.append("--workspace")
                else:
                    args.append("--project")
                if as_name:
                    args += ["--as", as_name]
            else:
                raise typer.BadParameter("Unknown context action")
            result = await interface._handle_context_command(args)
            status = result.get("status")
            if status:
                print(status)
            else:
                print(json.dumps(result, indent=2))

        asyncio.run(run())
    except Exception as e:
        print(json.dumps({"status": "error", "error": str(e)}, indent=2))
        raise typer.Exit(code=1)

def main():
    """Main entry point."""
    setup_signal_handlers()
    app()


if __name__ == "__main__":
    main()
