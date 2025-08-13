import asyncio
import datetime
import os
import platform
import signal
import sys
import traceback
import re
from pathlib import Path
from typing import List, Optional, Callable, Dict, Any, Set, Union, TypeVar, cast
# Removed mock imports - using real RunMode implementation now

import json # For JSON output
import io

# Ensure UTF-8 encoding for stdout/stderr to prevent emoji encoding issues
# This is especially important on Windows and some terminal environments
try:
    # Only wrap if not already wrapped and if buffer is available
    if hasattr(sys.stdout, 'buffer') and not isinstance(sys.stdout, io.TextIOWrapper):
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    if hasattr(sys.stderr, 'buffer') and not isinstance(sys.stderr, io.TextIOWrapper):
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8")
except (AttributeError, OSError):
    # If wrapping fails, continue with existing streams
    pass

# Add import timing for profiling if enabled
import time
PROFILE_ENABLED = os.environ.get("PENGUIN_PROFILE", "0") == "1"
if PROFILE_ENABLED:
    print(f"\033[2mStarting CLI module import timing...\033[0m")
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
    
    prompt_toolkit_import = time_import("prompt_toolkit")
    PromptSession = prompt_toolkit_import.PromptSession
    KeyBindings = time_import("prompt_toolkit.key_binding").KeyBindings
    Keys = time_import("prompt_toolkit.keys").Keys
    Style = time_import("prompt_toolkit.styles").Style
    HTML = time_import("prompt_toolkit.formatted_text").HTML
    
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
    
    total_end = time.time()
    total_import_time = (total_end - total_start) * 1000  # Convert to ms
    
    # Print import times
    print(f"\033[2mImport timing results:\033[0m")
    sorted_modules = sorted(module_times.items(), key=lambda x: x[1], reverse=True)
    for module, time_ms in sorted_modules:
        percentage = (time_ms / total_import_time) * 100
        if percentage >= 5.0:  # Only show significant contributors
            print(f"\033[2m  {module}: {time_ms:.0f}ms ({percentage:.1f}%)\033[0m")
    print(f"\033[2mTotal import time: {total_import_time:.0f}ms\033[0m")
else:
    # Standard imports without timing
    import typer  # type: ignore
    from rich.console import Console as RichConsole # Renamed to avoid conflict # type: ignore
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

    from penguin.config import config as penguin_config_global, DEFAULT_MODEL, DEFAULT_PROVIDER, WORKSPACE_PATH, GITHUB_REPOSITORY
from penguin.core import PenguinCore
from penguin.llm.api_client import APIClient
from penguin.llm.model_config import ModelConfig
from penguin.run_mode import RunMode # We will mock this but need the type for spec
from penguin.system.state import parse_iso_datetime, MessageCategory
from penguin.system.conversation_menu import ConversationMenu, ConversationSummary # Used by PenguinCLI class
from penguin.system_prompt import SYSTEM_PROMPT
from penguin.tools import ToolManager
from penguin.utils.log_error import log_error
from penguin.utils.logs import setup_logger
from penguin.cli.interface import PenguinInterface
from penguin.config import Config # Import Config type for type hinting
from penguin.project.manager import ProjectManager
from penguin.project.spec_parser import parse_project_specification_from_markdown
from penguin.project.workflow_orchestrator import WorkflowOrchestrator
from penguin.project.task_executor import ProjectTaskExecutor
from penguin.project.validation_manager import ValidationManager
from penguin.project.git_manager import GitManager

# Add better import error handling for setup functions
setup_available = True
setup_import_error = None

try:
    from penguin.setup import check_first_run, run_setup_wizard_sync, check_config_completeness
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

app = typer.Typer(help="Penguin AI Assistant - Your command-line AI companion.\nRun with -p/--prompt for non-interactive mode, or with a subcommand (e.g., 'chat').\nIf no prompt or subcommand is given, starts an interactive chat session.")
console = RichConsole() # Use the renamed import
logger = setup_logger("penguin_cli.log") # Setup a logger for the CLI module

# Project management sub-application
project_app = typer.Typer(help="Project and task management commands")
app.add_typer(project_app, name="project")

# Define a type variable for better typing
T = TypeVar('T')

