"""
Penguin CLI - Unified Command-Line Interface

This module provides the main CLI for the Penguin AI Assistant, combining:
- Interactive chat sessions with Rich-based display and event-driven streaming
- Project and task management commands
- Multi-agent coordination and messaging
- Configuration and setup wizards
- Performance profiling and diagnostics

Architecture:
────────────
Entry Point Chain:
  pyproject.toml [project.scripts]
      ↓
  penguin.cli.cli:app (this file)
      ↓
  PenguinCLI class (interactive session manager)
      ↓
  PenguinInterface (business logic layer in interface.py)
      ↓
  PenguinCore (AI engine in core.py)

Key Components:
───────────────
1. Typer Application Setup (lines ~1-200)
   - Global app with subcommands: project, agent, msg, coord, config, task
   - Core component initialization
   - Configuration management

2. Main Entry Point (lines ~430-600)
   - main_entry(): Handles all CLI flags and routing
   - Headless mode detection (--no-tui, -p/--prompt)
   - Session management (--continue, --resume)
   - Task execution (--run, --247/--continuous)

3. Subcommand Groups (lines ~750-1900)
   - config_app: Setup wizard, config editing, validation
   - agent_app: Multi-agent management (spawn, personas, pause/resume, activate)
   - project_app: Project creation, listing, deletion, workflow execution
   - task_app: Task CRUD operations and status management
   - msg_app: Message routing to agents and human
   - coord_app: Multi-agent coordinator workflows (spawn, broadcast, role-chains)

4. PenguinCLI Class (lines ~1900-3380)
   - Interactive session manager with event-based streaming
   - Rich panel display with syntax highlighting
   - Code block detection and formatting (20+ languages)
   - Reasoning token display (separate gray panels)
   - Tool result buffering for chronological ordering
   - Multi-line input with prompt_toolkit (Alt+Enter for newlines)
   - Conversation menu and session management

   Key Features:
   - ✅ Event-driven streaming from Core (no legacy callbacks)
   - ✅ Separate reasoning/content buffers
   - ✅ Tool results buffer during streaming
   - ✅ Automatic code detection and highlighting
   - ✅ Progress indicators with proper cleanup
   - ✅ Duplicate message prevention

5. Top-Level Commands (lines ~3380-3780)
   - chat: Start interactive session
   - perf_test: Startup performance benchmarking
   - profile: cProfile-based profiling with snakeviz integration

History:
────────
This file is the result of merging old_cli.py (polished PenguinCLI implementation)
into cli.py (comprehensive subcommand structure). The merge preserves:
- All subcommands from cli.py (agent, msg, coord, project, task, config)
- Polished PenguinCLI class from old_cli.py with all Round 6 fixes
- Event-based streaming system (no stream_callback bugs)
- Diff rendering, reasoning display, tool result buffering

For TUI interface, use: penguin-tui-proto (experimental)
For command documentation, see: penguin/cli/commands.yml

Maintainer Notes:
─────────────────
- PenguinCLI class handles ALL display logic (don't duplicate in commands)
- Use PenguinInterface for business logic (shared with TUI/Web)
- All streaming goes through Core events (handle_event method)
- Tool results auto-buffer during streaming for correct ordering
- Update commands.yml when adding new slash commands
"""

import asyncio
import datetime
import io

# Removed mock imports - using real RunMode implementation now
import json  # For JSON output
import logging
import os
import platform
import re
import signal
import sys
import traceback
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple, TypeVar, Union

# Ensure UTF-8 encoding for stdout/stderr to prevent emoji encoding issues
# This is especially important on Windows and some terminal environments
try:
    # Only wrap if not already wrapped and if buffer is available
    if hasattr(sys.stdout, "buffer") and not isinstance(sys.stdout, io.TextIOWrapper):
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    if hasattr(sys.stderr, "buffer") and not isinstance(sys.stderr, io.TextIOWrapper):
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8")
except (AttributeError, OSError):
    # If wrapping fails, continue with existing streams
    pass

# Allow setup wizard on import when launched via CLI entry point
os.environ.setdefault("PENGUIN_SETUP_ON_IMPORT", "1")

# Add import timing for profiling if enabled
import time

