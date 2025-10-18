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
    total_start = time.time()
    module_times = {}

    def time_import(module_name):
        start = time.time()
        result = __import__(module_name, globals(), locals(), [], 0)
        end = time.time()
        module_times[module_name] = (end - start) * 1000  # Convert to ms
        return result

    # Time major imports
    typer = time_import("typer")
    rich_console_import = time_import("rich.console")
    Console = rich_console_import.Console
    Markdown = time_import("rich.markdown").Markdown
    Panel = time_import("rich.panel").Panel
    Progress = time_import("rich.progress").Progress
    SpinnerColumn = time_import("rich.progress").SpinnerColumn
    TextColumn = time_import("rich.progress").TextColumn
    Syntax = time_import("rich.syntax").Syntax
    Live = time_import("rich.live").Live

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
    import rich  # type: ignore
    from prompt_toolkit import PromptSession  # type: ignore
    from prompt_toolkit.key_binding import KeyBindings  # type: ignore
    from prompt_toolkit.keys import Keys  # type: ignore
    from prompt_toolkit.styles import Style  # type: ignore
    from prompt_toolkit.formatted_text import HTML  # type: ignore

from penguin.cli.interface import PenguinInterface
from penguin.config import (
    DEFAULT_MODEL,
    DEFAULT_PROVIDER,
    GITHUB_REPOSITORY,
    WORKSPACE_PATH,
    Config,  # Import Config type for type hinting
    config as penguin_config_global,
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

# Import unified command system
from penguin.cli.commands import CommandRegistry
from penguin.cli.typer_bridge import TyperBridge, integrate_with_existing_app
from penguin.cli.renderer import UnifiedRenderer, RenderStyle

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

PENGUIN_ASCII_BANNER = r"""
ooooooooo.                                                 o8o              
`888   `Y88.                                               `"'              
 888   .d88'  .ooooo.  ooo. .oo.    .oooooooo oooo  oooo  oooo  ooo. .oo.   
 888ooo88P'  d88' `88b `888P"Y88b  888' `88b  `888  `888  `888  `888P"Y88b  
 888         888ooo888  888   888  888   888   888   888   888   888   888  
 888         888    .o  888   888  `88bod8P'   888   888   888   888   888  
o888o        `Y8bod8P' o888o o888o `8oooooo.   `V88V"V8P' o888o o888o o888o 
                                   d"     YD                                
                                   "Y88888P'                                
          """

_banner_printed = False


def _print_ascii_banner(console_obj: RichConsole, *, force: bool = False) -> None:
    """Print the Penguin ASCII banner once per process unless forced."""
    global _banner_printed
    if _banner_printed and not force:
        return
    console_obj.print(PENGUIN_ASCII_BANNER, style="bold cyan")
    _banner_printed = True
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

    logger.info("Initializing core components globally...")
    init_start_time = time.time()

    _loaded_config = penguin_config_global  # Use the imported config

    effective_workspace = (
        workspace_override or WORKSPACE_PATH
    )  # WORKSPACE_PATH from penguin.config
    logger.debug(f"Effective workspace path for global init: {effective_workspace}")
    # Note: PenguinCore itself uses WORKSPACE_PATH from config for ProjectManager.
    # A more direct way to override this in Core would be needed if ProjectManager path needs to change.

    # Access _loaded_config as a dictionary or using property access
    streaming_enabled = not no_streaming_override

    # Try both attribute-style and dict-style access to handle different Config implementations
    if hasattr(_loaded_config, "model") and callable(
        getattr(_loaded_config, "model", None)
    ):
        # Config.model() returns a dict-like object
        model_dict = _loaded_config.model()
        streaming_enabled = not no_streaming_override and model_dict.get(
            "streaming_enabled", True
        )
    elif hasattr(_loaded_config, "model") and not callable(
        getattr(_loaded_config, "model", None)
    ):
        # Config.model is a property that returns a dict-like object
        model_dict = _loaded_config.model
        streaming_enabled = not no_streaming_override and model_dict.get(
            "streaming_enabled", True
        )
    elif isinstance(_loaded_config, dict) and "model" in _loaded_config:
        # _loaded_config is a dict with a model key
        streaming_enabled = not no_streaming_override and _loaded_config["model"].get(
            "streaming_enabled", True
        )

    # Create ModelConfig with safe access
    if hasattr(_loaded_config, "model") and callable(
        getattr(_loaded_config, "model", None)
    ):
        # Model is a method that returns a dict-like object
        model_dict = _loaded_config.model()
        api_dict = getattr(_loaded_config, "api", {})
        if isinstance(api_dict, dict):
            api_base = api_dict.get("base_url")
        else:
            api_base = getattr(api_dict, "base_url", None)
    elif hasattr(_loaded_config, "model") and not callable(
        getattr(_loaded_config, "model", None)
    ):
        # Model is a property that returns a dict-like object
        model_dict = _loaded_config.model
        api_dict = getattr(_loaded_config, "api", {})
        if isinstance(api_dict, dict):
            api_base = api_dict.get("base_url")
        else:
            api_base = getattr(api_dict, "base_url", None)
    elif isinstance(_loaded_config, dict):
        # Direct dictionary access
        model_dict = _loaded_config.get("model", {})
        api_dict = _loaded_config.get("api", {})
        api_base = api_dict.get("base_url") if isinstance(api_dict, dict) else None
    else:
        # Fallback for unknown config type
        model_dict = {}
        api_base = None

    _model_config = ModelConfig(
        model=model_override or model_dict.get("default", DEFAULT_MODEL),
        provider=model_dict.get("provider", DEFAULT_PROVIDER),
        api_base=api_base,  # Use the api_base we determined above
        client_preference=model_dict.get("client_preference", "native"),
        streaming_enabled=streaming_enabled,
        vision_enabled=model_dict.get("vision_enabled", False),
        max_tokens=model_dict.get("max_tokens", 8000),
        temperature=model_dict.get("temperature", 0.7),
    )

    _api_client = APIClient(model_config=_model_config)
    _api_client.set_system_prompt(SYSTEM_PROMPT)

    # Determine fast startup setting from config or override
    config_fast_startup = False
    try:
        if hasattr(_loaded_config, "fast_startup"):
            config_fast_startup = _loaded_config.fast_startup
        elif isinstance(_loaded_config, dict):
            config_fast_startup = _loaded_config.get("performance", {}).get(
                "fast_startup", False
            )
    except Exception:
        pass

    effective_fast_startup = fast_startup_override or config_fast_startup

    # Convert config to dict format for ToolManager
    config_dict = (
        _loaded_config.__dict__
        if hasattr(_loaded_config, "__dict__")
        else _loaded_config
    )
    _tool_manager = ToolManager(
        config_dict, log_error, fast_startup=effective_fast_startup
    )

    # Make sure our config is compatible with what PenguinCore expects
    wrapped_config = _ensure_config_compatible(_loaded_config)

    # PenguinCore's __init__ will use its passed config to set up ProjectManager with WORKSPACE_PATH
    _core = PenguinCore(
        config=wrapped_config,
        api_client=_api_client,
        tool_manager=_tool_manager,
        model_config=_model_config,
    )
    # If workspace_override needs to directly influence PenguinCore's ProjectManager path,
    # PenguinCore would need to accept a workspace_path argument or have a setter.

    _interface = PenguinInterface(_core)

    # Set core on command registry for unified command handling
    _command_registry.set_core(_core)

    logger.info(
        f"Core components initialized globally in {time.time() - init_start_time:.2f}s"
    )


async def _run_penguin_direct_prompt(prompt_text: str, output_format: str):
    global _core
    if not _core:
        logger.error("Core not initialized for direct prompt execution.")
        # Attempt to initialize if called directly without main_entry doing it
        await _initialize_core_components_globally()
        if not _core:
            console.print("[red]Error: Core components failed to initialize.[/red]")
            raise typer.Exit(code=1)

    actual_prompt = ""
    if prompt_text == "-":
        if not sys.stdin.isatty():
            actual_prompt = sys.stdin.read().strip()
            logger.info("Reading prompt from stdin for direct execution.")
        else:
            logger.warning(
                "Prompt specified as '-' but stdin is a TTY. No input read for direct prompt."
            )
            if output_format == "text":
                console.print(
                    "[yellow]Warning: Prompt was '-' but no data piped from stdin.[/yellow]"
                )
            elif output_format in ["json", "stream-json"]:
                print(
                    json.dumps(
                        {
                            "error": "Prompt was '-' but no data piped from stdin.",
                            "assistant_response": "",
                            "action_results": [],
                        }
                    )
                )
            return
    else:
        actual_prompt = prompt_text

    if not actual_prompt:
        logger.info("No prompt provided for direct execution.")
        if output_format == "text":
            console.print("[yellow]No prompt provided.[/yellow]")
        elif output_format in ["json", "stream-json"]:
            print(
                json.dumps(
                    {
                        "error": "No prompt provided",
                        "assistant_response": "",
                        "action_results": [],
                    }
                )
            )
        return

    logger.info(
        f"Processing direct prompt (output format: {output_format}): '{actual_prompt[:100]}...'"
    )

    # Non-interactive implies not using the Rich-based streaming UI from PenguinCLI.
    # `core.process` with `streaming=False` will get the full response.
    # For `stream-json`, `core.process` would need to support yielding JSON chunks.
    # For now, `stream-json` will output the full response as a single JSON object.

    # TODO: Implement actual streaming for "stream-json" output format.
    # This might involve modifying `_core.process` or having a separate streaming method
    # that yields structured event data (init, user_message, assistant_chunk, tool_call, etc.).
    if output_format == "stream-json":
        # Placeholder for future actual streaming implementation
        # For now, it will behave like "json"
        logger.info(
            "stream-json output format selected; will output full JSON for now. True streaming TODO."
        )
        # Example of initial messages for true stream-json:
        # session_id_for_stream = _core.conversation_manager.get_current_session_id() # Needs method in ConversationManager
        # print(json.dumps({"type": "system", "subtype": "init", "session_id": "placeholder_session_id"}))
        # print(json.dumps({"type": "user", "message": {"content": actual_prompt}, "session_id": "placeholder_session_id"}))
        pass

    response = await _core.process(
        {"text": actual_prompt},
        streaming=False,  # For non-interactive, we process fully then format output.
        # If output_format is stream-json, core.process would need to handle that.
    )

    if output_format == "text":
        assistant_response_text = response.get("assistant_response", "")
        if assistant_response_text:  # Only print if there's something
            console.print(assistant_response_text)

        action_results = response.get("action_results", [])
        if action_results:
            for i, res in enumerate(action_results):
                if i == 0 and assistant_response_text:
                    console.print("")
                panel_content = (
                    f"[bold cyan]Action:[/bold cyan] {res.get('action', res.get('action_name', 'Unknown'))}\n"
                    f"[bold cyan]Status:[/bold cyan] {res.get('status', 'unknown')}\n"
                    f"[bold cyan]Result:[/bold cyan]\n{res.get('result', res.get('output', 'N/A'))}"
                )
                console.print(
                    Panel(
                        panel_content,
                        title=f"Action Result {i + 1}",
                        padding=1,
                        border_style="yellow",
                    )
                )
    elif output_format == "json" or output_format == "stream-json":
        print(json.dumps(response, indent=2))
    else:
        console.print(
            f"[red]Error: Unknown output format '{output_format}'. Valid options are 'text', 'json', 'stream-json'.[/red]"
        )
        raise typer.Exit(code=1)


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
        None, "--run", help="Run a specific task or project in autonomous mode."
    ),
    continuous: bool = typer.Option(
        False,
        "--247",
        "--continuous",
        help="Run in continuous mode until manually stopped.",
    ),
    time_limit: Optional[int] = typer.Option(
        None,
        "--time-limit",
        help="Time limit in minutes for task/continuous execution.",
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
        help="Execution root for file ops and commands: 'project' or 'workspace'",
    ),
    version: Optional[bool] = typer.Option(
        None, "--version", "-V", help="Show Penguin version and exit.", is_eager=True
    ),
):
    """
    Penguin AI Assistant - Your command-line AI companion.
    """
    if version:
        # TODO: Get version dynamically, e.g., from importlib.metadata or a __version__ string
        console.print("Penguin AI Assistant v0.1.0 (Placeholder Version)")
        raise typer.Exit()

    # Preconfigure environment for root/project overrides so that even
    # early-return paths (e.g. launching the TUI) honour the requested roots.
    resolved_project_path: Optional[Path] = None
    if project:
        # Try as-is, then workspace/projects/<name>
        candidates = []
        try:
            candidates.append(Path(project).expanduser())
        except Exception:
            pass
        candidates.append(Path(WORKSPACE_PATH) / "projects" / project)
        for candidate in candidates:
            try:
                if candidate.exists() and candidate.is_dir():
                    resolved_project_path = candidate.resolve()
                    os.environ["PENGUIN_PROJECT_ROOT"] = str(resolved_project_path)
                    os.environ.setdefault("PENGUIN_CWD", str(resolved_project_path))
                    logger.info(
                        "CLI env: PENGUIN_PROJECT_ROOT=%s", resolved_project_path
                    )
                    break
            except Exception:
                continue

    if root:
        root_mode = root.lower()
        if root_mode in ("project", "workspace"):
            os.environ["PENGUIN_WRITE_ROOT"] = root_mode
            if root_mode == "workspace":
                os.environ["PENGUIN_CWD"] = str(WORKSPACE_PATH)
            elif root_mode == "project" and resolved_project_path is not None:
                os.environ["PENGUIN_CWD"] = str(resolved_project_path)
            logger.info(
                "CLI env: PENGUIN_WRITE_ROOT=%s PENGUIN_CWD=%s",
                root_mode,
                os.environ.get("PENGUIN_CWD"),
            )
        else:
            console.print(
                f"[yellow]Warning: unknown root '{root}'. Expected 'project' or 'workspace'.[/yellow]"
            )

    # Skip heavy initialization for config commands and certain lightweight commands
    if ctx.invoked_subcommand in ["config"]:
        return  # Let the subcommand handle its own logic without core initialization

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
            console.print("[yellow]  pip install questionary httpx[/yellow]")
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

        # Record project flag for downstream commands
        ctx.obj = ctx.obj or {}
        ctx.obj["project"] = project

        # Check for priority flags in order of precedence:
        # 1. Task execution (--run)
        if run_task is not None:
            await _handle_run_mode(run_task, continuous, time_limit, task_description)
        # 2. Session management (--continue/--resume)
        elif continue_last or resume_session:
            # We'll always go into interactive mode for session management
            if prompt is not None:
                # Combine -p with -c/--resume
                await _handle_session_management(
                    continue_last, resume_session, prompt, output_format
                )
            else:
                # Just go into interactive mode with loaded session
                await _handle_session_management(continue_last, resume_session)
        # 3. Direct prompt (-p/--prompt)
        elif prompt is not None:
            # Standard non-interactive mode if -p or --prompt was used
            await _run_penguin_direct_prompt(prompt, output_format)
        # 4. Continuous mode without task (just --247)
        elif continuous:
            await _handle_run_mode(None, continuous, time_limit, task_description)
        # 5. Default: interactive chat session
        elif ctx.invoked_subcommand is None:
            # No subcommand invoked, default to interactive chat
            await _run_interactive_chat()
        # Else: a subcommand was invoked (e.g., `penguin chat`, `penguin profile`).
        # Typer will handle calling the subcommand.

    # Run the async function in the current thread
    asyncio.run(_async_init_and_run())