# Global core components - initialized by _initialize_core_components_globally
_core: Optional[PenguinCore] = None
_interface: Optional[PenguinInterface] = None
_model_config: Optional[ModelConfig] = None
_api_client: Optional[APIClient] = None
_tool_manager: Optional[ToolManager] = None
_loaded_config: Optional[Union[Dict[str, Any], Config]] = None  # Global config can be dict or Config
_interactive_session_manager: Optional[Any] = None # For PenguinCLI instance

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
                raise AttributeError(f"'{self.__class__.__name__}' object has no attribute '{name}'")
                
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

    _loaded_config = penguin_config_global # Use the imported config

    effective_workspace = workspace_override or WORKSPACE_PATH # WORKSPACE_PATH from penguin.config
    logger.debug(f"Effective workspace path for global init: {effective_workspace}")
    # Note: PenguinCore itself uses WORKSPACE_PATH from config for ProjectManager.
    # A more direct way to override this in Core would be needed if ProjectManager path needs to change.

    # Access _loaded_config as a dictionary or using property access
    streaming_enabled = not no_streaming_override
    
    # Try both attribute-style and dict-style access to handle different Config implementations
    if hasattr(_loaded_config, 'model') and callable(getattr(_loaded_config, 'model', None)):
        # Config.model() returns a dict-like object 
        model_dict = _loaded_config.model()
        streaming_enabled = not no_streaming_override and model_dict.get("streaming_enabled", True)
    elif hasattr(_loaded_config, 'model') and not callable(getattr(_loaded_config, 'model', None)):
        # Config.model is a property that returns a dict-like object
        model_dict = _loaded_config.model
        streaming_enabled = not no_streaming_override and model_dict.get("streaming_enabled", True)
    elif isinstance(_loaded_config, dict) and "model" in _loaded_config:
        # _loaded_config is a dict with a model key
        streaming_enabled = not no_streaming_override and _loaded_config["model"].get("streaming_enabled", True)
        
    # Create ModelConfig with safe access
    if hasattr(_loaded_config, 'model') and callable(getattr(_loaded_config, 'model', None)):
        # Model is a method that returns a dict-like object
        model_dict = _loaded_config.model()
        api_dict = getattr(_loaded_config, 'api', {})
        if isinstance(api_dict, dict):
            api_base = api_dict.get("base_url")
        else:
            api_base = getattr(api_dict, "base_url", None)
    elif hasattr(_loaded_config, 'model') and not callable(getattr(_loaded_config, 'model', None)):
        # Model is a property that returns a dict-like object
        model_dict = _loaded_config.model
        api_dict = getattr(_loaded_config, 'api', {})
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
        if hasattr(_loaded_config, 'fast_startup'):
            config_fast_startup = _loaded_config.fast_startup
        elif isinstance(_loaded_config, dict):
            config_fast_startup = _loaded_config.get("performance", {}).get("fast_startup", False)
    except Exception:
        pass
    
    effective_fast_startup = fast_startup_override or config_fast_startup
    
    # Convert config to dict format for ToolManager
    config_dict = _loaded_config.__dict__ if hasattr(_loaded_config, '__dict__') else _loaded_config
    _tool_manager = ToolManager(config_dict, log_error, fast_startup=effective_fast_startup)
    
    # Make sure our config is compatible with what PenguinCore expects
    wrapped_config = _ensure_config_compatible(_loaded_config)
    
    # PenguinCore's __init__ will use its passed config to set up ProjectManager with WORKSPACE_PATH
    _core = PenguinCore(
        config=wrapped_config, 
        api_client=_api_client,
        tool_manager=_tool_manager,
        model_config=_model_config
    )
    # If workspace_override needs to directly influence PenguinCore's ProjectManager path,
    # PenguinCore would need to accept a workspace_path argument or have a setter.

    _interface = PenguinInterface(_core)

    logger.info(f"Core components initialized globally in {time.time() - init_start_time:.2f}s")

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
            logger.warning("Prompt specified as '-' but stdin is a TTY. No input read for direct prompt.")
            if output_format == "text":
                console.print("[yellow]Warning: Prompt was '-' but no data piped from stdin.[/yellow]")
            elif output_format in ["json", "stream-json"]:
                print(json.dumps({"error": "Prompt was '-' but no data piped from stdin.", "assistant_response": "", "action_results": []}))
            return
    else:
        actual_prompt = prompt_text

    if not actual_prompt:
        logger.info("No prompt provided for direct execution.")
        if output_format == "text":
            console.print("[yellow]No prompt provided.[/yellow]")
        elif output_format in ["json", "stream-json"]:
            print(json.dumps({"error": "No prompt provided", "assistant_response": "", "action_results": []}))
        return

    logger.info(f"Processing direct prompt (output format: {output_format}): '{actual_prompt[:100]}...'")
    
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
        logger.info("stream-json output format selected; will output full JSON for now. True streaming TODO.")
        # Example of initial messages for true stream-json:
        # session_id_for_stream = _core.conversation_manager.get_current_session_id() # Needs method in ConversationManager
        # print(json.dumps({"type": "system", "subtype": "init", "session_id": "placeholder_session_id"}))
        # print(json.dumps({"type": "user", "message": {"content": actual_prompt}, "session_id": "placeholder_session_id"}))
        pass

    response = await _core.process(
        {"text": actual_prompt}, 
        streaming=False # For non-interactive, we process fully then format output.
                        # If output_format is stream-json, core.process would need to handle that.
    )

    if output_format == "text":
        assistant_response_text = response.get("assistant_response", "")
        if assistant_response_text: # Only print if there's something
             console.print(assistant_response_text)

        action_results = response.get("action_results", [])
        if action_results:
            for i, res in enumerate(action_results):
                if i == 0 and assistant_response_text: 
                    console.print("") 
                panel_content = (
                    f"[bold cyan]Action:[/bold cyan] {res.get('action', res.get('action_name', 'Unknown'))}\n"
                    f"[bold cyan]Status:[/bold cyan] {res.get('status', 'unknown')}\n"
                    f"[bold cyan]Result:[/bold cyan]\n{res.get('result', res.get('output','N/A'))}"
                )
                console.print(Panel(panel_content,
                                    title=f"Action Result {i+1}",
                                    padding=1, border_style="yellow"))
    elif output_format == "json" or output_format == "stream-json":
        print(json.dumps(response, indent=2))
    else:
        console.print(f"[red]Error: Unknown output format '{output_format}'. Valid options are 'text', 'json', 'stream-json'.[/red]")
        raise typer.Exit(code=1)