PROFILE_ENABLED = os.environ.get("PENGUIN_PROFILE", "0") == "1"
if PROFILE_ENABLED:
    print("\033[2mStarting CLI module import timing...\033[0m")
    import importlib
    total_start = time.time()
    module_times = {}

    def time_import(module_name):
        start = time.time()
        result = importlib.import_module(module_name)
        end = time.time()
        module_times[module_name] = (end - start) * 1000  # Convert to ms
        return result

    # Time major imports
    typer = time_import("typer")
    RichConsole = time_import("rich.console").Console
    Markdown = time_import("rich.markdown").Markdown
    Panel = time_import("rich.panel").Panel
    _rich_progress = time_import("rich.progress")
    Progress = _rich_progress.Progress
    SpinnerColumn = _rich_progress.SpinnerColumn
    TextColumn = _rich_progress.TextColumn
    Syntax = time_import("rich.syntax").Syntax
    Live = time_import("rich.live").Live
    Text = time_import("rich.text").Text
    rich = time_import("rich")

    # prompt_toolkit imports
    PromptSession = time_import("prompt_toolkit").PromptSession
    KeyBindings = time_import("prompt_toolkit.key_binding").KeyBindings
    Keys = time_import("prompt_toolkit.keys").Keys
    Style = time_import("prompt_toolkit.styles").Style
    HTML = time_import("prompt_toolkit.formatted_text").HTML

    # Removed prompt_toolkit timing imports – legacy Rich CLI removed

    # Time internal imports
    config_module = time_import("penguin.config")
    # Now access specific attributes after import
    config = config_module.config
    DEFAULT_MODEL = config_module.DEFAULT_MODEL
    DEFAULT_PROVIDER = config_module.DEFAULT_PROVIDER
    WORKSPACE_PATH = config_module.WORKSPACE_PATH

    PenguinCore_module = time_import("penguin.core")
    PenguinCore = PenguinCore_module.PenguinCore
    APIClient_module = time_import("penguin.llm.api_client")
    APIClient = APIClient_module.APIClient
    ModelConfig_module = time_import("penguin.llm.model_config")
    ModelConfig = ModelConfig_module.ModelConfig
    # RunMode = time_import("penguin.run_mode").RunMode # Not directly used in this new structure's top level
    MessageCategory_module = time_import("penguin.system.state")
    MessageCategory = MessageCategory_module.MessageCategory
    parse_iso_datetime = MessageCategory_module.parse_iso_datetime
    # ConversationMenu = time_import("penguin.system.conversation_menu").ConversationMenu # Used by PenguinCLI class
    # ConversationSummary = time_import("penguin.system.conversation_menu").ConversationSummary # Used by PenguinCLI class
    SYSTEM_PROMPT_module = time_import("penguin.system_prompt")
    SYSTEM_PROMPT = SYSTEM_PROMPT_module.SYSTEM_PROMPT
    ToolManager_module = time_import("penguin.tools")
    ToolManager = ToolManager_module.ToolManager
    log_error_module = time_import("penguin.utils.log_error")
    log_error = log_error_module.log_error
    setup_logger_module = time_import("penguin.utils.logs")
    setup_logger = setup_logger_module.setup_logger
    PenguinInterface_module = time_import("penguin.cli.interface")
    PenguinInterface = PenguinInterface_module.PenguinInterface

    # Import unified command system
    CommandRegistry_module = time_import("penguin.cli.commands")
    CommandRegistry = CommandRegistry_module.CommandRegistry
    TyperBridge_module = time_import("penguin.cli.typer_bridge")
    TyperBridge = TyperBridge_module.TyperBridge
    integrate_with_existing_app = TyperBridge_module.integrate_with_existing_app

    total_end = time.time()
    total_import_time = (total_end - total_start) * 1000  # Convert to ms

    # Print import times
    print("\033[2mImport timing results:\033[0m")
    sorted_modules = sorted(module_times.items(), key=lambda x: x[1], reverse=True)
    for module, time_ms in sorted_modules:
        percentage = (time_ms / total_import_time) * 100
        if percentage >= 5.0:  # Only show significant contributors
            print(f"\033[2m  {module}: {time_ms:.0f}ms ({percentage:.1f}%)\033[0m")
    print(f"\033[2mTotal import time: {total_import_time:.0f}ms\033[0m")
else:
    # Standard imports without timing
    import typer  # type: ignore
    from rich.console import Console as RichConsole  # type: ignore
    from rich.markdown import Markdown  # type: ignore
    from rich.panel import Panel  # type: ignore
    from rich.progress import Progress, SpinnerColumn, TextColumn  # type: ignore
    from rich.syntax import Syntax  # type: ignore
    from rich.live import Live  # type: ignore
    from rich.text import Text  # type: ignore
    import rich  # type: ignore
    from prompt_toolkit import PromptSession  # type: ignore
    from prompt_toolkit.key_binding import KeyBindings  # type: ignore
    from prompt_toolkit.keys import Keys  # type: ignore
    from prompt_toolkit.styles import Style  # type: ignore
    from prompt_toolkit.formatted_text import HTML  # type: ignore

from penguin._version import __version__
from penguin.cli.agent_commands import bind_agent_commands
from penguin.cli.bootstrap import bootstrap_cli
from penguin.cli.command_services import (
    AmbiguousProjectError,
    InvalidTaskStateError,
    NoProjectTasksError,
    NoReadyProjectTasksError,
    ProjectMutationError,
    ProjectNotFoundError,
    TaskMutationError,
    TaskNotFoundError,
    complete_task as complete_task_service,
    create_task as create_task_service,
    delete_task as delete_task_service,
    delete_project_and_tasks,
    list_project_summaries,
    list_tasks as list_tasks_service,
    parse_task_status,
    resolve_project_identifier,
    prepare_project_start,
    start_task as start_task_service,
)
from penguin.cli.config_commands import bind_config_commands
from penguin.cli.coordination_commands import bind_coordination_commands
from penguin.cli.environment import (
    preconfigure_cli_environment,
    set_cli_workspace_path,
)
from penguin.cli.extension_commands import bind_extension_commands
from penguin.cli.interface import PenguinInterface
from penguin.cli.interactive import PenguinCLI
from penguin.cli.model_runtime import (
    project_reasoning_config as _project_reasoning_config,
    resolve_reasoning_config as _resolve_cli_reasoning_config,
)
from penguin.cli.output_policy import render_direct_prompt, render_runmode_completion
from penguin.cli.presentation import print_ascii_banner as _print_ascii_banner
from penguin.cli.project_commands import bind_project_commands
from penguin.cli.run_dispatch import (
    DispatchMode,
    DispatchRequest,
    execute_direct_prompt,
    execute_run_mode,
    resolve_session,
    select_dispatch_mode,
)
from penguin.config import (
    DEFAULT_MODEL,
    DEFAULT_PROVIDER,
    GITHUB_REPOSITORY,
    WORKSPACE_PATH,
    Config,  # Import Config type for type hinting
    config as penguin_config_global,
    _ensure_env_loaded,  # Lazy env loading for startup performance
)
from penguin.core import PenguinCore
from penguin.llm.api_client import APIClient
from penguin.llm.model_config import ModelConfig
from penguin.project.spec_parser import parse_project_specification_from_markdown
from penguin.project.task_executor import ProjectTaskExecutor
from penguin.project.validation_manager import ValidationManager
from penguin.project.workflow_orchestrator import WorkflowOrchestrator
from penguin.run_mode import RunMode  # We will mock this but need the type for spec
from penguin.system.state import MessageCategory, parse_iso_datetime
from penguin.system.conversation_menu import ConversationMenu, ConversationSummary
from penguin.system_prompt import SYSTEM_PROMPT
from penguin.tools import ToolManager
from penguin.utils.log_error import log_error
from penguin.utils.logs import setup_logger