async def _handle_run_mode(
    task_name: Optional[str],
    continuous: bool,
    time_limit: Optional[int] = None,
    description: Optional[str] = None,
) -> None:
    """
    Handle run mode execution with specified task and options.

    Args:
        task_name: Name of the task to run
        continuous: Whether to run in continuous mode
        time_limit: Optional time limit in minutes
        description: Optional description for the task
    """
    global _core

    if not _core:
        logger.error("Core not initialized for run mode.")
        console.print(
            "[red]Error: Core components failed to initialize for run mode.[/red]"
        )
        raise typer.Exit(code=1)

    try:
        logger.info(
            f"Starting run mode: task={task_name}, continuous={continuous}, time_limit={time_limit}"
        )

        stream_started = False

        async def runmode_stream_callback(chunk: str, message_type: str = "assistant") -> None:
            """Stream RunMode chunks directly to the console in headless mode."""
            nonlocal stream_started

            if chunk == "" and stream_started:
                # Final signal – terminate the current line cleanly
                console.print("")
                stream_started = False
                return

            if not chunk:
                return

            if not stream_started:
                # Provide a visual separator before streaming begins
                console.print("")
                stream_started = True

            style = "dim" if message_type == "reasoning" else "white"
            console.print(
                chunk,
                style=style,
                end="",
                highlight=False,
                soft_wrap=True,
            )
            try:
                console.file.flush()
            except Exception:
                pass

        # Configure UI update callback (placeholder for future enhancements)
        async def ui_update_callback() -> None:
            """Handle UI updates during run mode."""
            pass

        # Use core.start_run_mode to execute the task
        if continuous:
            console.print(
                f"[bold blue]Starting continuous mode{' for task: ' + task_name if task_name else ''}[/bold blue]"
            )
            if time_limit:
                console.print(f"[blue]Time limit: {time_limit} minutes[/blue]")
            console.print("[blue]Press Ctrl+C to stop execution gracefully[/blue]")

            try:
                # For continuous mode, we use the same method but with continuous=True
                await _core.start_run_mode(
                    name=task_name,
                    description=description,
                    continuous=True,
                    time_limit=time_limit,
                    stream_callback_for_cli=runmode_stream_callback,
                    ui_update_callback_for_cli=ui_update_callback,
                )
            except KeyboardInterrupt:
                console.print(
                    "\n[yellow]Keyboard interrupt received. Gracefully shutting down...[/yellow]"
                )
                # Core should handle the graceful shutdown internally
        else:
            # For single task execution
            if not task_name:
                console.print(
                    "[yellow]No task specified for run mode. Use --run <task_name> to specify a task.[/yellow]"
                )
                raise typer.Exit(code=1)

            console.print(f"[bold blue]Running task: {task_name}[/bold blue]")
            if description:
                console.print(f"[blue]Description: {description}[/blue]")
            if time_limit:
                console.print(f"[blue]Time limit: {time_limit} minutes[/blue]")

            await _core.start_run_mode(
                name=task_name,
                description=description,
                continuous=False,
                time_limit=time_limit,
                stream_callback_for_cli=runmode_stream_callback,
                ui_update_callback_for_cli=ui_update_callback,
            )

        console.print("[green]Run mode execution completed.[/green]")

    except Exception as e:
        logger.error(f"Error in run mode execution: {e}", exc_info=True)
        console.print(f"[red]Error running task: {e!s}[/red]")
        console.print(traceback.format_exc())


async def _handle_session_management(
    continue_last: bool,
    resume_session: Optional[str],
    prompt: Optional[str] = None,
    output_format: str = "text",
) -> None:
    """
    Handle session management flags by loading the appropriate conversation.

    Args:
        continue_last: Whether to continue the most recent conversation
        resume_session: Optional session ID to resume
        prompt: Optional prompt to process in non-interactive mode
        output_format: Output format for non-interactive mode
    """
    global _core

    if not _core:
        logger.error("Core not initialized for session management.")
        console.print(
            "[red]Error: Core components failed to initialize for session management.[/red]"
        )
        raise typer.Exit(code=1)

    try:
        if continue_last:
            # Get the most recent conversation ID
            conversations = _core.list_conversations(limit=1)
            if not conversations:
                console.print(
                    "[yellow]No previous conversations found to continue.[/yellow]"
                )
                if prompt:
                    # Fall back to standard processing if no conversation to continue
                    await _run_penguin_direct_prompt(prompt, output_format)
                else:
                    # Fall back to new interactive session
                    await _run_interactive_chat()
                return

            # Load the most recent conversation
            session_id = conversations[0]["id"]
            logger.info(f"Continuing most recent conversation: {session_id}")
            success = _core.conversation_manager.load(session_id)

            if not success:
                console.print(
                    "[yellow]Failed to load most recent conversation. Starting new session.[/yellow]"
                )
                if prompt:
                    await _run_penguin_direct_prompt(prompt, output_format)
                else:
                    await _run_interactive_chat()
                return

            console.print(f"[green]Continuing conversation {session_id}[/green]")

        elif resume_session:
            # Load the specified conversation
            logger.info(f"Resuming conversation: {resume_session}")
            success = _core.conversation_manager.load(resume_session)

            if not success:
                console.print(
                    f"[yellow]Failed to load conversation {resume_session}. Starting new session.[/yellow]"
                )
                if prompt:
                    await _run_penguin_direct_prompt(prompt, output_format)
                else:
                    await _run_interactive_chat()
                return

            console.print(f"[green]Resumed conversation {resume_session}[/green]")

        # Process prompt if provided, otherwise go into interactive mode
        if prompt:
            await _run_penguin_direct_prompt(prompt, output_format)
        else:
            await _run_interactive_chat()

    except Exception as e:
        logger.error(f"Error in session management: {e}", exc_info=True)
        console.print(f"[red]Error loading conversation: {e!s}[/red]")
        # Fall back to standard behavior
        if prompt:
            await _run_penguin_direct_prompt(prompt, output_format)
        else:
            await _run_interactive_chat()


# Create a sub-app for config management
config_app = typer.Typer(name="config", help="Manage Penguin configuration")
app.add_typer(config_app, name="config")