async def _run_interactive_chat():
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
        None, "-p", "--prompt", 
        help="Run in non-interactive mode. Use '-' to read prompt from stdin."
    ),
    output_format: str = typer.Option(
        "text", "--output-format", 
        help="Output format for -p mode (text, json, stream-json).",
        case_sensitive=False
        # autocompletion=lambda: ["text", "json", "stream-json"] # Requires Typer 0.9+
    ),
    continue_last: bool = typer.Option(
        False, "--continue", "-c",
        help="Continue the most recent conversation."
    ),
    resume_session: Optional[str] = typer.Option(
        None, "--resume",
        help="Resume a specific conversation by its session ID."
    ),
    run_task: Optional[str] = typer.Option(
        None, "--run",
        help="Run a specific task or project in autonomous mode."
    ),
    continuous: bool = typer.Option(
        False, "--247", "--continuous",
        help="Run in continuous mode until manually stopped."
    ),
    time_limit: Optional[int] = typer.Option(
        None, "--time-limit",
        help="Time limit in minutes for task/continuous execution."
    ),
    task_description: Optional[str] = typer.Option(
        None, "--description",
        help="Optional description for the task when using --run."
    ),
    model: Optional[str] = typer.Option(
        None, "--model", "-m", 
        help="Specify the model to use (e.g., 'anthropic/claude-3-5-sonnet-20240620'). Overrides config."
    ),
    workspace: Optional[Path] = typer.Option(
        None, "--workspace", "-w", 
        help="Set custom workspace path. Overrides config."
    ),
    no_streaming: bool = typer.Option(
        False, "--no-streaming", 
        help="Disable streaming mode for LLM responses (primarily for interactive mode)."
    ),
    fast_startup: bool = typer.Option(
        False, "--fast-startup", 
        help="Enable fast startup mode (defer memory indexing until first use)."
    ),
    # Add other global options from the plan here eventually
    # e.g., continue_session, resume_session_id, system_prompt_override, etc.
    version: Optional[bool] = typer.Option( # Example: adding a version flag
        None, "--version", "-v", help="Show Penguin version and exit.", is_eager=True
    )
):
    """
    Penguin AI Assistant - Your command-line AI companion.
    """
    if version:
        # TODO: Get version dynamically, e.g., from importlib.metadata or a __version__ string
        console.print("Penguin AI Assistant v0.1.0 (Placeholder Version)") 
        raise typer.Exit()

    # Skip heavy initialization for config commands and certain lightweight commands
    if ctx.invoked_subcommand in ["config"]:
        return  # Let the subcommand handle its own logic without core initialization

    # Create a sync wrapper around our async code
    async def _async_init_and_run():
        # Check if setup is needed before initializing core components
        if not setup_available:
            console.print(f"[yellow]⚠️ Setup wizard not available: {setup_import_error}[/yellow]")
            console.print("[yellow]You may need to install additional dependencies:[/yellow]")
            console.print("[yellow]  pip install questionary httpx[/yellow]")
            console.print("[yellow]Or manually create a config file.[/yellow]\n")
        elif check_first_run():
            console.print("[bold yellow]🐧 Welcome to Penguin! First-time setup is required.[/bold yellow]")
            console.print("Running setup wizard...\n")
            
            try:
                config_result = run_setup_wizard_sync()
                if config_result:
                    if "error" in config_result:
                        console.print(f"[red]Setup error: {config_result['error']}[/red]")
                        console.print("Try running 'penguin config setup' manually or check dependencies.")
                        raise typer.Exit(code=1)
                    else:
                        console.print("[bold green]Setup completed successfully![/bold green]")
                        console.print("Starting Penguin...\n")
                else:
                    console.print("[yellow]Setup was cancelled. Run 'penguin config setup' when ready.[/yellow]")
                    raise typer.Exit(code=0)
            except KeyboardInterrupt:
                console.print("\n[yellow]Setup interrupted. Run 'penguin config setup' when ready.[/yellow]")
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
                fast_startup_override=fast_startup
            )
        except Exception as e:
            logger.error(f"Fatal error during core component initialization: {e}", exc_info=True)
            console.print(f"[bold red]Fatal Initialization Error:[/bold red] {e}")
            console.print("Please check logs for more details.")
            raise typer.Exit(code=1)

        # Check for priority flags in order of precedence:
        # 1. Task execution (--run)
        if run_task is not None:
            await _handle_run_mode(run_task, continuous, time_limit, task_description)
        # 2. Session management (--continue/--resume)
        elif continue_last or resume_session:
            # We'll always go into interactive mode for session management
            if prompt is not None:
                # Combine -p with -c/--resume
                await _handle_session_management(continue_last, resume_session, prompt, output_format)
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
    description: Optional[str] = None
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
        console.print("[red]Error: Core components failed to initialize for run mode.[/red]")
        raise typer.Exit(code=1)
    
    try:
        logger.info(f"Starting run mode: task={task_name}, continuous={continuous}, time_limit={time_limit}")
        
        # Stream callbacks removed - using event system only
                    
        # Configure UI update callback (no-op for now)
        async def ui_update_callback() -> None:
            """Handle UI updates during run mode"""
            pass
            
        # Use core.start_run_mode to execute the task
        if continuous:
            console.print(f"[bold blue]Starting continuous mode{' for task: ' + task_name if task_name else ''}[/bold blue]")
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
                    stream_callback_for_cli=None,
                    ui_update_callback_for_cli=ui_update_callback
                )
            except KeyboardInterrupt:
                console.print("\n[yellow]Keyboard interrupt received. Gracefully shutting down...[/yellow]")
                # Core should handle the graceful shutdown internally
        else:
            # For single task execution
            if not task_name:
                console.print("[yellow]No task specified for run mode. Use --run <task_name> to specify a task.[/yellow]")
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
                stream_callback_for_cli=None,
                ui_update_callback_for_cli=ui_update_callback
            )
            
        console.print("[green]Run mode execution completed.[/green]")
        
    except Exception as e:
        logger.error(f"Error in run mode execution: {e}", exc_info=True)
        console.print(f"[red]Error running task: {str(e)}[/red]")
        console.print(traceback.format_exc())

async def _handle_session_management(continue_last: bool, resume_session: Optional[str], prompt: Optional[str] = None, output_format: str = "text") -> None:
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
        console.print("[red]Error: Core components failed to initialize for session management.[/red]")
        raise typer.Exit(code=1)
    
    try:
        if continue_last:
            # Get the most recent conversation ID
            conversations = _core.list_conversations(limit=1)
            if not conversations:
                console.print("[yellow]No previous conversations found to continue.[/yellow]")
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
                console.print(f"[yellow]Failed to load most recent conversation. Starting new session.[/yellow]")
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
                console.print(f"[yellow]Failed to load conversation {resume_session}. Starting new session.[/yellow]")
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
        console.print(f"[red]Error loading conversation: {str(e)}[/red]")
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
        console.print("[yellow]You may need to install additional dependencies:[/yellow]")
        console.print("[yellow]  pip install questionary httpx[/yellow]")
        console.print("[yellow]Or install with setup extras:[/yellow]")
        console.print("[yellow]  pip install penguin[setup][/yellow]")
        raise typer.Exit(code=1)
    
    try:
        config_result = run_setup_wizard_sync()
        if config_result:
            if "error" in config_result:
                console.print(f"[red]Setup error: {config_result['error']}[/red]")
                if "Missing dependencies" in config_result['error']:
                    console.print("[yellow]Please install the missing dependencies and try again.[/yellow]")
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
        console.print(f"[yellow]Could not open editor. Config file is located at:[/yellow] {config_path}")

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
        console.print("[yellow]Install setup dependencies first: pip install questionary httpx[/yellow]")
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
            required_sections = ['model', 'workspace']
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
        'PENGUIN_CONFIG_PATH',
        'PENGUIN_ROOT', 
        'PENGUIN_WORKSPACE',
        'XDG_CONFIG_HOME',
        'APPDATA'
    ]
    
    for var in env_vars:
        value = os.environ.get(var)
        if value:
            console.print(f"  {var}: {value}")
        else:
            console.print(f"  {var}: [dim]not set[/dim]")
    
    console.print(f"\n[dim]Platform: {platform.system()} {platform.release()}[/dim]")
    console.print(f"[dim]Python: {sys.version}[/dim]")

# Project Management Commands
@project_app.command("create")
def project_create(
    name: str = typer.Argument(..., help="Project name"),
    description: Optional[str] = typer.Option(None, "--description", "-d", help="Project description"),
    workspace_path: Optional[str] = typer.Option(None, "--workspace", "-w", help="Project workspace path")
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
                name=name,
                description=description or f"Project: {name}"
            )
            
            console.print(f"[green]✓ Project created successfully![/green]")
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
                console.print("[yellow]No projects found. Create one with 'penguin project create <name>'[/yellow]")
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
                project_tasks = await _core.project_manager.list_tasks_async(project_id=project.id)
                task_count = len(project_tasks)
                
                table.add_row(
                    project.id[:8],
                    project.name,
                    project.status,  # Project status is a string, not an enum
                    str(task_count),
                    project.created_at[:16] if project.created_at else "Unknown"  # created_at is ISO string, take first 16 chars (YYYY-MM-DD HH:MM)
                )
            
            console.print(table)
            
        except Exception as e:
            console.print(f"[red]Error listing projects: {e}[/red]")
            raise typer.Exit(code=1)
    
    asyncio.run(_async_project_list())