# Default to a quieter root logger unless explicitly overridden
DEFAULT_LOG_LEVEL = os.getenv("PENGUIN_LOG_LEVEL", "WARNING").upper()
try:
    logging.getLogger().setLevel(getattr(logging, DEFAULT_LOG_LEVEL, logging.WARNING))
except Exception:
    logging.getLogger().setLevel(logging.WARNING)

# Import unified command system
from penguin.cli.commands import CommandRegistry
from penguin.cli.typer_bridge import TyperBridge, integrate_with_existing_app
from penguin.cli.renderer import UnifiedRenderer, RenderStyle
from penguin.cli.streaming_display import StreamingDisplay
from penguin.cli.event_manager import EventManager
from penguin.cli.events import EventBus, EventType
from penguin.cli.session_manager import SessionManager
from penguin.cli.display_manager import DisplayManager
from penguin.cli.streaming_manager import StreamingManager

try:
    # Prefer relative import to support repo and installed layouts
    from ..multi.coordinator import MultiAgentCoordinator  # type: ignore
except Exception:
    MultiAgentCoordinator = None  # type: ignore
from penguin.project.git_manager import GitManager

# Add better import error handling for setup functions
setup_available = True
setup_import_error = None

try:
    from penguin.setup import (
        check_config_completeness,
        check_first_run,
        run_setup_wizard_sync,
    )
except ImportError as e:
    setup_available = False
    setup_import_error = str(e)
    logger = logging.getLogger(__name__)
    logger.warning(f"Setup wizard not available due to missing dependencies: {e}")

    # Provide fallback functions
    def check_first_run() -> bool:
        """Fallback: always return False if setup is not available"""
        return False

    def run_setup_wizard_sync() -> Dict[str, Any]:
        """Fallback: return error message"""
        return {"error": f"Setup wizard not available: {setup_import_error}"}

    def check_config_completeness() -> bool:
        """Fallback: assume config is complete if setup unavailable"""
        return True


app = typer.Typer(
    help="Penguin AI Assistant - Your command-line AI companion.\n"
    "Run with -p/--prompt for non-interactive mode, or with a subcommand (e.g., 'chat').\n"
    "If no prompt or subcommand is given, starts an interactive CLI chat session.\n"
    "For experimental TUI, use: penguin-tui-proto"
)
console = RichConsole()  # Use the renamed import
logger = setup_logger("penguin_cli.log")  # Setup a logger for the CLI module

# Project management sub-application
project_app = typer.Typer(help="Project and task management commands")
app.add_typer(project_app, name="project")

# Messaging sub-application (Phase 3 demo)
msg_app = typer.Typer(help="Message routing helpers: send to agents or human")
app.add_typer(msg_app, name="msg")

# Coordinator sub-application (Phase 4 preview)
coord_app = typer.Typer(help="Multi-agent coordinator commands")
app.add_typer(coord_app, name="coord")

# Agent management sub-application
agent_app = typer.Typer(help="Agent management commands")
app.add_typer(agent_app, name="agent")

# Define a type variable for better typing
# Configuration sub-application
config_app = typer.Typer(help="Configuration management commands")
app.add_typer(config_app, name="config")

# Skills sub-application
skill_app = typer.Typer(help="Agent Skills discovery and activation commands")
app.add_typer(skill_app, name="skill")

# MCP host diagnostics and lifecycle controls
mcp_app = typer.Typer(help="MCP server diagnostics and lifecycle commands")
app.add_typer(mcp_app, name="mcp")

T = TypeVar("T")

# Global core components - initialized by _initialize_core_components_globally
_core: Optional[PenguinCore] = None
_interface: Optional[PenguinInterface] = None
_model_config: Optional[ModelConfig] = None
_api_client: Optional[APIClient] = None
_tool_manager: Optional[ToolManager] = None

# Initialize command registry and integrate with app
_command_registry = CommandRegistry.get_instance()
integrate_with_existing_app(app)
_loaded_config: Optional[Union[Dict[str, Any], Config]] = (
    None  # Global config can be dict or Config
)
_interactive_session_manager: Optional[Any] = None  # For PenguinCLI instance


def _ensure_config_compatible(config_data: Any) -> Any:
    """
    Ensure the config is compatible with PenguinCore expectations.
    If it's a dictionary, wrap it with attribute-like access.
    """
    if isinstance(config_data, dict):
        # Create a simple object that wraps the dictionary with attribute access
        class ConfigWrapper:
            def __init__(self, data):
                self._data = data

                # Add diagnostics attribute if not present
                if "diagnostics" not in data:
                    data["diagnostics"] = {"enabled": False}

            def __getattr__(self, name):
                if name in self._data:
                    value = self._data[name]
                    if isinstance(value, dict):
                        return ConfigWrapper(value)
                    return value
                raise AttributeError(
                    f"'{self.__class__.__name__}' object has no attribute '{name}'"
                )

            # Support dictionary-like access too
            def get(self, key, default=None):
                return self._data.get(key, default)

            def __contains__(self, key):
                return key in self._data

        return ConfigWrapper(config_data)
    return config_data