@config_app.command("setup")
def config_setup():
    """Run the setup wizard to configure Penguin"""
    console.print("[bold cyan]🐧 Penguin Setup Wizard[/bold cyan]")
    console.print("Configuring your Penguin environment...\n")

    if not setup_available:
        console.print(f"[red]Setup wizard not available: {setup_import_error}[/red]")
        console.print(
            "[yellow]You may need to install additional dependencies:[/yellow]"
        )
        console.print("[yellow]  pip install questionary httpx[/yellow]")
        console.print("[yellow]Or install with setup extras:[/yellow]")
        console.print("[yellow]  pip install penguin[setup][/yellow]")
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
                console.print("[bold green]Setup completed successfully![/bold green]")
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
        console.print(f"[red]Setup wizard not available: {setup_import_error}[/red]")
        console.print(
            "[yellow]Install setup dependencies first: pip install questionary httpx[/yellow]"
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
            console.print(f"  Setup wizard looks for config at: {setup_config_path}")
            console.print(f"    Exists: {'✓' if setup_config_path.exists() else '❌'}")
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
            console.print("  ⚠️ Main app using default config (no config file found)")
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

    console.print(f"\n[dim]Platform: {platform.system()} {platform.release()}[/dim]")
    console.print(f"[dim]Python: {sys.version}[/dim]")


# Agent Management Commands
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
            table.add_row(name, description, model_label, tools_label, auto_activate)

        console.print(table)

    asyncio.run(_run())


@agent_app.command("list")
def agent_list(
    json_output: bool = typer.Option(False, "--json", help="Emit agent roster as JSON"),
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
    shared_cw_max_tokens: Optional[int] = typer.Option(
        None, "--shared-cw-max", help="Clamp shared context window tokens"
    ),
    model_max_tokens: Optional[int] = typer.Option(
        None, "--model-max-tokens", help="Clamp agent context window tokens"
    ),
    model_config_id: Optional[str] = typer.Option(
        None, "--model-id", help="Model config id override"
    ),
    default_tools: Optional[List[str]] = typer.Option(
        None, "--tool", "-t", help="Restrict tools available to the agent (repeatable)"
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

        personas = {entry.get("name"): entry for entry in _core.get_persona_catalog()}
        if persona and persona not in personas:
            console.print(f"[red]Persona '{persona}' not found in configuration.[/red]")
            raise typer.Exit(code=1)

        model_configs = getattr(_core.config, "model_configs", {}) or {}
        if model_config_id and model_config_id not in model_configs:
            console.print(
                f"[red]Model id '{model_config_id}' not found in configuration.[/red]"
            )
            raise typer.Exit(code=1)

        tools_tuple = tuple(default_tools) if default_tools else None

        try:
            if parent_agent_id:
                _core.create_sub_agent(
                    agent_id,
                    parent_agent_id=parent_agent_id,
                    system_prompt=system_prompt,
                    share_session=share_session,
                    share_context_window=share_context_window,
                    shared_cw_max_tokens=shared_cw_max_tokens,
                    model_max_tokens=model_max_tokens,
                    persona=persona,
                    model_config_id=model_config_id,
                    default_tools=tools_tuple,
                    activate=activate,
                )
            else:
                _core.register_agent(
                    agent_id,
                    system_prompt=system_prompt,
                    activate=activate,
                    model_max_tokens=model_max_tokens,
                    persona=persona,
                    model_config_id=model_config_id,
                    default_tools=tools_tuple,
                )
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
        False, "--activate/--no-activate", help="Make this agent active after switching"
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

        personas = {entry.get("name"): entry for entry in _core.get_persona_catalog()}
        if persona not in personas:
            console.print(f"[red]Persona '{persona}' not found in configuration.[/red]")
            raise typer.Exit(code=1)

        model_configs = getattr(_core.config, "model_configs", {}) or {}
        if model_config_id and model_config_id not in model_configs:
            console.print(
                f"[red]Model id '{model_config_id}' not found in configuration.[/red]"
            )
            raise typer.Exit(code=1)

        tools_tuple = tuple(default_tools) if default_tools else None

        parent_map = getattr(_core.conversation_manager, "sub_agent_parent", {}) or {}
        parent = parent_map.get(agent_id)

        try:
            if parent:
                _core.create_sub_agent(
                    agent_id,
                    parent_agent_id=parent,
                    system_prompt=system_prompt,
                    persona=persona,
                    model_config_id=model_config_id,
                    default_tools=tools_tuple,
                    activate=activate,
                )
            else:
                _core.register_agent(
                    agent_id,
                    system_prompt=system_prompt,
                    activate=activate,
                    persona=persona,
                    model_config_id=model_config_id,
                    default_tools=tools_tuple,
                )
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
                value = ", ".join(f"{k}={v}" for k, v in value.items() if v is not None)
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
@project_app.command("create")
def project_create(
    name: str = typer.Argument(..., help="Project name"),
    description: Optional[str] = typer.Option(
        None, "--description", "-d", help="Project description"
    ),
    workspace_path: Optional[str] = typer.Option(
        None, "--workspace", "-w", help="Project workspace path"
    ),
):
    """Create a new project"""

    async def _async_project_create():
        console.print(f"[bold cyan]🐧 Creating project:[/bold cyan] {name}")

        # Initialize core components to access project manager
        await _initialize_core_components_globally()

        if not _core or not _core.project_manager:
            console.print("[red]Error: Project manager not available[/red]")
            raise typer.Exit(code=1)

        try:
            # Note: workspace_path is managed internally by ProjectManager
            project = await _core.project_manager.create_project_async(
                name=name, description=description or f"Project: {name}"
            )

            console.print("[green]✓ Project created successfully![/green]")
            console.print(f"  ID: {project.id}")
            console.print(f"  Name: {project.name}")
            console.print(f"  Description: {project.description}")
            if project.workspace_path:
                console.print(f"  Workspace: {project.workspace_path}")

        except Exception as e:
            console.print(f"[red]Error creating project: {e}[/red]")
            raise typer.Exit(code=1)

    asyncio.run(_async_project_create())


@project_app.command("list")
def project_list():
    """List all projects"""

    async def _async_project_list():
        console.print("[bold cyan]🐧 Projects:[/bold cyan]")

        await _initialize_core_components_globally()

        if not _core or not _core.project_manager:
            console.print("[red]Error: Project manager not available[/red]")
            raise typer.Exit(code=1)

        try:
            projects = await _core.project_manager.list_projects_async()

            if not projects:
                console.print(
                    "[yellow]No projects found. Create one with 'penguin project create <name>'[/yellow]"
                )
                return

            from rich.table import Table

            table = Table(show_header=True, header_style="bold magenta")
            table.add_column("ID", style="dim", width=8)
            table.add_column("Name", style="cyan")
            table.add_column("Status", style="green")
            table.add_column("Tasks", style="yellow")
            table.add_column("Created", style="dim")

            for project in projects:
                # Get task count for this project
                project_tasks = await _core.project_manager.list_tasks_async(
                    project_id=project.id
                )
                task_count = len(project_tasks)

                table.add_row(
                    project.id[:8],
                    project.name,
                    project.status,  # Project status is a string, not an enum
                    str(task_count),
                    project.created_at[:16]
                    if project.created_at
                    else "Unknown",  # created_at is ISO string, take first 16 chars (YYYY-MM-DD HH:MM)
                )

            console.print(table)

        except Exception as e:
            console.print(f"[red]Error listing projects: {e}[/red]")
            raise typer.Exit(code=1)

    asyncio.run(_async_project_list())


@project_app.command("delete")
def project_delete(
    project_id: str = typer.Argument(..., help="Project ID to delete"),
    force: bool = typer.Option(
        False, "--force", "-f", help="Force delete without confirmation"
    ),
):
    """Delete a project"""

    async def _async_project_delete():
        await _initialize_core_components_globally()

        if not _core or not _core.project_manager:
            console.print("[red]Error: Project manager not available[/red]")
            raise typer.Exit(code=1)

        try:
            # Get project details first
            project = await _core.project_manager.get_project_async(project_id)
            if not project:
                console.print(
                    f"[red]Error: Project with ID '{project_id}' not found[/red]"
                )
                raise typer.Exit(code=1)

            if not force:
                import typer

                confirm = typer.confirm(
                    f"Are you sure you want to delete project '{project.name}' ({project_id[:8]})?"
                )
                if not confirm:
                    console.print("[yellow]Operation cancelled[/yellow]")
                    return

            # Note: Need to add delete_project_async method to ProjectManager
            success = _core.project_manager.storage.delete_project(project_id)
            if not success:
                console.print("[red]Failed to delete project[/red]")
                raise typer.Exit(code=1)
            console.print(
                f"[green]✓ Project '{project.name}' deleted successfully[/green]"
            )

        except Exception as e:
            console.print(f"[red]Error deleting project: {e}[/red]")
            raise typer.Exit(code=1)

    asyncio.run(_async_project_delete())


@project_app.command("run")
def project_run(
    spec_file: Path = typer.Argument(
        ..., help="Path to the project specification Markdown file.", exists=True
    ),
):
    """
    Run a complete project workflow from a specification file.

    This command will:
    1. Parse the spec file to create a project and tasks.
    2. Sequentially execute each task using the real agent system.
    3. Validate each task by running tests.
    4. Create a pull request for each validated task.
    """

    async def _async_run_workflow():
        console.print(
            f"[bold blue]🐧 Starting project workflow from:[/bold blue] {spec_file}"
        )

        # --- Setup ---
        # Initialize core components to get the ProjectManager
        await _initialize_core_components_globally()
        project_manager = _core.project_manager

        # Use the real RunMode from the core instead of mocking
        run_mode = RunMode(_core)  # Pass the core instance

        # Initialize the rest of the managers
        if not GITHUB_REPOSITORY:
            console.print(
                "[red]Error: GITHUB_REPOSITORY is not configured in your .env or config.yml.[/red]"
            )
            raise typer.Exit(code=1)

        git_manager = GitManager(
            workspace_path=WORKSPACE_PATH,
            project_manager=project_manager,
            repo_owner_and_name=GITHUB_REPOSITORY,
        )
        validation_manager = ValidationManager(workspace_path=WORKSPACE_PATH)
        task_executor = ProjectTaskExecutor(
            run_mode=run_mode, project_manager=project_manager
        )
        orchestrator = WorkflowOrchestrator(
            project_manager=project_manager,
            task_executor=task_executor,
            validation_manager=validation_manager,
            git_manager=git_manager,
        )

        # --- Act ---
        console.print("\n[bold]1. Parsing project specification...[/bold]")
        try:
            spec_content = spec_file.read_text()
            parse_result = await parse_project_specification_from_markdown(
                markdown_content=spec_content, project_manager=project_manager
            )
            if parse_result["status"] != "success":
                console.print(
                    f"[red]Error parsing spec file: {parse_result['message']}[/red]"
                )
                raise typer.Exit(code=1)

            project_id = parse_result["creation_result"]["project"]["id"]
            num_tasks = parse_result["creation_result"]["tasks_created"]
            console.print(
                f"[green]✓ Project '{parse_result['creation_result']['project']['name']}' created with {num_tasks} task(s).[/green]"
            )
        except Exception as e:
            console.print(f"[red]Failed to read or parse spec file: {e}[/red]")
            raise typer.Exit(code=1)

        console.print("\n[bold]2. Executing project tasks...[/bold]")
        task_number = 0
        while True:
            task_number += 1
            console.print(f"\n--- Running Task {task_number}/{num_tasks} ---")
            workflow_result = await orchestrator.run_next_task(project_id=project_id)

            if workflow_result is None:
                console.print("[bold green]✓ No more tasks to run.[/bold green]")
                break

            console.print(f"   Task: '{workflow_result['task_title']}'")
            if workflow_result.get("status") == "COMPLETED":
                pr_url = workflow_result.get("pull_request", {}).get("pr_url", "N/A")
                console.print(
                    f"   [green]✓ Status: {workflow_result['status']}[/green]"
                )
                console.print(f"   [green]✓ Pull Request: {pr_url}[/green]")
            else:
                error_msg = workflow_result.get("error", "An unknown error occurred.")
                console.print(f"   [red]✗ Status: {workflow_result['status']}[/red]")
                console.print(f"   [red]✗ Reason: {error_msg}[/red]")
                console.print("[bold red]Workflow stopped due to failure.[/bold red]")
                break

        console.print("\n[bold blue]🐧 Project workflow finished.[/bold blue]")

    asyncio.run(_async_run_workflow())


# Task Management Commands
task_app = typer.Typer(help="Task management commands")
project_app.add_typer(task_app, name="task")


@task_app.command("create")
def task_create(
    project_id: str = typer.Argument(..., help="Project ID"),
    title: str = typer.Argument(..., help="Task title"),
    description: Optional[str] = typer.Option(
        None, "--description", "-d", help="Task description"
    ),
    parent_task_id: Optional[str] = typer.Option(
        None, "--parent", "-p", help="Parent task ID"
    ),
    priority: int = typer.Option(1, "--priority", help="Task priority (1-5)"),
):
    """Create a new task in a project"""

    async def _async_task_create():
        console.print(f"[bold cyan]🐧 Creating task:[/bold cyan] {title}")

        await _initialize_core_components_globally()

        if not _core or not _core.project_manager:
            console.print("[red]Error: Project manager not available[/red]")
            raise typer.Exit(code=1)

        try:
            task = await _core.project_manager.create_task_async(
                title=title,
                description=description or title,
                project_id=project_id,
                parent_task_id=parent_task_id,
                priority=priority,
            )

            console.print("[green]✓ Task created successfully![/green]")
            console.print(f"  ID: {task.id}")
            console.print(f"  Title: {task.title}")
            console.print(f"  Status: {task.status.value}")
            console.print(f"  Priority: {task.priority}")

        except Exception as e:
            console.print(f"[red]Error creating task: {e}[/red]")
            raise typer.Exit(code=1)

    asyncio.run(_async_task_create())


@task_app.command("list")
def task_list(
    project_id: Optional[str] = typer.Argument(None, help="Project ID to filter tasks"),
    status: Optional[str] = typer.Option(
        None,
        "--status",
        "-s",
        help="Filter by status (pending, running, completed, failed)",
    ),
):
    """List tasks, optionally filtered by project or status"""

    async def _async_task_list():
        console.print("[bold cyan]🐧 Tasks:[/bold cyan]")

        await _initialize_core_components_globally()

        if not _core or not _core.project_manager:
            console.print("[red]Error: Project manager not available[/red]")
            raise typer.Exit(code=1)

        try:
            # Parse status filter
            status_filter = None
            if status:
                from penguin.project.models import TaskStatus

                try:
                    status_filter = TaskStatus(status.upper())
                except ValueError:
                    console.print(
                        f"[red]Invalid status: {status}. Valid options: pending, running, completed, failed[/red]"
                    )
                    raise typer.Exit(code=1)

            tasks = await _core.project_manager.list_tasks_async(
                project_id=project_id, status=status_filter
            )

            if not tasks:
                filter_desc = ""
                if project_id:
                    filter_desc += f" in project {project_id[:8]}"
                if status:
                    filter_desc += f" with status {status}"
                console.print(f"[yellow]No tasks found{filter_desc}[/yellow]")
                return

            from rich.table import Table

            table = Table(show_header=True, header_style="bold magenta")
            table.add_column("ID", style="dim", width=8)
            table.add_column("Project", style="cyan", width=8)
            table.add_column("Title", style="white")
            table.add_column("Status", style="green")
            table.add_column("Priority", style="yellow", width=8)
            table.add_column("Created", style="dim")

            for task in tasks:
                table.add_row(
                    task.id[:8],
                    task.project_id[:8],
                    task.title,
                    task.status.value,
                    str(task.priority),
                    task.created_at[:16]
                    if task.created_at
                    else "Unknown",  # created_at is ISO string, take first 16 chars
                )

            console.print(table)

        except Exception as e:
            console.print(f"[red]Error listing tasks: {e}[/red]")
            raise typer.Exit(code=1)

    asyncio.run(_async_task_list())


@task_app.command("start")
def task_start(task_id: str = typer.Argument(..., help="Task ID to start")):
    """Start a task (set status to running)"""

    async def _async_task_start():
        await _initialize_core_components_globally()

        if not _core or not _core.project_manager:
            console.print("[red]Error: Project manager not available[/red]")
            raise typer.Exit(code=1)

        try:
            from penguin.project.models import TaskStatus

            task = await _core.project_manager.get_task_async(task_id)
            if not task:
                console.print(f"[red]Error: Task with ID '{task_id}' not found[/red]")
                raise typer.Exit(code=1)

            # Use update_task_status method for status changes
            success = _core.project_manager.update_task_status(
                task_id,
                TaskStatus.ACTIVE,  # ProjectManager uses ACTIVE instead of RUNNING
            )
            if not success:
                console.print("[red]Failed to start task[/red]")
                raise typer.Exit(code=1)

            # Get updated task
            updated_task = await _core.project_manager.get_task_async(task_id)

            console.print(f"[green]✓ Task '{task.title}' started[/green]")
            console.print(f"  Status: {updated_task.status.value}")

        except Exception as e:
            console.print(f"[red]Error starting task: {e}[/red]")
            raise typer.Exit(code=1)

    asyncio.run(_async_task_start())


@task_app.command("complete")
def task_complete(task_id: str = typer.Argument(..., help="Task ID to complete")):
    """Complete a task (set status to completed)"""

    async def _async_task_complete():
        await _initialize_core_components_globally()

        if not _core or not _core.project_manager:
            console.print("[red]Error: Project manager not available[/red]")
            raise typer.Exit(code=1)

        try:
            from penguin.project.models import TaskStatus

            task = await _core.project_manager.get_task_async(task_id)
            if not task:
                console.print(f"[red]Error: Task with ID '{task_id}' not found[/red]")
                raise typer.Exit(code=1)

            # Use update_task_status method for status changes
            success = _core.project_manager.update_task_status(
                task_id, TaskStatus.COMPLETED
            )
            if not success:
                console.print("[red]Failed to complete task[/red]")
                raise typer.Exit(code=1)

            # Get updated task
            updated_task = await _core.project_manager.get_task_async(task_id)

            console.print(f"[green]✓ Task '{task.title}' completed[/green]")
            console.print(f"  Status: {updated_task.status.value}")

        except Exception as e:
            console.print(f"[red]Error completing task: {e}[/red]")
            raise typer.Exit(code=1)

    asyncio.run(_async_task_complete())


@task_app.command("delete")
def task_delete(
    task_id: str = typer.Argument(..., help="Task ID to delete"),
    force: bool = typer.Option(
        False, "--force", "-f", help="Force delete without confirmation"
    ),
):
    """Delete a task"""

    async def _async_task_delete():
        await _initialize_core_components_globally()

        if not _core or not _core.project_manager:
            console.print("[red]Error: Project manager not available[/red]")
            raise typer.Exit(code=1)

        try:
            task = await _core.project_manager.get_task_async(task_id)
            if not task:
                console.print(f"[red]Error: Task with ID '{task_id}' not found[/red]")
                raise typer.Exit(code=1)

            if not force:
                import typer

                confirm = typer.confirm(
                    f"Are you sure you want to delete task '{task.title}' ({task_id[:8]})?"
                )
                if not confirm:
                    console.print("[yellow]Operation cancelled[/yellow]")
                    return

            # Note: Need to add delete_task_async method to ProjectManager
            success = _core.project_manager.storage.delete_task(task_id)
            if not success:
                console.print("[red]Failed to delete task[/red]")
                raise typer.Exit(code=1)
            console.print(f"[green]✓ Task '{task.title}' deleted successfully[/green]")

        except Exception as e:
            console.print(f"[red]Error deleting task: {e}[/red]")
            raise typer.Exit(code=1)

    asyncio.run(_async_task_delete())


# Duplicate chat command was deprecated; keeping stub commented out to avoid Typer double-registration
# @app.command()
# async def chat(): # Removed model, workspace, no_streaming options
#     """(Deprecated duplicate)"""
#     return


# --- PenguinCLI Class (Interactive Session Manager) ---
# This class definition remains largely the same for now, but will use global components.
# It's instantiated by _run_interactive_chat.
# Small adjustments might be needed if it previously took many args in __init__.


class PenguinCLI:
    USER_COLOR = "cyan"
    PENGUIN_COLOR = "blue"
    TOOL_COLOR = "yellow"
    RESULT_COLOR = "green"
    CODE_COLOR = "bright_blue"
    PENGUIN_EMOJI = "🐧"
    FILE_READ_ACTIONS = {"read_file", "read", "cat", "view", "enhanced_read"}

    # Language detection and mapping
    CODE_BLOCK_PATTERNS = [
        # Standard markdown code blocks with language specification
        (r"```(\w+)(.*?)```", "{}"),  # Captures language and code
        # Execute blocks (for backward compatibility)
        (r"<execute>(.*?)</execute>", "python"),
        # Diff/Edit action tags (will be auto-detected as diff if they contain diff content)
        (r"<apply_diff>(.*?)</apply_diff>", "text"),  # Will auto-detect as diff
        (r"<multiedit>(.*?)</multiedit>", "text"),  # Will auto-detect as diff
        (r"<enhanced_diff>(.*?)</enhanced_diff>", "text"),  # Will auto-detect as diff
        # Language-specific tags
        (r"<python>(.*?)</python>", "python"),
        (r"<javascript>(.*?)</javascript>", "javascript"),
        (r"<js>(.*?)</js>", "javascript"),
        (r"<html>(.*?)</html>", "html"),
        (r"<css>(.*?)</css>", "css"),
        (r"<java>(.*?)</java>", "java"),
        (r"<c\+\+>(.*?)</c\+\+>", "cpp"),
        (r"<cpp>(.*?)</cpp>", "cpp"),
        (r"<c#>(.*?)</c#>", "csharp"),
        (r"<csharp>(.*?)</csharp>", "csharp"),
        (r"<typescript>(.*?)</typescript>", "typescript"),
        (r"<ts>(.*?)</ts>", "typescript"),
        (r"<ruby>(.*?)</ruby>", "ruby"),
        (r"<go>(.*?)</go>", "go"),
        (r"<rust>(.*?)</rust>", "rust"),
        (r"<php>(.*?)</php>", "php"),
        (r"<swift>(.*?)</swift>", "swift"),
        (r"<kotlin>(.*?)</kotlin>", "kotlin"),
        (r"<shell>(.*?)</shell>", "bash"),
        (r"<bash>(.*?)</bash>", "bash"),
        (r"<sql>(.*?)</sql>", "sql"),
        # Default code block (no language specified)
        (r"<code>(.*?)</code>", "text"),
    ]

    # Language detection patterns for auto-detection
    LANGUAGE_DETECTION_PATTERNS = [
        # Python
        (r"import\s+[\w.]+|def\s+\w+\s*\(|class\s+\w+\s*[:\(]|print\s*\(", "python"),
        # JavaScript
        (
            r"function\s+\w+\s*\(|const\s+\w+\s*=|let\s+\w+\s*=|var\s+\w+\s*=|console\.log\(",
            "javascript",
        ),
        # HTML
        (r"<!DOCTYPE\s+html>|<html>|<body>|<div>|<span>|<p>", "html"),
        # CSS
        (r"body\s*{|\.[\w-]+\s*{|#[\w-]+\s*{|\@media", "css"),
        # Java
        (r"public\s+class|private\s+\w+\(|protected|System\.out\.print", "java"),
        # C++
        (r"#include\s+<\w+>|std::|namespace\s+\w+|template\s*<", "cpp"),
        # C#
        (r"using\s+System;|namespace\s+\w+|public\s+class|Console\.Write", "csharp"),
        # TypeScript
        (r"interface\s+\w+|type\s+\w+\s*=|export\s+class", "typescript"),
        # Ruby
        (r"require\s+[\'\"][\w./]+[\'\"]|def\s+\w+(\s*\|\s*.*?\s*\|)?|puts\s+", "ruby"),
        # Go
        (r"package\s+\w+|func\s+\w+|import\s+\(|fmt\.Print", "go"),
        # Rust
        (r"fn\s+\w+|let\s+mut|struct\s+\w+|impl\s+", "rust"),
        # PHP
        (r"<\?php|\$\w+\s*=|echo\s+|function\s+\w+\s*\(", "php"),
        # Swift
        (
            r"import\s+\w+|var\s+\w+\s*:|func\s+\w+\s*\(|class\s+\w+\s*:|\@IBOutlet",
            "swift",
        ),
        # Kotlin
        (r"fun\s+\w+\s*\(|val\s+\w+\s*:|var\s+\w+\s*:|class\s+\w+\s*[:\(]", "kotlin"),
        # Bash
        (r"#!/bin/bash|#!/bin/sh|^\s*if\s+\[\s+|^\s*for\s+\w+\s+in", "bash"),
        # SQL
        (r"SELECT\s+.*?\s+FROM|CREATE\s+TABLE|INSERT\s+INTO|UPDATE\s+.*?\s+SET", "sql"),
    ]

    # Language display names (for panel titles)
    LANGUAGE_DISPLAY_NAMES = {
        "python": "Python",
        "javascript": "JavaScript",
        "html": "HTML",
        "css": "CSS",
        "java": "Java",
        "cpp": "C++",
        "csharp": "C#",
        "typescript": "TypeScript",
        "ruby": "Ruby",
        "go": "Go",
        "rust": "Rust",
        "php": "PHP",
        "swift": "Swift",
        "kotlin": "Kotlin",
        "bash": "Shell/Bash",
        "sql": "SQL",
        "diff": "Diff/Patch",
        "text": "Code",
    }


    def __init__(self, core):
        self.core = core
        self.interface = PenguinInterface(core)
        self.in_247_mode = False
        self.message_count = 0
        self.console = RichConsole()  # Use RichConsole instead of Console

        # Initialize unified renderer with MINIMAL style (no panels for easier copy/paste)
        self.renderer = UnifiedRenderer(
            console=self.console,
            style=RenderStyle.MINIMAL,
            show_timestamps=False,
            show_metadata=False
        )

        self.conversation_menu = ConversationMenu(self.console)
        self.core.register_progress_callback(self.on_progress_update)

        # Add direct Core event subscription for improved event flow
        self.core.register_ui(self.handle_event)

        # Single Live display for better rendering
        self.live_display = None
        self.streaming_live = None

        # Message tracking to prevent duplication
        self.processed_messages = set()
        self.last_completed_message = ""
        self.last_completed_message_normalized = ""

        # Conversation turn tracking
        self.current_conversation_turn = 0
        self.message_turn_map = {}

        # Add streaming state tracking
        self.is_streaming = False
        self.streaming_buffer = ""
        self.streaming_reasoning_buffer = ""  # Separate buffer for reasoning tokens
        self.streaming_role = "assistant"

        # Buffer for pending system messages (tool results) during streaming
        self.pending_system_messages: List[
            Tuple[str, str]
        ] = []  # List of (content, role)

        # Run mode state
        self.run_mode_active = False
        self.run_mode_status = "Idle"

        self.progress = None

        # Create prompt_toolkit session
        self.session = self._create_prompt_session()

        # Add signal handler for clean interrupts
        signal.signal(signal.SIGINT, self._handle_interrupt)

        self._streaming_lock = asyncio.Lock()
        self._streaming_session_id = None  # legacy session id (will be removed)
        self._active_stream_id = None  # NEW – authoritative stream identifier from Core
        self._last_processed_turn = None

    def _create_prompt_session(self):
        """Create and configure a prompt_toolkit session with multi-line support"""
        # Define key bindings
        kb = KeyBindings()

        # Add keybinding for Alt+Enter to create a new line
        @kb.add(Keys.Escape, Keys.Enter)
        def _(event):
            """Insert a new line when Alt (or Option) + Enter is pressed."""
            event.current_buffer.insert_text("\n")

        # Add keybinding for Enter to submit
        @kb.add(Keys.Enter)
        def _(event):
            """Submit the input when Enter is pressed without modifiers."""
            # If there's already text and cursor is at the end, submit
            buffer = event.current_buffer
            if buffer.text and buffer.cursor_position == len(buffer.text):
                buffer.validate_and_handle()
            else:
                # Otherwise insert a new line
                buffer.insert_text("\n")

        # Add a custom style
        style = Style.from_dict(
            {
                "prompt": f"bold {self.USER_COLOR}",
            }
        )

        # Create the PromptSession
        return PromptSession(
            key_bindings=kb,
            style=style,
            multiline=True,  # Enable multi-line editing
            vi_mode=False,  # Use Emacs keybindings by default
            wrap_lines=True,  # Wrap long lines
            complete_in_thread=True,
        )

    def _handle_interrupt(self, sig, frame):
        self._safely_stop_progress()
        print("\nOperation interrupted by user.")
        raise KeyboardInterrupt

    def _extract_and_display_reasoning(self, message: str) -> str:
        """Extract <details> reasoning blocks and display them in a separate gray panel.

        Returns the message with reasoning blocks removed.
        """
        import re

        # Guard against re-displaying already processed reasoning
        if (
            hasattr(self, "_last_reasoning_extracted")
            and message == self._last_reasoning_extracted
        ):
            return message

        # Pattern to match <details> blocks with reasoning
        details_pattern = r"<details>\s*<summary>🧠[^<]*</summary>\s*(.*?)</details>\s*"

        matches = re.findall(details_pattern, message, re.DOTALL | re.IGNORECASE)

        if matches:
            # Extract reasoning content (everything between summary and </details>)
            reasoning_content = matches[0].strip()

            # Remove markdown formatting from reasoning (**, __, etc.)
            # Handle all markdown bold/italic patterns
            reasoning_text = re.sub(
                r"\*\*\*?(.*?)\*\*\*?", r"\1", reasoning_content
            )  # Remove **bold** and ***bold italic***
            reasoning_text = re.sub(
                r"___(.*?)___", r"\1", reasoning_text
            )  # Remove ___bold italic___
            reasoning_text = re.sub(
                r"__(.*?)__", r"\1", reasoning_text
            )  # Remove __bold__
            reasoning_text = re.sub(
                r"_(.*?)_", r"\1", reasoning_text
            )  # Remove _italic_
            reasoning_text = re.sub(
                r"\n+", " ", reasoning_text
            )  # Collapse newlines to spaces
            reasoning_text = re.sub(
                r"\s+", " ", reasoning_text
            )  # Collapse multiple spaces
            reasoning_text = reasoning_text.strip()

            # Display reasoning in a compact gray panel
            if reasoning_text:
                from rich.text import Text

                # Use dim styling for the entire panel content
                reasoning_display = Text(f"🧠 {reasoning_text}", style="dim italic")
                reasoning_panel = Panel(
                    reasoning_display,
                    title="[dim]Internal Reasoning[/dim]",
                    title_align="left",
                    border_style="dim",
                    width=self.console.width - 8,
                    box=rich.box.SIMPLE,  # Simpler box style
                    padding=(0, 1),  # Minimal padding
                )
                self.console.print(reasoning_panel)

            # Remove the details block from the message
            cleaned_message = re.sub(
                details_pattern, "", message, flags=re.DOTALL | re.IGNORECASE
            )

            # Mark this message as processed to prevent re-display
            self._last_reasoning_extracted = message

            return cleaned_message.strip()

        return message

    def _normalize_message_content(self, content: str) -> str:
        """Normalize assistant content for duplicate detection."""
        if not content:
            return ""
        # Remove collapsible reasoning blocks before comparison
        cleaned = re.sub(
            r"<details>.*?</details>", "", content, flags=re.DOTALL | re.IGNORECASE
        )
        # Normalize whitespace to avoid false mismatches
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        return cleaned

    def display_message(self, message: str, role: str = "assistant"):
        """Display a message using the unified renderer"""
        # Skip if this is a duplicate of a recently processed message
        message_key = f"{role}:{message[:50]}"

        if role in ["assistant", "user"]:
            if (
                message_key in self.processed_messages
                and role == "assistant"
                and message == self.last_completed_message
            ):
                return
        else:
            # Always add to processed messages to prevent future duplicates
            self.processed_messages.add(message_key)
            # Associate with current conversation turn
            self.message_turn_map[message_key] = self.current_conversation_turn
            # Update last completed message for assistant messages
            if role == "assistant":
                self.last_completed_message = message

        # Use unified renderer for all message rendering
        # Render with current style (no special case for welcome message)
        panel = self.renderer.render_message(message, role=role, as_panel=True)
        if panel:  # Only print if not filtered as duplicate
            self.console.print(panel)

    def _format_code_block(self, message, code, language, original_block):
        """Format a code block with syntax highlighting and return updated message"""
        # Get the display name for the language or use language code as fallback
        lang_display = self.LANGUAGE_DISPLAY_NAMES.get(language, language.capitalize())

        # CRITICAL: Detect diff content and override language to get proper coloring
        # Check for unified diff markers: ---, +++, @@, or lines starting with + or -
        if language in ["text", "actionxml"] or not language:
            if self._looks_like_diff(code):
                language = "diff"
                lang_display = "Diff"

        # If language is 'text', try to auto-detect
        if language == "text" and code.strip():
            detected_lang = self._detect_language(code)
            if detected_lang != "text":
                language = detected_lang
                lang_display = self.LANGUAGE_DISPLAY_NAMES.get(
                    language, language.capitalize()
                )

        # Choose theme based on language
        theme = "monokai"  # Default
        if language in ["html", "xml"]:
            theme = "github-dark"
        elif language in ["bash", "shell"]:
            theme = "native"
        elif language == "diff":
            theme = "monokai"  # monokai has good diff colors

        # Create a syntax highlighted version
        highlighted_code = Syntax(
            code.strip(),
            language,
            theme=theme,
            line_numbers=True,
            word_wrap=True,
            code_width=min(
                100, self.console.width - 20
            ),  # Limit width for better readability
        )

        # Create a panel for the code
        code_panel = Panel(
            highlighted_code,
            title=f"📋 {lang_display} Code",
            title_align="left",
            border_style=self.CODE_COLOR,
            padding=(1, 2),
        )

        # Display the code block separately
        self.console.print(code_panel)

        # Replace in original message with a note
        placeholder = f"[Code block displayed above ({lang_display})]"
        return message.replace(original_block, placeholder)

    def _create_tool_summary(self, tool_name: str, content: str, metadata: Dict) -> str:
        """
        Create a compact summary for tool results instead of showing full output.

        Args:
            tool_name: Name of the tool
            content: Full tool output
            metadata: Tool metadata

        Returns:
            Compact summary string
        """
        # Extract key info from content
        if "list_files" in tool_name:
            # Count files and directories
            dirs = content.count("DIRECTORIES:")
            files_count = content.count(" bytes)")
            return f"✓ Listed {files_count} files" + (f", {dirs} directories" if dirs > 0 else "")

        elif "read" in tool_name or "enhanced_read" in tool_name:
            # Show file path and size
            import re
            match = re.search(r'(\d+) characters', content)
            if match:
                size = match.group(1)
                file_path = metadata.get("file_path", "file")
                return f"✓ Read {file_path} ({size} chars)"
            return f"✓ Read file"

        elif "write" in tool_name or "enhanced_write" in tool_name:
            # Show file written
            file_path = metadata.get("file_path", "file")
            lines = content.count('\n')
            return f"✓ Wrote {file_path}" + (f" ({lines} lines)" if lines > 0 else "")

        # For other tools, show nothing (will use default display)
        return ""

    def _detect_language(self, code):
        """Automatically detect the programming language of the code"""
        # Default to text if we can't determine the language
        if not code or len(code.strip()) < 5:
            return "text"

        # Try to detect based on patterns
        for pattern, language in self.LANGUAGE_DETECTION_PATTERNS:
            if re.search(pattern, code, re.IGNORECASE | re.MULTILINE):
                return language

        # If no specific patterns matched, use some heuristics
        if code.count("#include") > 0:
            return "cpp"
        if code.count("def ") > 0 or code.count("import ") > 0:
            return "python"
        if (
            code.count("function") > 0
            or code.count("var ") > 0
            or code.count("const ") > 0
        ):
            return "javascript"
        if code.count("<html") > 0 or code.count("<div") > 0:
            return "html"

        # Default to text if no patterns matched
        return "text"

    def _display_code_output_panel(
        self, code_output: str, language: str, title: str = "Output"
    ):
        lang_display = self.LANGUAGE_DISPLAY_NAMES.get(language, language.capitalize())
        output_panel = Panel(
            Syntax(code_output, language, theme="monokai", word_wrap=True),
            title=f"📤 {lang_display} {title}",
            title_align="left",
            border_style="green",  # Or self.RESULT_COLOR
            padding=(1, 2),
            width=self.console.width - 8 if self.console else None,
        )
        if self.console:
            self.console.print(output_panel)
        else:  # Fallback if console not available (e.g. direct prompt mode context)
            print(f"--- {lang_display} {title} ---")
            print(code_output)
            print(f"--- End {lang_display} {title} ---")

    def _display_list_response(self, response: Dict[str, Any]):
        """Display the /list command response in a nicely formatted way"""
        try:
            from rich.table import Table

            projects = response.get("projects", [])
            tasks = response.get("tasks", [])
            summary = response.get("summary", {})

            # Display summary
            summary_text = f"**Summary**: {summary.get('total_projects', 0)} projects, "
            summary_text += f"{summary.get('total_tasks', 0)} tasks "
            summary_text += f"({summary.get('active_tasks', 0)} active)"
            self.display_message(summary_text, "system")

            # Display projects table if any exist
            if projects:
                self.display_message("## Projects", "system")
                table = Table(show_header=True, header_style="bold magenta")
                table.add_column("ID", style="dim", width=8)
                table.add_column("Name", style="cyan")
                table.add_column("Status", style="green")
                table.add_column("Tasks", style="yellow", width=6)
                table.add_column("Created", style="dim")

                for project in projects:
                    table.add_row(
                        project.get("id", "")[:8],
                        project.get("name", ""),
                        project.get("status", ""),
                        str(project.get("task_count", 0)),
                        project.get("created_at", "")[:16]
                        if project.get("created_at")
                        else "",
                    )

                self.console.print(table)

            # Display tasks table if any exist
            if tasks:
                self.display_message("## Tasks", "system")
                table = Table(show_header=True, header_style="bold magenta")
                table.add_column("ID", style="dim", width=8)
                table.add_column("Title", style="white")
                table.add_column("Status", style="green")
                table.add_column("Priority", style="yellow", width=8)
                table.add_column("Project", style="cyan", width=8)
                table.add_column("Created", style="dim")

                for task in tasks:
                    project_id = task.get("project_id", "")
                    project_display = project_id[:8] if project_id else "Independent"

                    table.add_row(
                        task.get("id", "")[:8],
                        task.get("title", ""),
                        task.get("status", ""),
                        str(task.get("priority", 0)),
                        project_display,
                        task.get("created_at", "")[:16]
                        if task.get("created_at")
                        else "",
                    )

                self.console.print(table)

            # If no projects or tasks
            if not projects and not tasks:
                self.display_message(
                    "No projects or tasks found. Create some with `/project create` or `/task create`.",
                    "system",
                )

        except Exception as e:
            # Fallback to simple text display
            logger.error(f"Error displaying list response: {e}")
            self.display_message(
                f"Projects and Tasks:\n{json.dumps(response, indent=2)}", "system"
            )

    def display_action_result(self, result: Dict[str, Any]):
        """Display action results in a more readable format"""
        # This method is part of PenguinCLI, used in interactive mode.
        # For direct prompt mode, _run_penguin_direct_prompt handles its own output.
        if not self.console:  # Should not happen in interactive mode
            logger.warning("display_action_result called without a console.")
            return

        action_type = result.get("action", result.get("action_name", "unknown"))
        result_text = str(
            result.get("result", result.get("output", ""))
        )  # Ensure string
        status = result.get("status", "unknown")

        status_icon = (
            "✓" if status == "completed" else ("⏳" if status == "pending" else "❌")
        )

        # Special handling for file read operations - acknowledge without dumping content
        is_file_read = action_type in self.FILE_READ_ACTIONS
        if is_file_read:
            self._display_file_read_result(result, result_text, action_type, status_icon)
            return

        # If result_text is code-like, use Syntax highlighting
        is_code_output = False
        detected_lang = "text"
        if result_text.strip() and (
            "\n" in result_text
            or any(
                kw in result_text
                for kw in ["def ", "class ", "import ", "function ", "const ", "let "]
            )
        ):
            is_code_output = True
            detected_lang = self._detect_language(result_text)

        # Check if this is a diff output (from edit tools) - display with enhanced visualization
        if self._display_diff_result(result_text, action_type, status_icon):
            return

        if is_code_output:
            lang_display = self.LANGUAGE_DISPLAY_NAMES.get(
                detected_lang, detected_lang.capitalize()
            )
            content_renderable = Syntax(
                result_text,
                detected_lang,
                theme="monokai",
                word_wrap=True,
                line_numbers=True,
            )
            title_for_panel = f"{status_icon} {lang_display} Output from {action_type}"
        else:
            content_renderable = Markdown(
                result_text if result_text.strip() else "(No textual output)"
            )
            title_for_panel = f"{status_icon} Result from {action_type}"

        # Create and display panel (moved outside the if/else blocks)
        panel = Panel(
            content_renderable,
            title=title_for_panel,
            title_align="left",
            border_style=self.TOOL_COLOR if status != "error" else "red",
            width=self.console.width - 8,
            padding=(1, 1),
        )
        self.console.print(panel)

    def _display_file_read_result(
        self,
        result: Dict[str, Any],
        result_text: str,
        action_type: str,
        status_icon: str,
    ) -> None:
        """Render file-read tool output as a concise preview."""
        file_info = result.get("file") or result.get("path") or result.get("source") or action_type

        lines = result_text.splitlines()
        line_count = len(lines)
        char_count = len(result_text)

        summary_lines = [f"**File:** `{file_info}`"]
        if line_count:
            summary_lines.append(
                f"**Size:** {line_count} lines · {char_count:,} characters"
            )
        else:
            summary_lines.append("**Size:** empty file")

        summary_lines.append(
            "**Preview:** content suppressed to keep the console concise; open the file directly if you need full contents."
        )

        summary_panel = Panel(
            Markdown("\n".join(summary_lines)),
            title=f"{status_icon} File Read",
            title_align="left",
            border_style=self.TOOL_COLOR,
            width=self.console.width - 8,
            padding=(1, 1),
        )
        self.console.print(summary_panel)

        if not line_count:
            self.console.print("[dim]No content to display.[/dim]")

    def _guess_language_from_filename(self, file_info: Any) -> str:
        """Best-effort guess of syntax language from file extension."""
        try:
            suffix = Path(str(file_info)).suffix.lower()
        except Exception:
            return "text"

        extension_map = {
            ".py": "python",
            ".js": "javascript",
            ".ts": "typescript",
            ".tsx": "typescript",
            ".jsx": "javascript",
            ".json": "json",
            ".yml": "yaml",
            ".yaml": "yaml",
            ".html": "html",
            ".htm": "html",
            ".css": "css",
            ".sh": "bash",
            ".bash": "bash",
            ".zsh": "bash",
            ".rb": "ruby",
            ".go": "go",
            ".rs": "rust",
            ".java": "java",
            ".cs": "csharp",
            ".cpp": "cpp",
            ".cxx": "cpp",
            ".cc": "cpp",
            ".c": "c",
            ".sql": "sql",
            ".md": "markdown",
        }
        return extension_map.get(suffix, "text")

    def _display_diff_result(
        self,
        result_text: str,
        action_type: str,
        status_icon: str,
    ) -> bool:
        """Render diff output with syntax highlighting when possible."""
        summary_text, diff_blocks = self._split_diff_sections(result_text)

        if diff_blocks:
            if summary_text.strip():
                summary_panel = Panel(
                    Markdown(summary_text.strip()),
                    title=f"{status_icon} Result from {action_type}",
                    title_align="left",
                    border_style=self.TOOL_COLOR,
                    width=self.console.width - 8,
                    padding=(1, 1),
                )
                self.console.print(summary_panel)

            total_blocks = len(diff_blocks)
            for index, block in enumerate(diff_blocks, start=1):
                stats = self._compute_diff_stats(block)
                stats_label = f"+{stats['adds']} / -{stats['deletes']}"
                if stats["hunks"]:
                    stats_label += f" · {stats['hunks']} hunk{'s' if stats['hunks'] != 1 else ''}"

                title_suffix = (
                    f" [{index}/{total_blocks}]" if total_blocks > 1 else ""
                )
                diff_title = (
                    f"{status_icon} Diff {title_suffix} ({stats_label}) from {action_type}"
                )

                try:
                    diff_renderable = Syntax(
                        block,
                        "diff",
                        theme="monokai",
                        line_numbers=False,
                        word_wrap=False,
                        code_width=min(120, self.console.width - 12),
                    )
                except Exception:
                    diff_renderable = Syntax(
                        block,
                        "text",
                        theme="monokai",
                        line_numbers=False,
                        word_wrap=False,
                        code_width=min(120, self.console.width - 12),
                    )

                diff_panel = Panel(
                    diff_renderable,
                    title=diff_title,
                    title_align="left",
                    border_style=self.TOOL_COLOR,
                    width=self.console.width - 8,
                    padding=(1, 1),
                )
                self.console.print(diff_panel)

            return True

        if self._looks_like_diff(result_text):
            from rich.text import Text

            diff_display = Text()
            for line in result_text.splitlines():
                if line.startswith("+") and not line.startswith("+++"):
                    diff_display.append(line + "\n", style="green")
                elif line.startswith("-") and not line.startswith("---"):
                    diff_display.append(line + "\n", style="red")
                elif line.startswith("@@"):
                    diff_display.append(line + "\n", style="cyan bold")
                elif line.startswith("+++") or line.startswith("---"):
                    diff_display.append(line + "\n", style="yellow bold")
                else:
                    diff_display.append(line + "\n", style="dim")

            diff_panel = Panel(
                diff_display,
                title=f"{status_icon} Diff Result from {action_type}",
                title_align="left",
                border_style=self.TOOL_COLOR,
                width=self.console.width - 8,
                padding=(1, 1),
            )
            self.console.print(diff_panel)
            return True

        return False

    def _split_diff_sections(self, text: str) -> Tuple[str, List[str]]:
        """Separate diff blocks from surrounding narrative text."""
        diff_blocks: List[str] = []

        # Extract fenced blocks first (```diff```, ```patch```)
        fenced_pattern = re.compile(r"```(?:diff|patch)\s*\n(.*?)```", re.IGNORECASE | re.DOTALL)

        def _capture_fenced(match: re.Match) -> str:
            block = match.group(1).strip()
            if block:
                diff_blocks.append(block)
            return ""

        remainder = fenced_pattern.sub(_capture_fenced, text)

        # Extract inline unified diff blocks
        inline_pattern = re.compile(
            r"(?ms)^---\s.+?\n\+\+\+\s.+?\n(?:@@.*\n)?(?:[ \t\+\-].*\n)+"
        )
        inline_matches = list(inline_pattern.finditer(remainder))
        for match in inline_matches:
            block = match.group(0).strip()
            if block:
                diff_blocks.append(block)
        remainder = inline_pattern.sub("", remainder)

        return remainder, diff_blocks

    def _compute_diff_stats(self, diff_text: str) -> Dict[str, int]:
        adds = deletes = hunks = 0
        for line in diff_text.splitlines():
            if line.startswith("@@"):
                hunks += 1
            elif line.startswith("+") and not line.startswith("+++"):
                adds += 1
            elif line.startswith("-") and not line.startswith("---"):
                deletes += 1
        return {"adds": adds, "deletes": deletes, "hunks": hunks}

    def _looks_like_diff(self, text: str) -> bool:
        if "```diff" in text.lower() or "```patch" in text.lower():
            return True
        if re.search(r"^---\s", text, re.MULTILINE) and re.search(r"^\+\+\+\s", text, re.MULTILINE):
            return True
        if re.search(r"^@@", text, re.MULTILINE):
            return True
        return False

    def _render_diff_message(self, message: str) -> bool:
        """Render system messages that contain diff content."""
        if not self._looks_like_diff(message):
            return False

        summary, blocks = self._split_diff_sections(message)
        if summary.strip():
            summary_panel = Panel(
                Markdown(summary.strip()),
                title="Diff Update",
                title_align="left",
                border_style=self.TOOL_COLOR,
                width=self.console.width - 8,
                padding=(1, 1),
            )
            self.console.print(summary_panel)

        if not blocks:
            # Try rendering whole message as diff if parsing failed
            blocks = [message]

        for block in blocks:
            stats = self._compute_diff_stats(block)
            stats_label = f"+{stats['adds']} / -{stats['deletes']}"
            if stats["hunks"]:
                stats_label += f" · {stats['hunks']} hunk{'s' if stats['hunks'] != 1 else ''}"

            try:
                renderable = Syntax(
                    block,
                    "diff",
                    theme="monokai",
                    line_numbers=False,
                    word_wrap=False,
                    code_width=min(120, self.console.width - 12),
                )
            except Exception:
                renderable = Syntax(
                    block,
                    "text",
                    theme="monokai",
                    line_numbers=False,
                    word_wrap=False,
                    code_width=min(120, self.console.width - 12),
                )

            panel = Panel(
                renderable,
                title=f"Diff ({stats_label})",
                title_align="left",
                border_style=self.TOOL_COLOR,
                width=self.console.width - 8,
                padding=(1, 1),
            )
            self.console.print(panel)

        return True

    def on_progress_update(
        self, iteration: int, max_iterations: int, message: Optional[str] = None
    ):
        """Handle progress updates without interfering with execution"""
        if not self.progress and iteration > 0:
            # Only show progress if not already processing
            self._safely_stop_progress()
            self.progress = Progress(
                SpinnerColumn(),
                TextColumn("[bold blue]{task.description}"),
                console=self.console,
            )
            self.progress.start()
            self.progress_task = self.progress.add_task(
                f"Thinking... (Step {iteration}/{max_iterations})", total=max_iterations
            )

        if self.progress:
            # Update without completing to prevent early termination
            self.progress.update(
                self.progress_task,
                description=f"{message or 'Processing'} (Step {iteration}/{max_iterations})",
                completed=min(
                    iteration, max_iterations - 1
                ),  # Never mark fully complete
            )

    def _safely_stop_progress(self):
        """Safely stop and clear the progress bar"""
        if self.progress:
            try:
                self.progress.stop()
            except Exception:
                pass  # Suppress any errors during progress cleanup
            finally:
                self.progress = None

    def _ensure_progress_cleared(self):
        """Make absolutely sure no progress indicator is active before showing input prompt"""
        self._safely_stop_progress()

        # Force redraw the prompt area
        print("\033[2K", end="\r")  # Clear the current line

    async def chat_loop(self):
        """Main chat loop with execution isolation"""
        # Initialize logging for this session
        timestamp = datetime.datetime.now()
        session_id = timestamp.strftime("%Y%m%d_%H%M")

        # Setup logging for this session
        _session_logger = setup_logger(f"chat_{session_id}.log")  # noqa: F841

        # Display ASCII art banner (printed once per process)
        _print_ascii_banner(self.console)

        welcome_message = """Welcome to Penguin AI Assistant!

For help: /help  •  For information: /info  •  To exit: /exit

TIP: Use Alt+Enter for new lines, Enter to submit"""

        self.display_message(welcome_message, "system")

        while True:
            try:
                # Clear any lingering progress bars before showing input
                self._ensure_progress_cleared()

                # Use prompt_toolkit instead of input()
                prompt_html = HTML(f"<prompt>You [{self.message_count}]: </prompt>")
                user_input = await self.session.prompt_async(prompt_html)

                if user_input.lower() in ["exit", "quit"]:
                    break

                if not user_input.strip():
                    continue

                # Increment conversation turn for new user input
                self.current_conversation_turn += 1
                # Reset streaming state
                self.is_streaming = False
                self.streaming_buffer = ""
                self.streaming_reasoning_buffer = ""
                self.last_completed_message = ""
                self.last_completed_message_normalized = ""

                # DON'T display user input here - let event system handle it
                # (Prevents duplicate display: once here, once from Core event)
                # self.display_message(user_input, "user")

                # Add user message to processed messages to prevent duplication
                user_msg_key = f"user:{user_input[:50]}"
                self.processed_messages.add(user_msg_key)
                self.message_turn_map[user_msg_key] = self.current_conversation_turn

                # Handle commands
                if user_input.startswith("/"):
                    command_parts = user_input[1:].split(
                        " ", 2
                    )  # Split into max 3 parts
                    command = command_parts[0].lower()

                    # Run handle_command through interface instead of all the individual handlers
                    try:
                        # For /run command, we need special handling for callbacks
                        if command == "run":
                            # Create callbacks for RunMode
                            # Stream callbacks removed - using event system only
                            async def ui_update_callback():
                                # Can be expanded with UI refresh logic if needed
                                pass

                            # Handle through interface
                            response = await self.interface.handle_command(
                                user_input[1:],  # Remove the leading slash
                                runmode_stream_cb=None,
                                runmode_ui_update_cb=ui_update_callback,
                            )
                        elif command == "image":
                            # Explicit handling of /image so we can stream the vision response correctly
                            try:
                                # Parse arguments: /image <path> [description words...]
                                image_path = None
                                description = ""
                                if len(command_parts) > 1 and command_parts[1].strip():
                                    image_path = command_parts[1].strip().strip("'\"")
                                else:
                                    # Ask interactively if no path provided
                                    image_path = (
                                        input("Drag and drop your image here: ")
                                        .strip()
                                        .replace("'", "")
                                    )

                                # Validate the file exists
                                if not image_path or not os.path.exists(image_path):
                                    self.display_message(
                                        f"Image file not found: {image_path}", "error"
                                    )
                                    continue

                                # Remaining part (index 2) is the description if present
                                if len(command_parts) > 2:
                                    description = command_parts[2]
                                if not description.strip():
                                    description = input(
                                        "Description (optional): "
                                    ).strip()

                                # Send the message through the standard interface path so all
                                # normal streaming / action-result handling is reused
                                response = await self.interface.process_input(
                                    {"text": description, "image_path": image_path},
                                    stream_callback=None,
                                )

                                # Finalise any streaming still active
                                if (
                                    hasattr(self, "_streaming_started")
                                    and self._streaming_started
                                ):
                                    self._finalize_streaming()

                                # Display any action results (e.g. vision-tool output)
                                if (
                                    isinstance(response, dict)
                                    and "action_results" in response
                                ):
                                    for result in response["action_results"]:
                                        if isinstance(result, dict):
                                            if "action" not in result:
                                                result["action"] = "unknown"
                                            if "result" not in result:
                                                result["result"] = (
                                                    "(No output available)"
                                                )
                                            if "status" not in result:
                                                result["status"] = "completed"
                                            self.display_action_result(result)
                                        else:
                                            self.display_message(str(result), "system")
                            except Exception as e:
                                self.display_message(
                                    f"Error processing image command: {e!s}", "error"
                                )
                                self.display_message(traceback.format_exc(), "error")
                            continue  # Skip default command processing for /image
                        else:
                            # Regular command handling
                            response = await self.interface.handle_command(
                                user_input[1:]
                            )

                        # Display response based on its type
                        if isinstance(response, dict):
                            # Handle error responses
                            if "error" in response:
                                self.display_message(response["error"], "error")

                            # Handle status messages
                            elif "status" in response:
                                self.display_message(response["status"], "system")

                            # Handle help messages
                            elif "help" in response:
                                help_header = response.get("help", "Available Commands")
                                commands = response.get("commands", [])
                                # Display help without extra indentation
                                self.console.print(
                                    Panel(
                                        f"{help_header}\n\n" + "\n".join(commands),
                                        title="🐧 Help",
                                        border_style="blue",
                                        padding=(1, 2),
                                    )
                                )

                            # Handle conversation list
                            elif "conversations" in response:
                                conversation_summaries = response["conversations"]
                                selected_id = (
                                    self.conversation_menu.select_conversation(
                                        conversation_summaries
                                    )
                                )
                                if selected_id:
                                    load_result = await self.interface.handle_command(
                                        f"chat load {selected_id}"
                                    )
                                    if "status" in load_result:
                                        self.display_message(
                                            load_result["status"], "system"
                                        )
                                    elif "error" in load_result:
                                        self.display_message(
                                            load_result["error"], "error"
                                        )

                            # Handle token usage display
                            elif "token_usage" in response:
                                token_data = response["token_usage"]
                                token_msg = "Current token usage:\n"
                                token_msg += f"Total tokens: {token_data.get('current_total_tokens', 0)} / {token_data.get('max_tokens', 0)} "
                                token_msg += (
                                    f"({token_data.get('percentage', 0):.1f}%)\n\n"
                                )

                                if "categories" in token_data:
                                    token_msg += "Token breakdown by category:\n"
                                    for cat, count in token_data["categories"].items():
                                        token_msg += f"• {cat}: {count}\n"

                                self.display_message(token_msg, "system")

                            # Handle model list
                            elif "models_list" in response:
                                models = response["models_list"]
                                models_msg = "Available models:\n"
                                for model in models:
                                    current_marker = (
                                        "→ " if model.get("current", False) else "  "
                                    )
                                    models_msg += f"{current_marker}{model.get('name')} ({model.get('provider')})\n"
                                self.display_message(models_msg, "system")

                            # Handle list command response
                            elif "projects" in response and "tasks" in response:
                                self._display_list_response(response)
                    except Exception as e:
                        self.display_message(f"Error executing command: {e!s}", "error")
                        self.display_message(traceback.format_exc(), "error")

                    continue  # Back to prompt after command processing

                # Process normal message input through interface
                try:
                    # Show brief "Thinking..." - will be stopped by event system when streaming starts
                    # Using transient Progress that auto-cleans up
                    thinking_progress = Progress(
                        SpinnerColumn(),
                        TextColumn("[dim]Thinking...[/dim]"),
                        console=self.console,
                        transient=True,  # Auto-disappears
                    )
                    thinking_progress.start()
                    thinking_task = thinking_progress.add_task("", total=None)

                    # Store ref so event handler can stop it before streaming
                    self._thinking_progress = thinking_progress

                    try:
                        # Process user message through interface
                        response = await self.interface.process_input(
                            {"text": user_input},
                            stream_callback=None,  # Events handle streaming display
                        )
                    finally:
                        # Always clean up thinking indicator
                        if hasattr(self, "_thinking_progress"):
                            try:
                                self._thinking_progress.stop()
                            except Exception:
                                pass
                            delattr(self, "_thinking_progress")

                    # Assistant responses (streaming or not) are now delivered via Core events.
                    # Therefore, avoid printing them directly here to prevent duplicates.
                    # Action results will still be handled below.

                    # Make sure to finalize any streaming that might still be in progress
                    if hasattr(self, "_streaming_started") and self._streaming_started:
                        self._finalize_streaming()

                    # Action results are now handled via the event system (SYSTEM_OUTPUT category)
                    # No need to display them here - that would cause duplication
                    # Commenting out to prevent duplicate display:
                    #
                    # if isinstance(response, dict) and "action_results" in response:
                    #     for result in response["action_results"]:
                    #         self.display_action_result(result)

                    # If the response itself is a string (unlikely but possible), display it.
                    elif isinstance(response, str):
                        self.display_message(response)

                except KeyboardInterrupt:
                    # Handle interrupt
                    self.display_message("Processing interrupted by user", "system")
                    self._safely_stop_progress()
                    # Cleanup any streaming in progress
                    if hasattr(self, "_streaming_started") and self._streaming_started:
                        self._finalize_streaming()
                    raise
                except Exception as e:
                    self.display_message(f"Error processing input: {e!s}", "error")
                    self.display_message(traceback.format_exc(), "error")
                finally:
                    # Always clean up progress display and streaming
                    self._safely_stop_progress()
                    if hasattr(self, "_streaming_started") and self._streaming_started:
                        self._finalize_streaming()

                # Save conversation after each message exchange
                self.message_count += 1

            except KeyboardInterrupt:
                self.display_message("[DEBUG] Keyboard interrupt received", "system")
                break

            except Exception as e:
                self.display_message(f"[DEBUG] Chat loop error: {e!s}", "error")
                self.display_message(
                    f"[DEBUG] Traceback:\n{traceback.format_exc()}", "error"
                )

        self.display_message("[DEBUG] Exiting chat loop", "system")
        console.print("\nGoodbye! 👋")

    async def handle_conversation_command(self, command_parts: List[str]) -> None:
        """Handle conversation-related commands"""
        if len(command_parts) < 2:
            self.display_message(
                "Usage:\n"
                " • /chat list - Show available conversations\n"
                " • /chat load - Load a previous conversation\n"
                " • /chat summary - Show current conversation summary",
                "system",
            )
            return

        action = command_parts[1].lower()

        if action == "list":
            # Get raw conversation list
            raw_conversations = self.core.conversation_manager.list_conversations()

            # Process each conversation to extract better titles
            conversations = []
            for idx, session in enumerate(raw_conversations):
                session_id = session["id"]

                # Try to get a more descriptive title
                title = session.get("title", "")

                # If no title is set, try to load the session to get the first user message
                if not title or title.startswith("Session "):
                    try:
                        # Load the session object
                        loaded_session = (
                            self.core.conversation_manager.session_manager.load_session(
                                session_id
                            )
                        )
                        if loaded_session:
                            # Find the first user message
                            for msg in loaded_session.messages:
                                if msg.role == "user":
                                    # Use first line of first user message as title
                                    content = msg.content
                                    if isinstance(content, str):
                                        first_line = content.split("\n", 1)[0]
                                        title = (
                                            (first_line[:37] + "...")
                                            if len(first_line) > 40
                                            else first_line
                                        )
                                        break
                                    elif isinstance(content, list):
                                        # Handle structured content like messages with images
                                        for item in content:
                                            if (
                                                isinstance(item, dict)
                                                and item.get("type") == "text"
                                            ):
                                                text = item.get("text", "")
                                                first_line = text.split("\n", 1)[0]
                                                title = (
                                                    (first_line[:37] + "...")
                                                    if len(first_line) > 40
                                                    else first_line
                                                )
                                                break
                                        if title:
                                            break
                    except Exception:
                        # Fall back to session ID if there's an error
                        title = f"Conversation {idx + 1}"

                # If still no title, use default
                if not title or title.startswith("Session "):
                    title = f"Conversation {idx + 1}"

                # Create the ConversationSummary with the extracted title
                conversations.append(
                    ConversationSummary(
                        session_id=session_id,
                        title=title,
                        message_count=session.get("message_count", 0),
                        # Format the datetime properly
                        last_active=(
                            parse_iso_datetime(session.get("last_active", "")).strftime(
                                "%Y-%m-%d %H:%M"
                            )
                            if session.get("last_active")
                            else "Unknown date"
                        ),
                    )
                )
            # Let user select a conversation
            session_id = self.conversation_menu.select_conversation(conversations)
            if session_id:
                try:
                    self.core.conversation_manager.load(session_id)
                    self.display_message("Conversation loaded successfully", "system")
                except Exception as e:
                    self.display_message(f"Error loading conversation: {e!s}", "error")

        elif action == "load":
            # Same as list for now, might add direct session_id loading later
            await self.handle_conversation_command(["conv", "list"])

        elif action == "summary":
            messages = self.core.conversation_manager.conversation.get_history()
            self.conversation_menu.display_summary(messages)

        elif action == "run":
            # During task execution
            await self.core.start_run_mode(
                command_parts[2], command_parts[3] if len(command_parts) > 3 else None
            )

            # After completion
            conversation = self.core.get_conversation(command_parts[2])
            if conversation and hasattr(self.core, "run_mode_messages"):
                # Need to handle this differently with new conversation system
                self.display_message("Task execution completed", "system")

        else:
            self.display_message(f"Unknown conversation action: {action}", "error")

    # Legacy stream_callback method removed - now using event system only

    def _finalize_streaming(self):
        """Finalize streaming and clean up the Live display"""
        if self.streaming_live:
            try:
                self.streaming_live.stop()
                self.streaming_live = None
            except:
                pass  # Suppress any errors during cleanup

        self._streaming_started = False
        self.is_streaming = False
        self._streaming_session_id = None
        self._active_stream_id = None

    def handle_event(self, event_type: str, data: Dict[str, Any]) -> None:
        """
        Handle events from Core and update the display accordingly.
        This creates a direct connection between Core and UI.

        Args:
            event_type: Type of event (e.g., "stream_chunk", "token_update")
            data: Event data
        """
        try:
            if event_type == "stream_chunk":
                # ------------------------------------------------------------------
                # Unified streaming handler using stream_id from Core
                # ------------------------------------------------------------------
                stream_id = data.get("stream_id")
                chunk = data.get("chunk", "")
                is_final = data.get("is_final", False)
                self.streaming_role = data.get("role", "assistant")

                # Ignore chunks with no stream_id (should not happen after refactor)
                if stream_id is None:
                    return

                # First chunk of a new streaming message -> initialise panel
                if self._active_stream_id is None:
                    self._active_stream_id = stream_id
                    self._streaming_started = True
                    self.is_streaming = True  # Set streaming flag
                    self.streaming_buffer = ""
                    self.streaming_reasoning_buffer = ""  # Reset reasoning buffer too

                    # CRITICAL: Stop ALL active progress displays FIRST to prevent "Only one live display" error
                    self._safely_stop_progress()

                    # Also stop the "Thinking..." indicator from chat_loop
                    if hasattr(self, "_thinking_progress"):
                        try:
                            self._thinking_progress.stop()
                            delattr(self, "_thinking_progress")
                        except Exception:
                            pass

                    # Clean up any previous Live panel
                    if getattr(self, "streaming_live", None):
                        try:
                            self.streaming_live.stop()
                        except Exception:
                            pass
                        self.streaming_live = None

                # Ignore chunks that belong to an old or foreign stream
                if stream_id != self._active_stream_id:
                    return

                # Skip empty non-final chunks
                if not chunk and not is_final:
                    return

                # Process chunk for display
                if chunk:
                    # Check if this is reasoning content or regular content
                    is_reasoning = data.get("is_reasoning", False)
                    message_type = data.get("message_type", "assistant")

                    if is_reasoning or message_type == "reasoning":
                        # Add to reasoning buffer
                        self.streaming_reasoning_buffer += chunk
                    else:
                        # Add to regular content buffer
                        self.streaming_buffer += chunk

                    # Update or create streaming panel using unified renderer
                    if not getattr(self, "streaming_live", None):
                        # Use unified renderer for streaming message
                        panel = self.renderer.render_streaming_message(
                            self.streaming_buffer,
                            role=self.streaming_role,
                            show_cursor=True
                        )
                        self.streaming_live = Live(
                            panel,
                            refresh_per_second=10,
                            console=self.console,
                            auto_refresh=True,
                            transient=False  # Keep visible after stop
                        )
                        self.streaming_live.start()
                    else:
                        try:
                            # Update with unified renderer
                            panel = self.renderer.render_streaming_message(
                                self.streaming_buffer,
                                role=self.streaming_role,
                                show_cursor=True
                            )
                            self.streaming_live.update(panel)
                        except Exception as e:
                            # Log the error and recreate Live display
                            logger.error(f"Live.update() failed: {e}, recreating Live display")
                            try:
                                self.streaming_live.stop()
                            except:
                                pass
                            self.streaming_live = None
                            # Will be recreated on next chunk

                if is_final:
                    # Final chunk received - clean up streaming state
                    self.is_streaming = False

                    # Display reasoning panel FIRST (above the Penguin message)
                    if self.streaming_reasoning_buffer.strip():
                        reasoning_panel = self.renderer.render_reasoning(
                            self.streaming_reasoning_buffer
                        )
                        self.console.print(reasoning_panel)

                    # Strip reasoning tags from content before final display
                    import re
                    content_without_reasoning = re.sub(r'<reasoning>.*?</reasoning>', '', self.streaming_buffer, flags=re.DOTALL).strip()

                    # Update Live display ONE LAST TIME with final formatted version
                    if getattr(self, "streaming_live", None) and content_without_reasoning:
                        try:
                            # Replace plain text streaming panel with fully formatted final panel
                            final_panel = self.renderer.render_message(
                                content_without_reasoning,
                                role=self.streaming_role,
                                as_panel=True
                            )
                            self.streaming_live.update(final_panel)
                            # Stop Live - content persists (transient=False)
                            self.streaming_live.stop()
                        except Exception as e:
                            logger.error(f"Failed to update final Live display: {e}")
                        self.streaming_live = None

                    # Store for deduplication
                    if self.streaming_buffer.strip():
                        self.last_completed_message = self.streaming_buffer
                        self.last_completed_message_normalized = (
                            self._normalize_message_content(self.streaming_buffer)
                        )

                    # NOW display any pending system messages (tool results) that arrived during streaming
                    if self.pending_system_messages:
                        for msg_content, msg_role in self.pending_system_messages:
                            self.display_message(msg_content, msg_role)
                        self.pending_system_messages.clear()

                    # Clear stream ID
                    self._active_stream_id = None

                    # Store completed message for deduplication
                    if self.streaming_buffer.strip():
                        completed_msg_key = (
                            f"{self.streaming_role}:{self.streaming_buffer[:50]}"
                        )
                        self.processed_messages.add(completed_msg_key)
                        self.message_turn_map[completed_msg_key] = (
                            self.current_conversation_turn
                        )

                    # Reset buffers
                    self.streaming_buffer = ""
                    self.streaming_reasoning_buffer = ""
                    return

            elif event_type == "token_update":
                # Could update a token display here if we add one
                pass

            elif event_type == "message":
                # A new message has been added to the conversation
                role = data.get("role", "unknown")
                content = data.get("content", "")
                category = data.get("category", MessageCategory.DIALOG)
                metadata = data.get("metadata", {}) if isinstance(data, dict) else {}

                # Buffer system output messages (tool results) if streaming is active
                if (
                    category == MessageCategory.SYSTEM_OUTPUT
                    or category == "SYSTEM_OUTPUT"
                ):
                    # Check if this is a verbose tool result that should be suppressed
                    tool_name = metadata.get("tool_name", "")
                    action_type = metadata.get("action_type", "")

                    # Suppress verbose tool output (reads, lists, writes)
                    SUPPRESS_VERBOSE_TOOLS = {
                        "read_file", "enhanced_read", "list_files_filtered",
                        "write_file", "enhanced_write", "list_files"
                    }

                    if tool_name in SUPPRESS_VERBOSE_TOOLS or action_type in SUPPRESS_VERBOSE_TOOLS:
                        # Show compact summary instead of full output
                        summary = self._create_tool_summary(tool_name or action_type, content, metadata)
                        if summary:
                            if self.is_streaming or self._active_stream_id is not None:
                                self.pending_system_messages.append((summary, "system"))
                            else:
                                self.display_message(summary, "system")
                        return

                    # Show full output for important tools (execute, diff, etc.)
                    if self.is_streaming or self._active_stream_id is not None:
                        # Buffer for display after streaming completes
                        self.pending_system_messages.append((content, "system"))
                        return
                    else:
                        # Not streaming, display immediately
                        self.display_message(content, "system")
                        return

                # Skip other internal system messages
                if category == MessageCategory.SYSTEM or category == "SYSTEM":
                    return

                # Suppress verbose tool payloads for read actions; action results already summarized
                if (
                    role == "tool"
                    and isinstance(metadata, dict)
                    and metadata.get("action_type") in self.FILE_READ_ACTIONS
                ):
                    msg_key = f"{role}:{content[:50]}"
                    self.processed_messages.add(msg_key)
                    self.message_turn_map[msg_key] = self.current_conversation_turn
                    return

                # Generate a message key and check if we've already processed this message
                msg_key = f"{role}:{content[:50]}"
                incoming_normalized = (
                    self._normalize_message_content(content)
                    if role == "assistant"
                    else ""
                )
                if msg_key in self.processed_messages:
                    return

                # If this is a user message, it's the start of a new conversation turn
                if role == "user":
                    # Increment conversation turn counter
                    self.current_conversation_turn += 1

                    # Clear streaming state for new turn
                    self.is_streaming = False
                    self.streaming_buffer = ""
                    self.streaming_reasoning_buffer = ""
                    self.last_completed_message = ""
                    self.last_completed_message_normalized = ""

                # For assistant messages, check if this was already displayed via streaming
                if role == "assistant":
                    # Skip if this message was already displayed via streaming
                    # Use startswith to handle minor formatting differences
                    if self.last_completed_message and (
                        content == self.last_completed_message or
                        content.startswith(self.last_completed_message[:50]) or
                        self.last_completed_message.startswith(content[:50])
                    ):
                        # Add to processed messages to avoid future duplicates
                        self.processed_messages.add(msg_key)
                        self.message_turn_map[msg_key] = self.current_conversation_turn
                        return

                    if (
                        self.last_completed_message_normalized
                        and incoming_normalized
                        and incoming_normalized == self.last_completed_message_normalized
                    ):
                        self.processed_messages.add(msg_key)
                        self.message_turn_map[msg_key] = self.current_conversation_turn
                        return

                # Add to processed messages and map to current turn
                self.processed_messages.add(msg_key)
                self.message_turn_map[msg_key] = self.current_conversation_turn

                # Display the message
                self.display_message(content, role)

                if role == "assistant":
                    self.last_completed_message = content
                    self.last_completed_message_normalized = incoming_normalized

            elif event_type == "status":
                # Handle status events like RunMode updates
                status_type = data.get("status_type", "")

                # Update RunMode status
                if "task_started" in status_type:
                    self.run_mode_active = True
                    task_name = data.get("data", {}).get("task_name", "Unknown task")
                    self.run_mode_status = f"Task '{task_name}' started"
                    
                    # CRITICAL: Reset streaming state when RunMode starts to avoid conflicts
                    self._finalize_streaming()
                    self.is_streaming = False
                    self.streaming_buffer = ""
                    self.streaming_reasoning_buffer = ""
                    self._active_stream_id = None
                    
                    self.display_message(f"Starting task: {task_name}", "system")

                elif "task_progress" in status_type:
                    self.run_mode_active = True
                    iteration = data.get("data", {}).get("iteration", "?")
                    max_iter = data.get("data", {}).get("max_iterations", "?")
                    progress = data.get("data", {}).get("progress", 0)
                    self.run_mode_status = (
                        f"Progress: {progress}% (Iter: {iteration}/{max_iter})"
                    )

                elif "task_completed" in status_type or "run_mode_ended" in status_type:
                    self.run_mode_active = False
                    
                    # CRITICAL: Finalize any active streaming when task completes
                    if self._active_stream_id is not None or self.is_streaming:
                        self._finalize_streaming()
                    
                    if "task_completed" in status_type:
                        task_name = data.get("data", {}).get(
                            "task_name", "Unknown task"
                        )
                        self.run_mode_status = f"Task '{task_name}' completed"
                        self.display_message(f"Task '{task_name}' completed", "system")
                    else:
                        self.run_mode_status = "RunMode ended"
                        self.display_message("RunMode ended", "system")

                elif "clarification_needed" in status_type:
                    self.run_mode_active = True
                    prompt = data.get("data", {}).get("prompt", "Input needed")
                    self.run_mode_status = f"Clarification needed: {prompt}"
                    self.display_message(f"Clarification needed: {prompt}", "system")

            elif event_type == "error":
                # Handle error events
                error_msg = data.get("message", "Unknown error")
                source = data.get("source", "")
                details = data.get("details", "")

                # Display error message
                self.display_message(f"Error: {error_msg}\n{details}", "error")

        except Exception as e:
            # Handle exception in event processing
            self.display_message(f"Error processing event: {e!s}", "error")

    def set_streaming(self, enabled: bool = True) -> None:
        """
        Force streaming mode on or off directly through the API client
        """
        if hasattr(self.core, "model_config") and self.core.model_config is not None:
            self.core.model_config.streaming_enabled = enabled
            print(f"[DEBUG] Set streaming_enabled={enabled} in core.model_config")

        if hasattr(self.core, "api_client") and self.core.api_client is not None:
            if hasattr(self.core.api_client, "model_config"):
                self.core.api_client.model_config.streaming_enabled = enabled
                print(
                    f"[DEBUG] Set streaming_enabled={enabled} in api_client.model_config"
                )

        print(f"[DEBUG] Streaming mode {'enabled' if enabled else 'disabled'}")

    def switch_client_preference(self, preference: str = "litellm") -> None:
        """
        Try switching the client preference for testing different backends

        Args:
            preference: "native", "litellm", or "openrouter"
        """
        if hasattr(self.core, "model_config") and self.core.model_config is not None:
            old_preference = self.core.model_config.client_preference
            self.core.model_config.client_preference = preference
            print(
                f"[DEBUG] Changed client_preference from {old_preference} to {preference}"
            )

            # Attempt to reinitialize API client with new preference
            if hasattr(self.core, "api_client") and self.core.api_client is not None:
                try:
                    from penguin.llm.api_client import APIClient

                    self.core.api_client = APIClient(self.core.model_config)
                    self.core.api_client.set_system_prompt(self.core.system_prompt)
                    print(
                        f"[DEBUG] Reinitialized API client with preference {preference}"
                    )
                except Exception as e:
                    print(f"[ERROR] Failed to reinitialize API client: {e}")


@msg_app.command("to-agent")
def msg_to_agent(
    agent_id: str = typer.Argument(..., help="Target agent id"),
    content: str = typer.Argument(..., help="Message content"),
    message_type: str = typer.Option(
        "message", "--type", help="Envelope message_type: message|action|status"
    ),
    workspace: Optional[Path] = typer.Option(
        None, "--workspace", help="Workspace path override"
    ),
):
    """Send a directed message to an agent via MessageBus."""

    async def _run():
        await _initialize_core_components_globally(workspace_override=workspace)
        assert _core is not None
        ok = await _core.send_to_agent(agent_id, content, message_type=message_type)
        console.print(f"[bold green]Sent[/bold green] to {agent_id}: {ok}")

    asyncio.run(_run())


# ---------------------------- Coordinator CLI ----------------------------


def _get_coordinator() -> "MultiAgentCoordinator":  # type: ignore
    if MultiAgentCoordinator is None:
        raise RuntimeError("Coordinator not available")
    assert _core is not None
    return MultiAgentCoordinator(_core)


@coord_app.command("spawn")
def coord_spawn(
    agent_id: str = typer.Argument(..., help="New agent id"),
    role: str = typer.Option(
        ..., "--role", "-r", help="Agent role (e.g., planner, researcher, implementer)"
    ),
    system_prompt: Optional[str] = typer.Option(
        None, "--system-prompt", "-s", help="Optional system prompt override"
    ),
    model_max_tokens: Optional[int] = typer.Option(
        None, "--model-max-tokens", help="Clamp child CWM at this size"
    ),
    activate: bool = typer.Option(
        False, "--activate/--no-activate", help="Make this agent active by default"
    ),
    persona: Optional[str] = typer.Option(
        None, "--persona", "-p", help="Persona id from config to apply"
    ),
    model_config_id: Optional[str] = typer.Option(
        None, "--model-id", help="Model config id override"
    ),
    default_tools: Optional[List[str]] = typer.Option(
        None, "--tool", "-t", help="Restrict tools available to the agent (repeatable)"
    ),
    shared_cw_max_tokens: Optional[int] = typer.Option(
        None, "--shared-cw-max", help="Clamp shared context window tokens"
    ),
    workspace: Optional[Path] = typer.Option(
        None, "--workspace", help="Workspace path override"
    ),
):
    async def _run():
        await _initialize_core_components_globally(workspace_override=workspace)
        assert _core is not None
        coord = _get_coordinator()
        personas = {entry.get("name") for entry in _core.get_persona_catalog()}
        if persona and persona not in personas:
            console.print(f"[red]Persona '{persona}' not found in configuration.[/red]")
            raise typer.Exit(code=1)
        model_configs = getattr(_core.config, "model_configs", {}) or {}
        if model_config_id and model_config_id not in model_configs:
            console.print(
                f"[red]Model id '{model_config_id}' not found in configuration.[/red]"
            )
            raise typer.Exit(code=1)
        tools_tuple = tuple(default_tools) if default_tools else None
        await coord.spawn_agent(
            agent_id,
            role=role,
            system_prompt=system_prompt,
            model_max_tokens=model_max_tokens,
            activate=activate,
            persona=persona,
            model_config_id=model_config_id,
            default_tools=tools_tuple,
            shared_cw_max_tokens=shared_cw_max_tokens,
        )
        console.print(f"[green]Spawned agent[/green] {agent_id} with role '{role}'")

    asyncio.run(_run())


@coord_app.command("destroy")
def coord_destroy(
    agent_id: str = typer.Argument(..., help="Agent id to destroy"),
    workspace: Optional[Path] = typer.Option(
        None, "--workspace", help="Workspace path override"
    ),
):
    async def _run():
        await _initialize_core_components_globally(workspace_override=workspace)
        coord = _get_coordinator()
        await coord.destroy_agent(agent_id)
        console.print(
            f"[yellow]Destroyed agent[/yellow] {agent_id} (conversation persists)"
        )

    asyncio.run(_run())


@coord_app.command("register")
def coord_register(
    agent_id: str = typer.Argument(..., help="Existing agent id"),
    role: str = typer.Option(..., "--role", "-r", help="Role to register under"),
    workspace: Optional[Path] = typer.Option(
        None, "--workspace", help="Workspace path override"
    ),
):
    async def _run():
        await _initialize_core_components_globally(workspace_override=workspace)
        coord = _get_coordinator()
        coord.register_existing(agent_id, role=role)
        console.print(f"[green]Registered agent[/green] {agent_id} to role '{role}'")

    asyncio.run(_run())


@coord_app.command("send-role")
def coord_send_role(
    role: str = typer.Option(..., "--role", "-r", help="Target role"),
    content: str = typer.Argument(..., help="Message content"),
    message_type: str = typer.Option("message", "--type", help="Envelope message_type"),
    workspace: Optional[Path] = typer.Option(
        None, "--workspace", help="Workspace path override"
    ),
):
    async def _run():
        await _initialize_core_components_globally(workspace_override=workspace)
        coord = _get_coordinator()
        target = await coord.send_to_role(role, content, message_type=message_type)
        console.print(f"Sent to role '{role}' agent: [cyan]{target}[/cyan]")

    asyncio.run(_run())


@coord_app.command("broadcast")
def coord_broadcast(
    roles: str = typer.Option(
        ..., "--roles", help="Comma-separated roles to broadcast to"
    ),
    content: str = typer.Argument(..., help="Message content"),
    message_type: str = typer.Option("message", "--type", help="Envelope message_type"),
    workspace: Optional[Path] = typer.Option(
        None, "--workspace", help="Workspace path override"
    ),
):
    async def _run():
        await _initialize_core_components_globally(workspace_override=workspace)
        coord = _get_coordinator()
        role_list = [r.strip() for r in roles.split(",") if r.strip()]
        sent = await coord.broadcast(role_list, content, message_type=message_type)
        console.print(f"Broadcast sent to: {', '.join(sent) if sent else '(none)'}")

    asyncio.run(_run())


@coord_app.command("rr-workflow")
def coord_rr_workflow(
    role: str = typer.Option(..., "--role", "-r", help="Role to round-robin"),
    prompts: List[str] = typer.Argument(..., help="List of prompts"),
    workspace: Optional[Path] = typer.Option(
        None, "--workspace", help="Workspace path override"
    ),
):
    async def _run():
        await _initialize_core_components_globally(workspace_override=workspace)
        coord = _get_coordinator()
        await coord.simple_round_robin_workflow(prompts, role=role)
        console.print("[green]Round-robin workflow complete[/green]")

    asyncio.run(_run())


@coord_app.command("role-chain")
def coord_role_chain(
    roles: str = typer.Option(
        ...,
        "--roles",
        help="Comma-separated role chain (e.g., planner,researcher,implementer)",
    ),
    content: str = typer.Argument(..., help="Initial content"),
    workspace: Optional[Path] = typer.Option(
        None, "--workspace", help="Workspace path override"
    ),
):
    async def _run():
        await _initialize_core_components_globally(workspace_override=workspace)
        coord = _get_coordinator()
        role_chain = [r.strip() for r in roles.split(",") if r.strip()]
        await coord.role_chain_workflow(content, roles=role_chain)
        console.print("[green]Role-chain workflow complete[/green]")

    asyncio.run(_run())


@msg_app.command("to-human")
def msg_to_human(
    content: str = typer.Argument(..., help="Message content"),
    message_type: str = typer.Option(
        "status", "--type", help="Envelope message_type: message|action|status"
    ),
    workspace: Optional[Path] = typer.Option(
        None, "--workspace", help="Workspace path override"
    ),
):
    """Send a message to the human recipient via MessageBus."""

    async def _run():
        await _initialize_core_components_globally(workspace_override=workspace)
        assert _core is not None
        ok = await _core.send_to_human(content, message_type=message_type)
        console.print(f"[bold green]Sent[/bold green] to human: {ok}")

    asyncio.run(_run())


@msg_app.command("human-reply")
def msg_human_reply(
    agent_id: str = typer.Argument(..., help="Target agent id"),
    content: str = typer.Argument(..., help="Reply content"),
    message_type: str = typer.Option("message", "--type", help="Envelope message_type"),
    workspace: Optional[Path] = typer.Option(
        None, "--workspace", help="Workspace path override"
    ),
):
    """Send a human reply to a specific agent (sender set to 'human')."""

    async def _run():
        await _initialize_core_components_globally(workspace_override=workspace)
        assert _core is not None
        ok = await _core.human_reply(agent_id, content, message_type=message_type)
        console.print(f"[bold green]Human reply sent[/bold green] to {agent_id}: {ok}")

    asyncio.run(_run())


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