@project_app.command("delete")
def project_delete(
    project_id: str = typer.Argument(..., help="Project ID to delete"),
    force: bool = typer.Option(False, "--force", "-f", help="Force delete without confirmation")
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
                console.print(f"[red]Error: Project with ID '{project_id}' not found[/red]")
                raise typer.Exit(code=1)
            
            if not force:
                import typer
                confirm = typer.confirm(f"Are you sure you want to delete project '{project.name}' ({project_id[:8]})?")
                if not confirm:
                    console.print("[yellow]Operation cancelled[/yellow]")
                    return
            
            # Note: Need to add delete_project_async method to ProjectManager
            success = _core.project_manager.storage.delete_project(project_id)
            if not success:
                console.print(f"[red]Failed to delete project[/red]")
                raise typer.Exit(code=1)
            console.print(f"[green]✓ Project '{project.name}' deleted successfully[/green]")
            
        except Exception as e:
            console.print(f"[red]Error deleting project: {e}[/red]")
            raise typer.Exit(code=1)
    
    asyncio.run(_async_project_delete())

@project_app.command("run")
def project_run(
    spec_file: Path = typer.Argument(..., help="Path to the project specification Markdown file.", exists=True),
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
        console.print(f"[bold blue]🐧 Starting project workflow from:[/bold blue] {spec_file}")

        # --- Setup ---
        # Initialize core components to get the ProjectManager
        await _initialize_core_components_globally()
        project_manager = _core.project_manager
        
        # Use the real RunMode from the core instead of mocking
        from penguin.run_mode import RunMode
        run_mode = RunMode(_core)  # Pass the core instance

        # Initialize the rest of the managers
        if not GITHUB_REPOSITORY:
            console.print("[red]Error: GITHUB_REPOSITORY is not configured in your .env or config.yml.[/red]")
            raise typer.Exit(code=1)

        git_manager = GitManager(
            workspace_path=WORKSPACE_PATH,
            project_manager=project_manager,
            repo_owner_and_name=GITHUB_REPOSITORY
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
                markdown_content=spec_content,
                project_manager=project_manager
            )
            if parse_result["status"] != "success":
                console.print(f"[red]Error parsing spec file: {parse_result['message']}[/red]")
                raise typer.Exit(code=1)
            
            project_id = parse_result["creation_result"]["project"]["id"]
            num_tasks = parse_result["creation_result"]["tasks_created"]
            console.print(f"[green]✓ Project '{parse_result['creation_result']['project']['name']}' created with {num_tasks} task(s).[/green]")
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
                console.print(f"   [green]✓ Status: {workflow_result['status']}[/green]")
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
    description: Optional[str] = typer.Option(None, "--description", "-d", help="Task description"),
    parent_task_id: Optional[str] = typer.Option(None, "--parent", "-p", help="Parent task ID"),
    priority: int = typer.Option(1, "--priority", help="Task priority (1-5)")
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
                priority=priority
            )
            
            console.print(f"[green]✓ Task created successfully![/green]")
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
    status: Optional[str] = typer.Option(None, "--status", "-s", help="Filter by status (pending, running, completed, failed)")
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
                    console.print(f"[red]Invalid status: {status}. Valid options: pending, running, completed, failed[/red]")
                    raise typer.Exit(code=1)
            
            tasks = await _core.project_manager.list_tasks_async(
                project_id=project_id,
                status=status_filter
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
                    task.created_at[:16] if task.created_at else "Unknown"  # created_at is ISO string, take first 16 chars
                )
            
            console.print(table)
            
        except Exception as e:
            console.print(f"[red]Error listing tasks: {e}[/red]")
            raise typer.Exit(code=1)
    
    asyncio.run(_async_task_list())

@task_app.command("start")
def task_start(
    task_id: str = typer.Argument(..., help="Task ID to start")
):
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
                TaskStatus.ACTIVE  # ProjectManager uses ACTIVE instead of RUNNING
            )
            if not success:
                console.print(f"[red]Failed to start task[/red]")
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
def task_complete(
    task_id: str = typer.Argument(..., help="Task ID to complete")
):
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
                task_id, 
                TaskStatus.COMPLETED
            )
            if not success:
                console.print(f"[red]Failed to complete task[/red]")
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
    force: bool = typer.Option(False, "--force", "-f", help="Force delete without confirmation")
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
                confirm = typer.confirm(f"Are you sure you want to delete task '{task.title}' ({task_id[:8]})?")
                if not confirm:
                    console.print("[yellow]Operation cancelled[/yellow]")
                    return
            
            # Note: Need to add delete_task_async method to ProjectManager
            success = _core.project_manager.storage.delete_task(task_id)
            if not success:
                console.print(f"[red]Failed to delete task[/red]")
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

    # Language detection and mapping
    CODE_BLOCK_PATTERNS = [
        # Standard markdown code blocks with language specification
        (r"```(\w+)(.*?)```", "{}"),  # Captures language and code
        # Execute blocks (for backward compatibility)
        (r"<execute>(.*?)</execute>", "python"),
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
        "text": "Code",
    }

    def __init__(self, core):
        self.core = core
        self.interface = PenguinInterface(core)
        self.in_247_mode = False
        self.message_count = 0
        self.console = RichConsole()  # Use RichConsole instead of Console
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

        # Conversation turn tracking
        self.current_conversation_turn = 0
        self.message_turn_map = {}

        # Add streaming state tracking
        self.is_streaming = False
        self.streaming_buffer = ""
        self.streaming_role = "assistant"

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
        self._active_stream_id = None      # NEW – authoritative stream identifier from Core
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

    def display_message(self, message: str, role: str = "assistant"):
        """Display a message with proper formatting"""
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

        # If we're currently streaming and this is the same content, finalize the stream instead
        if role == "assistant" and hasattr(self, "_streaming_started") and self._streaming_started:
            if message == self.streaming_buffer:
                self._finalize_streaming()
                return

        styles = {
            "assistant": self.PENGUIN_COLOR,
            "user": self.USER_COLOR,
            "system": self.TOOL_COLOR,
            "error": "red bold",
            "output": self.RESULT_COLOR,
            "code": self.CODE_COLOR,
        }

        emojis = {
            "assistant": self.PENGUIN_EMOJI,
            "user": "👤",
            "system": "🐧",
            "error": "⚠️",
            "code": "💻",
        }

        style = styles.get(role, "white")
        emoji = emojis.get(role, "💬")

        # Special handling for welcome message
        if role == "system" and "Welcome to the Penguin AI Assistant!" in message:
            header = f"{emoji} System (Welcome):"
        else:
            display_role = "Penguin" if role == "assistant" else role.capitalize()
            header = f"{emoji} {display_role}"

        # Enhanced code block formatting
        processed_message = message or ""
        code_blocks_found = False

        # Process all code block patterns
        for pattern, default_lang in self.CODE_BLOCK_PATTERNS:
            # Extract code blocks with this pattern
            matches = re.findall(pattern, processed_message, re.DOTALL)
            if not matches:
                continue

            # Process matches based on pattern type
            if default_lang == "{}":  # Standard markdown code block
                for lang, code in matches:
                    if not lang:
                        lang = "text"  # Default to plain text if no language specified
                    code_blocks_found = True
                    processed_message = self._format_code_block(
                        processed_message, code, lang, f"```{lang}{code}```"
                    )
            else:  # Tag-based code block
                for i, code_match in enumerate(matches):
                    # Handle single group or multi-group regex results
                    code = code_match if isinstance(code_match, str) else code_match[0]
                    lang = default_lang

                    tag_start = f"<{lang}>" if lang != "python" else "<execute>"
                    tag_end = f"</{lang}>" if lang != "python" else "</execute>"
                    original_block = f"{tag_start}{code}{tag_end}"

                    code_blocks_found = True
                    processed_message = self._format_code_block(
                        processed_message, code, lang, original_block
                    )

        # Special case: Look for code-like content in non-tagged system messages
        if role == "system" and not code_blocks_found:
            # Try to find code-like blocks in the message
            lines = processed_message.split("\n")
            code_block_lines = []
            in_code_block = False
            start_line = 0

            for i, line in enumerate(lines):
                # Heuristics to detect code block starts:
                # - Line starts with indentation followed by code-like content
                # - Line contains common code elements like 'def', 'import', etc.
                # - Line starts with a common programming construct
                code_indicators = [
                    re.match(r"\s{2,}[a-zA-Z0-9_]", line),  # Indented code
                    re.search(
                        r"(def|class|import|function|var|let|const)\s+", line
                    ),  # Keywords
                    re.match(r"[a-zA-Z0-9_\.]+\s*\(.*\)", line),  # Function calls
                    re.search(r"=.*?;?\s*$", line),  # Assignments
                ]

                if any(code_indicators) and not in_code_block:
                    # Start of a potential code block
                    in_code_block = True
                    start_line = i
                elif in_code_block and (not line.strip() or not any(code_indicators)):
                    # End of a code block
                    if i - start_line > 1:  # At least 2 lines of code
                        code_text = "\n".join(lines[start_line:i])
                        lang = self._detect_language(code_text)

                        # Only format if it looks like valid code
                        if lang != "text":
                            # Replace in the original message
                            for j in range(start_line, i):
                                lines[j] = ""
                            lines[start_line] = (
                                f"[Code block displayed below ({self.LANGUAGE_DISPLAY_NAMES.get(lang, lang.capitalize())})]"
                            )

                            # Add to code blocks
                            code_block_lines.append((code_text, lang))

                    in_code_block = False

            # Handle a code block that goes to the end
            if in_code_block and len(lines) - start_line > 1:
                code_text = "\n".join(lines[start_line:])
                lang = self._detect_language(code_text)

                if lang != "text":
                    # Replace in the original message
                    for j in range(start_line, len(lines)):
                        lines[j] = ""
                    lines[start_line] = (
                        f"[Code block displayed below ({self.LANGUAGE_DISPLAY_NAMES.get(lang, lang.capitalize())})]"
                    )

                    # Add to code blocks
                    code_block_lines.append((code_text, lang))

            # Reassemble the message
            processed_message = "\n".join(lines)

            # Display the detected code blocks
            for code_text, lang in code_block_lines:
                lang_display = self.LANGUAGE_DISPLAY_NAMES.get(lang, lang.capitalize())
                highlighted_code = Syntax(
                    code_text.strip(),
                    lang,
                    theme="monokai",
                    line_numbers=True,
                    word_wrap=True,
                )

                code_panel = Panel(
                    highlighted_code,
                    title=f"📋 {lang_display} Code",
                    title_align="left",
                    border_style=self.CODE_COLOR,
                    padding=(1, 2),
                )
                self.console.print(code_panel)

        # Handle code blocks in tool outputs (like execute results)
        if (
            role == "system"
            and "action" in message.lower()
            and "result" in message.lower()
        ):
            # Check if this is a code execution result
            if "execute" in message.lower():
                # Try to extract the code output
                match = re.search(r"Result: (.*?)(?:Status:|$)", message, re.DOTALL)
                if match:
                    code_output = match.group(1).strip()
                    # Detect if this contains code
                    if code_output and (
                        code_output.count("\n") > 0
                        or "=" in code_output
                        or "def " in code_output
                        or "import " in code_output
                    ):
                        # Detect language
                        language = self._detect_language(code_output)
                        lang_display = self.LANGUAGE_DISPLAY_NAMES.get(
                            language, language.capitalize()
                        )

                        # Display output in a special panel
                        self._display_code_output_panel(code_output, language, "Output")
                        # Simplify the message to avoid duplication
                        processed_message = message.replace(
                            code_output, f"[{lang_display} output displayed above]"
                        )

        # Regular message display with markdown
        panel = Panel(
            Markdown(processed_message),
            title=header,
            title_align="left",
            border_style=style,
            width=self.console.width - 8,
            box=rich.box.ROUNDED,
        )
        self.console.print(panel)

        # If message is suspiciously short, could provide visual indication
        if len(message.strip()) <= 1:
            # Add visual indicator that response was truncated
            message = f"{message} [Response truncated due to context limitations]"

    def _format_code_block(self, message, code, language, original_block):
        """Format a code block with syntax highlighting and return updated message"""
        # Get the display name for the language or use language code as fallback
        lang_display = self.LANGUAGE_DISPLAY_NAMES.get(language, language.capitalize())

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

    def _display_code_output_panel(self, code_output: str, language: str, title: str = "Output"):
        lang_display = self.LANGUAGE_DISPLAY_NAMES.get(language, language.capitalize())
        output_panel = Panel(
            Syntax(code_output, language, theme="monokai", word_wrap=True),
            title=f"📤 {lang_display} {title}",
            title_align="left",
            border_style="green", # Or self.RESULT_COLOR
            padding=(1, 2),
            width=self.console.width - 8 if self.console else None
        )
        if self.console:
            self.console.print(output_panel)
        else: # Fallback if console not available (e.g. direct prompt mode context)
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
                        project.get("created_at", "")[:16] if project.get("created_at") else ""
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
                        task.get("created_at", "")[:16] if task.get("created_at") else ""
                    )
                
                self.console.print(table)
            
            # If no projects or tasks
            if not projects and not tasks:
                self.display_message("No projects or tasks found. Create some with `/project create` or `/task create`.", "system")
                
        except Exception as e:
            # Fallback to simple text display
            logger.error(f"Error displaying list response: {e}")
            self.display_message(f"Projects and Tasks:\n{json.dumps(response, indent=2)}", "system")

    def display_action_result(self, result: Dict[str, Any]):
        """Display action results in a more readable format"""
        # This method is part of PenguinCLI, used in interactive mode.
        # For direct prompt mode, _run_penguin_direct_prompt handles its own output.
        if not self.console: # Should not happen in interactive mode
            logger.warning("display_action_result called without a console.")
            return

        action_type = result.get("action", result.get("action_name", "unknown"))
        result_text = str(result.get("result", result.get("output", ""))) # Ensure string
        status = result.get("status", "unknown")
        
        status_icon = "✓" if status == "completed" else ("⏳" if status == "pending" else "❌")
        header = f"🔧 Action Result: {action_type}"
        
        # If result_text is code-like, use Syntax highlighting
        is_code_output = False
        detected_lang = "text"
        if result_text.strip() and ('\n' in result_text or any(kw in result_text for kw in ["def ", "class ", "import ", "function ", "const ", "let "])):
            is_code_output = True
            detected_lang = self._detect_language(result_text)

        if is_code_output:
            lang_display = self.LANGUAGE_DISPLAY_NAMES.get(detected_lang, detected_lang.capitalize())
            content_renderable = Syntax(result_text, detected_lang, theme="monokai", word_wrap=True, line_numbers=True)
            title_for_panel = f"{status_icon} {lang_display} Output from {action_type}"
        else:
            content_renderable = Markdown(result_text if result_text.strip() else "(No textual output)")
            title_for_panel = f"{status_icon} Result from {action_type}"

        # Create and display panel (moved outside the if/else blocks)
        panel = Panel(
            content_renderable,
            title=title_for_panel,
            title_align="left",
            border_style=self.TOOL_COLOR if status != "error" else "red",
            width=self.console.width - 8,
            padding=(1,1)
        )
        self.console.print(panel)

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
        session_logger = setup_logger(f"chat_{session_id}.log")

        welcome_message = """Welcome to the Penguin AI Assistant!

Available Commands:

 • /chat: Conversation management
   - list: Show available conversations
   - load: Load a previous conversation
   - summary: Show current conversation summary
   
 • /list: Display all projects and tasks

 • /task: Task management commands
   - create [name] [description]: Create a new task
   - run [name]: Run a task
   - status [name]: Check task status
   
 • /project: Project management commands
   - create [name] [description]: Create a new project
   - run [name]: Run a project
   - status [name]: Check project status
   
 • /models: Interactive model selection (search with autocomplete)
 • /model set <id>: Manually set a specific model ID
   
 • /exit or exit: End the conversation

 • /image: Include an image in your message
   - image [image_path] [description]: Include an image in your message

 • /help or help: Show this help message

Press Tab for command completion Use ↑↓ to navigate command history Press Ctrl+C to stop a running task"""

        self.display_message(welcome_message, "system")
        self.display_message(
            "TIP: Use Alt+Enter for new lines, Enter to submit", "system"
        )

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
                self.last_completed_message = ""

                # Show user input
                self.display_message(user_input, "user")

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
                                runmode_ui_update_cb=ui_update_callback
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
                                    image_path = input("Drag and drop your image here: ").strip().replace("'", "")

                                # Validate the file exists
                                if not image_path or not os.path.exists(image_path):
                                    self.display_message(f"Image file not found: {image_path}", "error")
                                    continue

                                # Remaining part (index 2) is the description if present
                                if len(command_parts) > 2:
                                    description = command_parts[2]
                                if not description.strip():
                                    description = input("Description (optional): ").strip()

                                # Send the message through the standard interface path so all
                                # normal streaming / action-result handling is reused
                                response = await self.interface.process_input(
                                    {"text": description, "image_path": image_path},
                                    stream_callback=self.stream_callback,
                                )

                                # Finalise any streaming still active
                                if hasattr(self, "_streaming_started") and self._streaming_started:
                                    self._finalize_streaming()

                                # Display any action results (e.g. vision-tool output)
                                if isinstance(response, dict) and "action_results" in response:
                                    for result in response["action_results"]:
                                        if isinstance(result, dict):
                                            if "action" not in result:
                                                result["action"] = "unknown"
                                            if "result" not in result:
                                                result["result"] = "(No output available)"
                                            if "status" not in result:
                                                result["status"] = "completed"
                                            self.display_action_result(result)
                                        else:
                                            self.display_message(str(result), "system")
                            except Exception as e:
                                self.display_message(f"Error processing image command: {str(e)}", "error")
                                self.display_message(traceback.format_exc(), "error")
                            continue  # Skip default command processing for /image
                        else:
                            # Regular command handling
                            response = await self.interface.handle_command(user_input[1:])
                        
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
                                help_text = response["help"] + "\n\n" + "\n".join(response.get("commands", []))
                                self.display_message(help_text, "system")
                                
                            # Handle conversation list
                            elif "conversations" in response:
                                conversation_summaries = response["conversations"]
                                selected_id = self.conversation_menu.select_conversation(conversation_summaries)
                                if selected_id:
                                    load_result = await self.interface.handle_command(f"chat load {selected_id}")
                                    if "status" in load_result:
                                        self.display_message(load_result["status"], "system")
                                    elif "error" in load_result:
                                        self.display_message(load_result["error"], "error")
                    
                            # Handle token usage display
                            elif "token_usage" in response:
                                token_data = response["token_usage"]
                                token_msg = f"Current token usage:\n"
                                token_msg += f"Total tokens: {token_data.get('current_total_tokens', 0)} / {token_data.get('max_tokens', 0)} "
                                token_msg += f"({token_data.get('percentage', 0):.1f}%)\n\n"
                                
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
                                    current_marker = "→ " if model.get("current", False) else "  "
                                    models_msg += f"{current_marker}{model.get('name')} ({model.get('provider')})\n"
                                self.display_message(models_msg, "system")
                                
                            # Handle list command response
                            elif "projects" in response and "tasks" in response:
                                self._display_list_response(response)
                    except Exception as e:
                        self.display_message(f"Error executing command: {str(e)}", "error")
                        self.display_message(traceback.format_exc(), "error")
                    
                    continue  # Back to prompt after command processing

                # Process normal message input through interface
                try:
                    # Process user message through interface
                    response = await self.interface.process_input(
                        {"text": user_input},
                        stream_callback=None  # Events handle streaming display
                    )
                    
                    # Assistant responses (streaming or not) are now delivered via Core events.
                    # Therefore, avoid printing them directly here to prevent duplicates.
                    # Action results will still be handled below.
                    
                    # Make sure to finalize any streaming that might still be in progress
                    if hasattr(self, "_streaming_started") and self._streaming_started:
                        self._finalize_streaming()
                        
                    # Display any action results returned by the interface/core.
                    if isinstance(response, dict) and "action_results" in response:
                            print(f"[DEBUG] Found {len(response['action_results'])} action result(s)")
                            for i, result in enumerate(response["action_results"]):
                                print(f"[DEBUG] Processing action result #{i}")
                                if isinstance(result, dict):
                                # Ensure required fields exist with sensible defaults
                                    if "action" not in result:
                                        result["action"] = "unknown"
                                    if "result" not in result:
                                        result["result"] = "(No output available)"
                                    if "status" not in result:
                                        result["status"] = "completed"
                                    self.display_action_result(result)
                                else:
                                # Fallback for non-dict results
                                    self.display_message(str(result), "system")
                
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
                    self.display_message(f"Error processing input: {str(e)}", "error")
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
                self.display_message(f"[DEBUG] Chat loop error: {str(e)}", "error")
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
                    except Exception as e:
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
                    self.display_message(
                        f"Error loading conversation: {str(e)}", "error"
                    )

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
                    self.streaming_buffer += chunk
                    
                    # Update or create streaming panel
                    if not getattr(self, "streaming_live", None):
                        panel = Panel(
                            Markdown(self.streaming_buffer),
                            title=f"{self.PENGUIN_EMOJI} Penguin (Streaming)",
                            title_align="left",
                            border_style=self.PENGUIN_COLOR,
                            width=self.console.width - 8,
                        )
                        self.streaming_live = Live(
                            panel,
                            refresh_per_second=10,
                            console=self.console,
                            vertical_overflow="visible",
                        )
                        self.streaming_live.start()
                    else:
                        try:
                            panel = Panel(
                                Markdown(self.streaming_buffer),
                                title=f"{self.PENGUIN_EMOJI} Penguin (Streaming)",
                                title_align="left",
                                border_style=self.PENGUIN_COLOR,
                                width=self.console.width - 8,
                            )
                            self.streaming_live.update(panel)
                        except Exception:
                            # fallback
                            print(chunk, end="", flush=True)

                if is_final:
                    # Final chunk received - display final message and clean up
                    self.is_streaming = False
                    
                    # Display the final message as a regular panel (not streaming)
                    if self.streaming_buffer.strip():
                        self.display_message(self.streaming_buffer, self.streaming_role)
                        # Store for deduplication
                        self.last_completed_message = self.streaming_buffer

                    # Clean up streaming panel
                    self._finalize_streaming()
                    self._active_stream_id = None

                    # Store completed message for deduplication
                    if self.streaming_buffer.strip():
                        completed_msg_key = f"{self.streaming_role}:{self.streaming_buffer[:50]}"
                        self.processed_messages.add(completed_msg_key)
                        self.message_turn_map[completed_msg_key] = self.current_conversation_turn

                    # Reset buffer
                    self.streaming_buffer = ""
                    return

            elif event_type == "token_update":
                # Could update a token display here if we add one
                pass

            elif event_type == "message":
                # A new message has been added to the conversation
                role = data.get("role", "unknown")
                content = data.get("content", "")
                category = data.get("category", MessageCategory.DIALOG)

                # Allow system output messages (tool results) to be displayed
                if category == MessageCategory.SYSTEM_OUTPUT or category == "SYSTEM_OUTPUT":
                    # Display tool results immediately
                    self.display_message(content, "system")
                    return
                    
                # Skip other internal system messages
                if category == MessageCategory.SYSTEM or category == "SYSTEM":
                    return

                # Generate a message key and check if we've already processed this message
                msg_key = f"{role}:{content[:50]}"
                if msg_key in self.processed_messages:
                    return

                # If this is a user message, it's the start of a new conversation turn
                if role == "user":
                    # Increment conversation turn counter
                    self.current_conversation_turn += 1

                    # Clear streaming state for new turn
                    self.is_streaming = False
                    self.streaming_buffer = ""
                    self.last_completed_message = ""

                # For assistant messages, check if this was already displayed via streaming
                if role == "assistant":
                    # Skip if this message was already displayed via streaming
                    if content == self.last_completed_message:
                        # Add to processed messages to avoid future duplicates
                        self.processed_messages.add(msg_key)
                        self.message_turn_map[msg_key] = self.current_conversation_turn
                        return

                # Add to processed messages and map to current turn
                self.processed_messages.add(msg_key)
                self.message_turn_map[msg_key] = self.current_conversation_turn

                # Display the message
                self.display_message(content, role)

            elif event_type == "status":
                # Handle status events like RunMode updates
                status_type = data.get("status_type", "")

                # Update RunMode status
                if "task_started" in status_type:
                    self.run_mode_active = True
                    task_name = data.get("data", {}).get("task_name", "Unknown task")
                    self.run_mode_status = f"Task '{task_name}' started"
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
            self.display_message(f"Error processing event: {str(e)}", "error")

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