async def _initialize_core_components_globally(
    model_override: Optional[str] = None,
    workspace_override: Optional[Path] = None,
    no_streaming_override: bool = False,
    fast_startup_override: bool = False,
):
    global _core, _interface, _model_config, _api_client, _tool_manager, _loaded_config

    if _core is not None:
        logger.debug("Core components already initialized globally.")
        # Here you could add logic to update components if overrides change,
        # e.g., if model_override is different from _model_config.model.
        # For now, first initialization is sticky for simplicity.
        return

    result = bootstrap_cli(
        model_override=model_override,
        workspace_override=workspace_override,
        no_streaming_override=no_streaming_override,
        fast_startup_override=fast_startup_override,
    )
    _core = result.core
    _interface = result.interface
    _model_config = result.model_config
    _api_client = result.api_client
    _tool_manager = result.tool_manager
    _loaded_config = result.loaded_config

    # Publish compatibility state only after every dependency was constructed.
    _command_registry.set_core(_core)


async def _initialize_command_runtime(**kwargs: Any) -> None:
    """Late-bound initializer used by extracted command registrars."""

    await _initialize_core_components_globally(**kwargs)


async def _run_penguin_direct_prompt(prompt_text: str, output_format: str) -> None:
    """Compatibility facade for extracted direct-prompt execution."""
    global _core
    if not _core:
        await _initialize_core_components_globally()
    if not _core:
        console.print("[red]Error: Core components failed to initialize.[/red]")
        raise typer.Exit(code=1)

    try:
        stdin_is_tty = sys.stdin.isatty()
        stdin_text = None if stdin_is_tty else sys.stdin.read()
        outcome = await execute_direct_prompt(
            _core,
            prompt_text=prompt_text,
            output_format=output_format,
            stdin_text=stdin_text,
            stdin_is_tty=stdin_is_tty,
        )
    except ValueError as exc:
        console.print(f"[red]Error: {exc}[/red]")
        raise typer.Exit(code=1)
    render_direct_prompt(console, outcome)


async def _get_skill_manager_for_cli(workspace: Optional[Path] = None):
    """Initialize Penguin and return the runtime SkillManager for CLI commands."""
    await _initialize_core_components_globally(workspace_override=workspace)
    manager = None
    if _core is not None:
        conversation_manager = getattr(_core, "conversation_manager", None)
        manager = getattr(conversation_manager, "skill_manager", None)
    if manager is None and _tool_manager is not None:
        manager = getattr(_tool_manager, "skill_manager", None)
    if manager is None:
        console.print("[red]Error: Skill manager not available[/red]")
        raise typer.Exit(code=1)
    manager.refresh()
    return manager


globals().update(
    bind_extension_commands(
        skill_app,
        mcp_app,
        lambda workspace=None: _get_skill_manager_for_cli(workspace),
        lambda: _tool_manager,
        lambda: console,
    )
)


async def _run_interactive_chat():
    """Launch the interactive CLI chat session with PenguinCLI."""
    global _core, _interface, _interactive_session_manager
    if not _core or not _interface:
        logger.error("Core or Interface not initialized for interactive chat.")
        # Attempt to initialize if called directly
        await _initialize_core_components_globally()
        if not _core or not _interface:
            console.print("[red]Error: Core components failed to initialize for interactive chat.[/red]")
            raise typer.Exit(code=1)

    if _interactive_session_manager is None:
        # PenguinCLI class is defined later in this file.
        # It takes `core` and its __init__ creates `PenguinInterface(core)`.
        _interactive_session_manager = PenguinCLI(_core)
    
    # The chat_loop should handle its own Rich Live context if needed.
    await _interactive_session_manager.chat_loop()


# Store the original app.callback to restore if needed, or adjust for Typer's intended use.
# Typer allows only one app.callback.
_previous_main_callback = app.registered_callback


def _set_cli_workspace_path(workspace_path: Union[str, Path]) -> Path:
    """Compatibility wrapper for extracted workspace normalization."""
    global WORKSPACE_PATH
    resolved_workspace = set_cli_workspace_path(workspace_path)
    WORKSPACE_PATH = resolved_workspace
    return resolved_workspace


def _preconfigure_cli_environment(
    workspace: Optional[Path],
    project: Optional[str],
    root: Optional[str],
) -> Tuple[Optional[Path], Path]:
    """Compatibility wrapper for extracted environment normalization."""
    global WORKSPACE_PATH
    result = preconfigure_cli_environment(
        workspace,
        project,
        root,
        default_workspace=WORKSPACE_PATH,
    )
    WORKSPACE_PATH = result[1]
    return result


@app.callback(invoke_without_command=True)
def main_entry(
    ctx: typer.Context,
    prompt: Optional[str] = typer.Option(
        None,
        "-p",
        "--prompt",
        help="Run in non-interactive mode. Use '-' to read prompt from stdin.",
    ),
    output_format: str = typer.Option(
        "text",
        "--output-format",
        help="Output format for -p mode (text, json, stream-json).",
        case_sensitive=False,
        # autocompletion=lambda: ["text", "json", "stream-json"] # Requires Typer 0.9+
    ),
    continue_last: bool = typer.Option(
        False, "--continue", "-c", help="Continue the most recent conversation."
    ),
    resume_session: Optional[str] = typer.Option(
        None, "--resume", help="Resume a specific conversation by its session ID."
    ),
    run_task: Optional[str] = typer.Option(
        None, "--run", help="Start autonomous execution for a specific task or project target."
    ),
    continuous: bool = typer.Option(
        False,
        "--247",
        "--continuous",
        help="Run continuously (24/7 mode). Project-scoped runs work the ready frontier and may stop honestly when no tasks are ready; non-project runs may continue exploratorily by determining next steps.",
    ),
    time_limit: Optional[int] = typer.Option(
        None,
        "--time-limit",
        help="Cap run duration in minutes when explicitly provided here. This does not imply blueprint/task-defined time limits are surfaced in the CLI yet.",
    ),
    task_description: Optional[str] = typer.Option(
        None,
        "--description",
        help="Optional description for the task when using --run.",
    ),
    model: Optional[str] = typer.Option(
        None,
        "--model",
        "-m",
        help="Specify the model to use (e.g., 'anthropic/claude-3-5-sonnet-20240620'). Overrides config.",
    ),
    workspace: Optional[Path] = typer.Option(
        None, "--workspace", "-w", help="Set custom workspace path. Overrides config."
    ),
    no_streaming: bool = typer.Option(
        False,
        "--no-streaming",
        help="Disable streaming mode for LLM responses (primarily for interactive mode).",
    ),
    fast_startup: bool = typer.Option(
        False,
        "--fast-startup",
        help="Enable fast startup mode (defer memory indexing until first use).",
    ),
    # Add other global options from the plan here eventually
    # e.g., continue_session, resume_session_id, system_prompt_override, etc.
    project: Optional[str] = typer.Option(
        None,
        "--project",
        help="Route tasks to a project; if omitted, tasks are independent",
    ),
    root: Optional[str] = typer.Option(
        None,
        "--root",
        help="Execution root for file ops and commands: 'project' (default) or 'workspace'",
    ),
    version: Optional[bool] = typer.Option(
        None, "--version", "-V", help="Show Penguin version and exit.", is_eager=True
    ),
):
    """
    Penguin AI Assistant - Your command-line AI companion.
    """
    if version:
        console.print(f"Penguin {__version__}")
        raise typer.Exit()

    # Preconfigure environment for root/project overrides so that even
    # early-return paths (e.g. launching the TUI) honour the requested roots.
    resolved_project_path, _resolved_workspace = _preconfigure_cli_environment(
        workspace=workspace,
        project=project,
        root=root,
    )

    if root:
        root_mode = root.lower()
        if root_mode not in ("project", "workspace"):
            console.print(
                f"[yellow]Warning: unknown root '{root}'. Expected 'project' or 'workspace'.[/yellow]"
            )

    # Explicit subcommands initialize their own dependencies. Returning here also
    # keeps command-group help and metadata paths provider-free.
    if ctx.invoked_subcommand is not None:
        return

    # Create a sync wrapper around our async code
    async def _async_init_and_run():
        # Check if setup is needed before initializing core components
        if not setup_available:
            console.print(
                f"[yellow]⚠️ Setup wizard not available: {setup_import_error}[/yellow]"
            )
            console.print(
                "[yellow]You may need to install additional dependencies:[/yellow]"
            )
            console.print("[yellow]  pip install questionary PyYAML rich[/yellow]")
            console.print("[yellow]Or manually create a config file.[/yellow]\n")
        elif check_first_run():
            console.print(
                "[bold yellow]🐧 Welcome to Penguin! First-time setup is required.[/bold yellow]"
            )
            console.print("Running setup wizard...\n")

            try:
                config_result = run_setup_wizard_sync()
                if config_result:
                    if "error" in config_result:
                        console.print(
                            f"[red]Setup error: {config_result['error']}[/red]"
                        )
                        console.print(
                            "Try running 'penguin config setup' manually or check dependencies."
                        )
                        raise typer.Exit(code=1)
                    else:
                        console.print(
                            "[bold green]Setup completed successfully![/bold green]"
                        )
                        # Re-read config after setup to pick up user-selected model
                        from penguin.config import Config
                        globals()['_loaded_config'] = Config.load_config()
                        # Update DEFAULT_MODEL from fresh config
                        if hasattr(globals()['_loaded_config'], 'model_config'):
                            _mc = globals()['_loaded_config'].model_config
                            if _mc:
                                globals()['DEFAULT_MODEL'] = getattr(_mc, 'model', 'openai/gpt-5')
                                globals()['DEFAULT_PROVIDER'] = getattr(_mc, 'provider', 'openai')
                        console.print("Starting Penguin...\n")
                else:
                    console.print(
                        "[yellow]Setup was cancelled. Run 'penguin config setup' when ready.[/yellow]"
                    )
                    raise typer.Exit(code=0)
            except KeyboardInterrupt:
                console.print(
                    "\n[yellow]Setup interrupted. Run 'penguin config setup' when ready.[/yellow]"
                )
                raise typer.Exit(code=0)
            except Exception as e:
                console.print(f"[red]Setup failed: {e}[/red]")
                console.print("You can try running 'penguin config setup' manually.")
                console.print(f"[dim]Error details: {traceback.format_exc()}[/dim]")
                raise typer.Exit(code=1)

        # Initialize core components once, passing global CLI options as overrides
        try:
            await _initialize_core_components_globally(
                model_override=model,
                workspace_override=workspace,
                no_streaming_override=no_streaming,
                fast_startup_override=fast_startup,
            )
        except Exception as e:
            logger.error(
                f"Fatal error during core component initialization: {e}", exc_info=True
            )
            console.print(f"[bold red]Fatal Initialization Error:[/bold red] {e}")
            console.print("Please check logs for more details.")
            raise typer.Exit(code=1)

        global _tool_manager

        if isinstance(output_format, str) and output_format.lower() == "text":
            _print_ascii_banner(console)

        logger.info(
            "CLI args resolved: root=%s project=%s prompt=%s run_task=%s",
            root,
            project,
            bool(prompt),
            run_task,
        )
        try:
            console.print(
                f"[dim]CLI args resolved root={root} project={project} prompt={'set' if prompt else 'none'} run={run_task}[/dim]"
            )
        except Exception:
            pass

        # Bind tool manager to the requested project workspace, if provided
        if project:
            try:
                project_path_override: Optional[Path] = None
                pm = getattr(_core, "project_manager", None)
                if pm:
                    try:
                        project_obj = await pm.get_project_async(project)
                    except Exception:
                        project_obj = None
                    if not project_obj:
                        loop = asyncio.get_running_loop()
                        project_obj = await loop.run_in_executor(
                            None, pm.get_project_by_name, project
                        )
                    if not project_obj:
                        loop = asyncio.get_running_loop()
                        project_obj = await loop.run_in_executor(
                            None, pm.get_project, project
                        )
                    if project_obj and getattr(project_obj, "workspace_path", None):
                        project_path_override = Path(project_obj.workspace_path)

                if project_path_override is None:
                    candidate = (
                        Path(_tool_manager.workspace_root) / "projects" / project
                    )
                    if candidate.exists():
                        project_path_override = candidate
                    else:
                        direct = Path(project).expanduser()
                        if direct.exists():
                            project_path_override = direct

                if project_path_override is not None:
                    msg = _tool_manager.set_project_root(project_path_override)
                    console.print(f"[dim]{msg}[/dim]")
                else:
                    console.print(
                        f"[yellow]Warning: could not resolve project '{project}' workspace; using default root.[/yellow]"
                    )
            except Exception as e:
                console.print(
                    f"[yellow]Warning: failed to configure project root '{project}': {e}[/yellow]"
                )

        # Apply execution root toggle if requested
        if root:
            try:
                msg = _tool_manager.set_execution_root(root)
                console.print(f"[dim]{msg}[/dim]")
            except Exception as e:
                console.print(
                    f"[yellow]Warning: failed to set execution root: {e}[/yellow]"
                )

        # Log the resolved roots for diagnostics
        try:
            logger.info(
                "CLI ToolManager id=%s mode=%s file_root=%s project_root=%s workspace_root=%s",
                hex(id(_tool_manager)) if _tool_manager else None,
                getattr(_tool_manager, "file_root_mode", None),
                getattr(_tool_manager, "_file_root", None),
                getattr(_tool_manager, "project_root", None),
                getattr(_tool_manager, "workspace_root", None),
            )
        except Exception:
            pass

        # Always show the current execution root for clarity
        try:
            console.print(
                f"[dim]Execution root: {_tool_manager.file_root_mode} ({_tool_manager._file_root})[/dim]"
            )
        except Exception:
            pass

        # Show current model/provider/adapter for visibility
        try:
            adapter_name = (
                _api_client.client_handler.__class__.__name__
                if _api_client and getattr(_api_client, "client_handler", None)
                else "unknown"
            )
            console.print(
                f"[dim]Model: {_model_config.provider}/{_model_config.model} via {_model_config.client_preference} ({adapter_name})[/dim]"
            )
        except Exception:
            logger.debug("Unable to display model/adapter info", exc_info=True)

        # Record project flag for downstream commands
        ctx.obj = ctx.obj or {}
        ctx.obj["project"] = project

        dispatch_mode = select_dispatch_mode(
            DispatchRequest(
                run_task=run_task,
                continue_last=continue_last,
                resume_session=resume_session,
                prompt=prompt,
                continuous=continuous,
                invoked_subcommand=ctx.invoked_subcommand,
            )
        )
        if dispatch_mode is DispatchMode.RUN_MODE:
            await _handle_run_mode(run_task, continuous, time_limit, task_description)
        elif dispatch_mode is DispatchMode.SESSION:
            if prompt is not None:
                await _handle_session_management(
                    continue_last, resume_session, prompt, output_format
                )
            else:
                await _handle_session_management(continue_last, resume_session)
        elif dispatch_mode is DispatchMode.DIRECT_PROMPT:
            await _run_penguin_direct_prompt(prompt, output_format)
        elif dispatch_mode is DispatchMode.CONTINUOUS:
            await _handle_run_mode(None, continuous, time_limit, task_description)
        elif dispatch_mode is DispatchMode.INTERACTIVE:
            await _run_interactive_chat()
        # Else: a subcommand was invoked (e.g., `penguin chat`, `penguin profile`).
        # Typer will handle calling the subcommand.

    # Run the async function in the current thread
    # Run the async function in the current thread
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        # If we are in a running loop (e.g. Jupyter, other async app), we need nest_asyncio
        try:
            import nest_asyncio
            nest_asyncio.apply()
            asyncio.run(_async_init_and_run())
        except ImportError:
            console.print("[bold red]Error: Async event loop already running.[/bold red]")
            console.print("If you are running this from a notebook or another async app,")
            console.print("please install 'nest_asyncio' or use the async API directly.")
            raise typer.Exit(code=1)
    else:
        asyncio.run(_async_init_and_run())