@app.command()
async def chat(): # Removed model, workspace, no_streaming options
    """Start an interactive chat session with Penguin."""
    global _core # Ensure we're referring to the global
    if not _core:
        # This should ideally be caught by main_entry's initialization.
        # If `penguin chat` is called directly, main_entry runs first.
        logger.warning("Chat command invoked, but core components appear uninitialized. main_entry should handle this.")
        # Attempting to initialize with defaults if somehow missed.
        try:
            await _initialize_core_components_globally()
        except Exception as e:
            logger.error(f"Error re-initializing core for chat command: {e}", exc_info=True)
            console.print(f"[red]Error: Core components failed to initialize for chat: {e}[/red]")
            raise typer.Exit(code=1)
        
        if not _core: # Still not initialized after attempt
            console.print("[red]Critical Error: Core components could not be initialized.[/red]")
            raise typer.Exit(code=1)
            
    await _run_interactive_chat()

# Profile command remains largely the same, ensure it uses `console` correctly
@app.command()
def perf_test(
    iterations: int = typer.Option(3, "--iterations", "-i", help="Number of test iterations to run"),
    show_report: bool = typer.Option(True, "--show-report/--no-report", help="Show detailed performance report"),
):
    """
    Run startup performance benchmarks to compare normal vs fast startup modes.
    """
    async def _async_perf_test():
        from penguin.utils.profiling import enable_profiling, reset_profiling, print_startup_report
        import time
        
        console.print("[bold blue]🚀 Penguin Startup Performance Test[/bold blue]")
        console.print("="*60)
        
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
                core_normal = await PenguinCore.create(fast_startup=False, show_progress=False)
                normal_time = time.perf_counter() - start_time
                normal_times.append(normal_time)
                console.print(f"    ✓ Normal startup: {normal_time:.4f}s")
                
                # Clean up
                if hasattr(core_normal, 'reset_state'):
                    await core_normal.reset_state()
                del core_normal
                
            except Exception as e:
                console.print(f"    ✗ Normal startup failed: {e}")
                normal_times.append(float('inf'))
            
            # Test fast startup
            console.print("  Testing fast startup...")
            reset_profiling()
            start_time = time.perf_counter()
            
            try:
                from penguin.core import PenguinCore
                core_fast = await PenguinCore.create(fast_startup=True, show_progress=False)
                fast_time = time.perf_counter() - start_time
                fast_times.append(fast_time)
                console.print(f"    ✓ Fast startup: {fast_time:.4f}s")
                
                # Clean up
                if hasattr(core_fast, 'reset_state'):
                    await core_fast.reset_state()
                del core_fast
                
            except Exception as e:
                console.print(f"    ✗ Fast startup failed: {e}")
                fast_times.append(float('inf'))
        
        # Calculate statistics
        valid_normal = [t for t in normal_times if t != float('inf')]
        valid_fast = [t for t in fast_times if t != float('inf')]
        
        console.print(f"\n[bold blue]📊 Performance Results ({iterations} iterations)[/bold blue]")
        console.print("="*60)
        
        if valid_normal and valid_fast:
            avg_normal = sum(valid_normal) / len(valid_normal)
            avg_fast = sum(valid_fast) / len(valid_fast)
            
            improvement = ((avg_normal - avg_fast) / avg_normal) * 100
            speedup = avg_normal / avg_fast if avg_fast > 0 else float('inf')
            
            console.print(f"Normal startup:  {avg_normal:.4f}s avg (range: {min(valid_normal):.4f}s - {max(valid_normal):.4f}s)")
            console.print(f"Fast startup:    {avg_fast:.4f}s avg (range: {min(valid_fast):.4f}s - {max(valid_fast):.4f}s)")
            console.print(f"")
            console.print(f"Performance improvement: [bold green]{improvement:.1f}% faster[/bold green]")
            console.print(f"Speedup factor: [bold green]{speedup:.2f}x[/bold green]")
            
            if improvement > 0:
                console.print("\n[bold green]🎉 Fast startup mode is working![/bold green]")
            else:
                console.print("\n[bold yellow]⚠️ Fast startup mode might not be working as expected[/bold yellow]")
        else:
            console.print("[red]Could not complete performance tests due to errors[/red]")
        
        if show_report:
            console.print(f"\n[bold blue]📈 Detailed Performance Report[/bold blue]")
            print_startup_report()
    
    asyncio.run(_async_perf_test())