async def _handle_session_management(
    continue_last: bool,
    resume_session: Optional[str],
    prompt: Optional[str] = None,
    output_format: str = "text",
) -> None:
    """Compatibility facade for extracted session resolution."""
    if not _core:
        console.print("[red]Error: Core not initialized[/red]")
        return

    try:
        resolution = resolve_session(
            _core,
            continue_last=continue_last,
            resume_session=resume_session,
        )
    except Exception as exc:
        console.print(f"[red]Error resolving session: {exc}[/red]")
        return

    if resolution.kind == "resumed":
        console.print(f"[green]Resumed session: {resolution.session_id}[/green]")
    elif resolution.kind == "continued":
        console.print(f"[green]Continued last session: {resolution.session_id}[/green]")
    elif resolution.kind == "fresh":
        console.print("[yellow]No previous session found. Starting fresh.[/yellow]")

    if prompt:
        await _run_penguin_direct_prompt(prompt, output_format)
    else:
        await PenguinCLI(_core).chat_loop()




async def _handle_run_mode(
    task_name: Optional[str],
    continuous: bool,
    time_limit: Optional[int] = None,
    description: Optional[str] = None,
) -> None:
    """Compatibility facade for the extracted RunMode dispatch service."""
    if not _core:
        logger.error("Core not initialized for run mode.")
        console.print(
            "[red]Error: Core components failed to initialize for run mode.[/red]"
        )
        raise typer.Exit(code=1)

    try:
        completion = await execute_run_mode(
            _core,
            console,
            task_name=task_name,
            continuous=continuous,
            time_limit=time_limit,
            description=description,
        )
        render_runmode_completion(console, completion)
    except ValueError as exc:
        console.print(f"[yellow]{exc}[/yellow]")
        raise typer.Exit(code=1)
    except KeyboardInterrupt:
        console.print(
            "\\n[yellow]Keyboard interrupt received. Gracefully shutting down...[/yellow]"
        )
    except Exception as exc:
        logger.error("Error in run mode execution: %s", exc, exc_info=True)
        console.print(f"[red]Error running task: {exc!s}[/red]")
        console.print(traceback.format_exc())


# Config command implementations are bound after permissions_app is registered.
permissions_app = typer.Typer(name="permissions", help="Permission and security management")
app.add_typer(permissions_app, name="permissions")


globals().update(
    bind_config_commands(
        config_app,
        permissions_app,
        console,
        setup_available=setup_available,
        setup_import_error=setup_import_error,
        run_setup_wizard_sync=run_setup_wizard_sync,
        check_config_completeness=check_config_completeness,
        check_first_run=check_first_run,
    )
)
globals().update(
    bind_agent_commands(
        agent_app,
        _initialize_core_components_globally,
        lambda: _core,
        console,
    )
)
globals().update(
    bind_project_commands(
        project_app,
        _initialize_command_runtime,
        lambda: _core,
        lambda: WORKSPACE_PATH,
        lambda: console,
    )
)


globals().update(
    bind_coordination_commands(
        msg_app,
        coord_app,
        _initialize_command_runtime,
        lambda: _core,
        lambda: console,
        lambda: MultiAgentCoordinator,
    )
)


@app.command()
async def chat():  # Removed model, workspace, no_streaming options
    """Start an interactive chat session with Penguin."""
    global _core  # Ensure we're referring to the global
    if not _core:
        # This should ideally be caught by main_entry's initialization.
        # If `penguin chat` is called directly, main_entry runs first.
        logger.warning(
            "Chat command invoked, but core components appear uninitialized. main_entry should handle this."
        )
        # Attempting to initialize with defaults if somehow missed.
        try:
            await _initialize_core_components_globally()
        except Exception as e:
            logger.error(
                f"Error re-initializing core for chat command: {e}", exc_info=True
            )
            console.print(
                f"[red]Error: Core components failed to initialize for chat: {e}[/red]"
            )
            raise typer.Exit(code=1)

        if not _core:  # Still not initialized after attempt
            console.print(
                "[red]Critical Error: Core components could not be initialized.[/red]"
            )
            raise typer.Exit(code=1)

    await _run_interactive_chat()


# Profile command remains largely the same, ensure it uses `console` correctly
@app.command()
def perf_test(
    iterations: int = typer.Option(
        3, "--iterations", "-i", help="Number of test iterations to run"
    ),
    show_report: bool = typer.Option(
        True, "--show-report/--no-report", help="Show detailed performance report"
    ),
):
    """
    Run startup performance benchmarks to compare normal vs fast startup modes.
    """

    async def _async_perf_test():
        import time

        from penguin.utils.profiling import (
            enable_profiling,
            print_startup_report,
            reset_profiling,
        )

        console.print("[bold blue]🚀 Penguin Startup Performance Test[/bold blue]")
        console.print("=" * 60)

        enable_profiling()

        normal_times = []
        fast_times = []

        for iteration in range(iterations):
            console.print(f"\n[yellow]Iteration {iteration + 1}/{iterations}[/yellow]")

            # Test normal startup
            console.print("  Testing normal startup...")
            reset_profiling()
            start_time = time.perf_counter()

            try:
                from penguin.core import PenguinCore

                core_normal = await PenguinCore.create(
                    fast_startup=False, show_progress=False
                )
                normal_time = time.perf_counter() - start_time
                normal_times.append(normal_time)
                console.print(f"    ✓ Normal startup: {normal_time:.4f}s")

                # Clean up
                if hasattr(core_normal, "reset_state"):
                    await core_normal.reset_state()
                del core_normal

            except Exception as e:
                console.print(f"    ✗ Normal startup failed: {e}")
                normal_times.append(float("inf"))

            # Test fast startup
            console.print("  Testing fast startup...")
            reset_profiling()
            start_time = time.perf_counter()

            try:
                from penguin.core import PenguinCore

                core_fast = await PenguinCore.create(
                    fast_startup=True, show_progress=False
                )
                fast_time = time.perf_counter() - start_time
                fast_times.append(fast_time)
                console.print(f"    ✓ Fast startup: {fast_time:.4f}s")

                # Clean up
                if hasattr(core_fast, "reset_state"):
                    await core_fast.reset_state()
                del core_fast

            except Exception as e:
                console.print(f"    ✗ Fast startup failed: {e}")
                fast_times.append(float("inf"))

        # Calculate statistics
        valid_normal = [t for t in normal_times if t != float("inf")]
        valid_fast = [t for t in fast_times if t != float("inf")]

        console.print(
            f"\n[bold blue]📊 Performance Results ({iterations} iterations)[/bold blue]"
        )
        console.print("=" * 60)

        if valid_normal and valid_fast:
            avg_normal = sum(valid_normal) / len(valid_normal)
            avg_fast = sum(valid_fast) / len(valid_fast)

            improvement = ((avg_normal - avg_fast) / avg_normal) * 100
            speedup = avg_normal / avg_fast if avg_fast > 0 else float("inf")

            console.print(
                f"Normal startup:  {avg_normal:.4f}s avg (range: {min(valid_normal):.4f}s - {max(valid_normal):.4f}s)"
            )
            console.print(
                f"Fast startup:    {avg_fast:.4f}s avg (range: {min(valid_fast):.4f}s - {max(valid_fast):.4f}s)"
            )
            console.print("")
            console.print(
                f"Performance improvement: [bold green]{improvement:.1f}% faster[/bold green]"
            )
            console.print(f"Speedup factor: [bold green]{speedup:.2f}x[/bold green]")

            if improvement > 0:
                console.print(
                    "\n[bold green]🎉 Fast startup mode is working![/bold green]"
                )
            else:
                console.print(
                    "\n[bold yellow]⚠️ Fast startup mode might not be working as expected[/bold yellow]"
                )
        else:
            console.print(
                "[red]Could not complete performance tests due to errors[/red]"
            )

        if show_report:
            console.print("\n[bold blue]📈 Detailed Performance Report[/bold blue]")
            print_startup_report()

    asyncio.run(_async_perf_test())