@app.command()
def profile(
    output_file: str = typer.Option("penguin_profile", "--output", "-o", help="Output file name for profile data (without extension)"),
    view: bool = typer.Option(False, "--view", "-v", help="Open the profile visualization after saving"),
):
    """
    Start Penguin with profiling enabled to analyze startup performance.
    Results are saved for later analysis with tools like snakeviz.
    """
    import cProfile
    import pstats
    import io
    # from pathlib import Path # Already imported
    import subprocess
    # import sys # Already imported
    
    # Create a profile directory if it doesn't exist
    profile_dir = Path("profiles")
    profile_dir.mkdir(exist_ok=True)
    
    # Prepare the output file name
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    actual_output_file = output_file if output_file != "penguin_profile" else f"penguin_profile_{timestamp}"
    
    output_path = profile_dir / f"{actual_output_file}.prof"
    stats_path = profile_dir / f"{actual_output_file}.txt"
    
    console.print(f"[bold blue]Starting Penguin with profiling enabled...[/bold blue]")
    console.print(f"Profile data will be saved to: [cyan]{output_path}[/cyan]")
    
    def run_profiled_penguin_interactive():
        # This will now go through the main_entry, which initializes and runs interactive.
        # We need to simulate running `penguin` command itself.
        # For profiling, it's better to profile the actual `app()` call or a specific async function.
        # Let's profile the `_run_interactive_chat` after components are initialized.
        async def profiled_interactive_session():
            await _initialize_core_components_globally() # Ensure init
            await _run_interactive_chat()

        try:
            asyncio.run(profiled_interactive_session())
        except KeyboardInterrupt:
            console.print("[yellow]Penguin interactive session interrupted by user during profiling.[/yellow]")
        except SystemExit: # Catch typer.Exit
            console.print("[yellow]Penguin exited during profiling (SystemExit).[/yellow]")
        except Exception as e:
            console.print(f"[red]Error during profiled interactive run: {str(e)}[/red]")
            logger.error(f"Profiling error: {e}", exc_info=True)


    profiler = cProfile.Profile()
    profiler.enable()
    
    run_profiled_penguin_interactive() # Call the modified function
        
    profiler.disable()
    console.print("[green]Profiling complete.[/green]")
        
    profiler.dump_stats(str(output_path))
    console.print(f"Profile data saved to: [cyan]{output_path}[/cyan]")
        
    s = io.StringIO()
    # Sort by cumulative time, then standard name for consistent ordering
    ps = pstats.Stats(profiler, stream=s).sort_stats('cumulative', 'name')
    ps.print_stats(30)  # Print top 30 functions
    stats_content = s.getvalue()
        
    with open(stats_path, 'w') as f:
            f.write(stats_content)
        
    console.print(f"Profile summary saved to: [cyan]{stats_path}[/cyan]")
    console.print("[bold]Top 30 functions by cumulative time:[/bold]")
    console.print(stats_content)
        
    if view:
        try:
                subprocess.run(["snakeviz", str(output_path)], check=True)
        except FileNotFoundError:
            console.print(f"[yellow]snakeviz command not found. Please install snakeviz to view profiles.[/yellow]")
            console.print(f"[yellow]You can manually visualize the profile with: snakeviz {output_path}[/yellow]")
        except Exception as e:
                console.print(f"[yellow]Could not open visualization: {str(e)}[/yellow]")
                console.print(f"[yellow]You can manually visualize the profile with: snakeviz {output_path}[/yellow]")

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
    except Exception as e: # Catch any unhandled exceptions from Typer/asyncio layers
        logger.critical(f"Unhandled exception at CLI entry point: {e}", exc_info=True)
        console.print(f"[bold red]Unhandled Critical Error:[/bold red] {e}")
        console.print("This is unexpected. Please check logs or report this issue.")
        sys.exit(1)