@app.command()
def profile(
    output_file: str = typer.Option(
        "penguin_profile",
        "--output",
        "-o",
        help="Output file name for profile data (without extension)",
    ),
    view: bool = typer.Option(
        False, "--view", "-v", help="Open the profile visualization after saving"
    ),
):
    """
    Start Penguin with profiling enabled to analyze startup performance.
    Results are saved for later analysis with tools like snakeviz.
    """
    import cProfile
    import io
    import pstats

    # from pathlib import Path # Already imported
    import subprocess
    # import sys # Already imported

    # Create a profile directory if it doesn't exist
    profile_dir = Path("profiles")
    profile_dir.mkdir(exist_ok=True)

    # Prepare the output file name
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    actual_output_file = (
        output_file
        if output_file != "penguin_profile"
        else f"penguin_profile_{timestamp}"
    )

    output_path = profile_dir / f"{actual_output_file}.prof"
    stats_path = profile_dir / f"{actual_output_file}.txt"

    console.print("[bold blue]Starting Penguin with profiling enabled...[/bold blue]")
    console.print(f"Profile data will be saved to: [cyan]{output_path}[/cyan]")

    def run_profiled_penguin_interactive():
        # This will now go through the main_entry, which initializes and runs interactive.
        # We need to simulate running `penguin` command itself.
        # For profiling, it's better to profile the actual `app()` call or a specific async function.
        # Let's profile the `_run_interactive_chat` after components are initialized.
        async def profiled_interactive_session():
            await _initialize_core_components_globally()  # Ensure init
            await _run_interactive_chat()

        try:
            asyncio.run(profiled_interactive_session())
        except KeyboardInterrupt:
            console.print(
                "[yellow]Penguin interactive session interrupted by user during profiling.[/yellow]"
            )
        except SystemExit:  # Catch typer.Exit
            console.print(
                "[yellow]Penguin exited during profiling (SystemExit).[/yellow]"
            )
        except Exception as e:
            console.print(f"[red]Error during profiled interactive run: {e!s}[/red]")
            logger.error(f"Profiling error: {e}", exc_info=True)

    profiler = cProfile.Profile()
    profiler.enable()

    run_profiled_penguin_interactive()  # Call the modified function

    profiler.disable()
    console.print("[green]Profiling complete.[/green]")

    profiler.dump_stats(str(output_path))
    console.print(f"Profile data saved to: [cyan]{output_path}[/cyan]")

    s = io.StringIO()
    # Sort by cumulative time, then standard name for consistent ordering
    ps = pstats.Stats(profiler, stream=s).sort_stats("cumulative", "name")
    ps.print_stats(30)  # Print top 30 functions
    stats_content = s.getvalue()

    with open(stats_path, "w") as f:
        f.write(stats_content)

    console.print(f"Profile summary saved to: [cyan]{stats_path}[/cyan]")
    console.print("[bold]Top 30 functions by cumulative time:[/bold]")
    console.print(stats_content)

    if view:
        try:
            subprocess.run(["snakeviz", str(output_path)], check=True)
        except FileNotFoundError:
            console.print(
                "[yellow]snakeviz command not found. Please install snakeviz to view profiles.[/yellow]"
            )
            console.print(
                f"[yellow]You can manually visualize the profile with: snakeviz {output_path}[/yellow]"
            )
        except Exception as e:
            console.print(f"[yellow]Could not open visualization: {e!s}[/yellow]")
            console.print(
                f"[yellow]You can manually visualize the profile with: snakeviz {output_path}[/yellow]"
            )

    console.print("[bold green]Profiling session ended.[/bold green]")
    console.print(f"[dim]To visualize: snakeviz {output_path}[/dim]")


# Duplicate chat command disabled
# @app.command()
# async def chat_duplicate_disabled():  # deprecated duplicate chat, kept for reference but unused

if __name__ == "__main__":
    # This makes Typer process the CLI arguments and call the appropriate function.
    # For async callbacks, we need to wrap app() with asyncio.run
    try:
        asyncio.run(app())
    except Exception as e:  # Catch any unhandled exceptions from Typer/asyncio layers
        logger.critical(f"Unhandled exception at CLI entry point: {e}", exc_info=True)
        console.print(f"[bold red]Unhandled Critical Error:[/bold red] {e}")
        console.print("This is unexpected. Please check logs or report this issue.")
        sys.exit(1)
