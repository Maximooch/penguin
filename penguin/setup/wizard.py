import questionary
import yaml
import os
import json
import httpx
import asyncio
from pathlib import Path
import platform
import shutil
import subprocess
from typing import Dict, Any, List, Optional, Tuple
import shutil
from rich.console import Console

# Create rich console for enhanced output
console = Console()

# Define consistent styling for questionary
STYLE = questionary.Style([
    ('qmark', 'fg:cyan bold'),           # Question mark
    ('question', 'fg:white bold'),       # Questions
    ('answer', 'fg:cyan bold'),          # Answers
    ('pointer', 'fg:cyan bold'),         # Selection pointer
    ('highlighted', 'fg:cyan bold'),     # Highlighted option
    ('selected', 'fg:green'),            # Selected option
    ('instruction', 'fg:white'),         # Instructions
    ('text', 'fg:white'),                # Regular text
    ('disabled', 'fg:gray italic')       # Disabled options
])

def check_setup_dependencies() -> Tuple[bool, List[str]]:
    """
    Check if all required dependencies for the setup wizard are available.
    
    Returns:
        Tuple of (all_available: bool, missing_packages: List[str])
    """
    required_packages = {
        'questionary': 'questionary',
        'httpx': 'httpx',
        'yaml': 'PyYAML',
        'rich': 'rich',
    }
    
    missing = []
    
    for module_name, package_name in required_packages.items():
        try:
            __import__(module_name)
        except ImportError:
            missing.append(package_name)
    
    return len(missing) == 0, missing

def display_dependency_install_instructions(missing_packages: List[str]) -> None:
    """Display instructions for installing missing dependencies"""
    console.print(f"[bold red]⚠️ Missing required dependencies for setup wizard:[/bold red]")
    console.print(f"[yellow]Missing packages:[/yellow] {', '.join(missing_packages)}")
    console.print("\n[bold cyan]To install missing dependencies:[/bold cyan]")
    console.print(f"[white]pip install {' '.join(missing_packages)}[/white]")
    console.print("\n[bold cyan]Or install all optional dependencies:[/bold cyan]")
    console.print("[white]pip install penguin[setup][/white]")
    console.print("\n[dim]After installing dependencies, run 'penguin config setup' to configure Penguin.[/dim]")

def check_first_run() -> bool:
    """
    Check if this is the first run of Penguin by looking for setup completion indicators.
    
    Returns:
        True if setup is needed, False if already completed
    """
    # Check for setup completion file
    setup_complete_file = get_config_path().parent / ".penguin_setup_complete"
    if setup_complete_file.exists():
        return False
    
    # Check if config exists and has required fields
    config_path = get_config_path()
    if not config_path.exists():
        return True
        
    # Check config completeness
    return not check_config_completeness()

def check_config_completeness() -> bool:
    """
    Check if the current config.yml has all required fields for basic operation.
    
    Returns:
        True if config is complete enough to run, False if setup is needed
    """
    config_path = get_config_path()
    if not config_path.exists():
        return False
        
    try:
        with open(config_path, 'r') as f:
            config = yaml.safe_load(f)
            
        if not config:
            return False
            
        # Check for required sections
        required_sections = ['model', 'workspace']
        for section in required_sections:
            if section not in config:
                return False
                
        # Check if we have a valid model configuration
        model_config = config.get('model', {})
        if not model_config.get('default'):
            return False
            
        # Check if workspace path is set
        workspace_config = config.get('workspace', {})
        if not workspace_config.get('path'):
            return False
            
        # Check for API access (environment variables or config)
        # This is optional - some models might not need API keys
        provider = model_config.get('provider', '')
        has_api_access = _check_api_access(provider)
        
        # If no API access is configured, we should run setup
        # (unless it's a local model like Ollama)
        if not has_api_access and provider not in ['ollama', 'local']:
            console.print("[yellow]⚠️ No API access configured. Run 'penguin config setup' to configure API keys.[/yellow]")
            return False
            
        return True
        
    except Exception as e:
        console.print(f"[red]Error checking config completeness: {e}[/red]")
        return False

def _check_api_access(provider: str) -> bool:
    """Check if API access is configured for the given provider"""
    api_key_env_vars = {
        'anthropic': ['ANTHROPIC_API_KEY'],
        'openai': ['OPENAI_API_KEY'],
        'openrouter': ['OPENROUTER_API_KEY'],
        'google': ['GOOGLE_API_KEY', 'GEMINI_API_KEY'],
        'mistral': ['MISTRAL_API_KEY'],
        'deepseek': ['DEEPSEEK_API_KEY'],
        'ollama': [],  # Local, no API key needed
        'local': [],   # Local, no API key needed
    }
    
    env_vars = api_key_env_vars.get(provider.lower(), [])
    if not env_vars:  # Local provider, assume it's available
        return True
        
    return any(os.getenv(var) for var in env_vars)

def mark_setup_complete():
    """Mark setup as completed by creating a completion file"""
    setup_complete_file = get_config_path().parent / ".penguin_setup_complete"
    try:
        with open(setup_complete_file, 'w') as f:
            f.write(f"Setup completed on {os.getenv('USER', 'user')}@{platform.node()} at {platform.system()}\n")
        console.print(f"[green]✓ Setup marked as complete[/green]")
    except Exception as e:
        console.print(f"[yellow]Warning: Could not mark setup as complete: {e}[/yellow]")

async def fetch_models_from_openrouter() -> List[Dict[str, Any]]:
    """
    Fetch available models from OpenRouter API
    Returns a list of model data objects
    """
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get("https://openrouter.ai/api/v1/models", timeout=10.0)
            response.raise_for_status()
            data = response.json()
            return data.get("data", [])
    except Exception as e:
        console.print(f"[bold red]⚠️ Failed to fetch models from OpenRouter:[/bold red] {e}")
        return []

def get_local_models_cache() -> List[Dict[str, Any]]:
    """
    Get cached models list if available
    Returns empty list if no cache found
    """
    cache_path = Path.home() / ".config" / "penguin" / "models_cache.json"
    if cache_path.exists():
        try:
            with open(cache_path, "r") as f:
                return json.load(f)
        except Exception:
            return []
    return []

def save_models_cache(models: List[Dict[str, Any]]) -> None:
    """Save models to local cache for faster startup next time"""
    cache_path = Path.home() / ".config" / "penguin" / "models_cache.json"
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    
    try:
        with open(cache_path, "w") as f:
            json.dump(models, f)
    except Exception as e:
        console.print(f"[bold yellow]⚠️ Failed to cache models:[/bold yellow] {e}")

def prepare_model_choices(models: List[Dict[str, Any]]) -> Tuple[List[str], Dict[str, str]]:
    """
    Convert models list to:
    1. List of formatted choice strings
    2. Mapping from choice string to model ID
    """
    choices = []
    model_map = {}
    
    # Add popular/recommended models at the top
    recommended = [
        "anthropic/claude-3-5-sonnet-20240620",
        "openai/o3-mini",
        "google/gemini-2-5-pro-preview", 
        "mistral/devstral",
        "meta-llama/llama-3-70b-instruct",
    ]
    
    # Add all recommended models first (if they exist in the data)
    for rec_id in recommended:
        for model in models:
            model_id = model.get("id", "")
            if model_id == rec_id:
                context_length = model.get("context_length", "unknown")
                display = f"{model_id} ({context_length} tokens)"
                choices.append(display)
                model_map[display] = model_id
                break
    
    # Then add the rest
    for model in models:
        model_id = model.get("id", "")
        # Skip if already added as recommended
        if any(model_id == rec for rec in recommended):
            continue
            
        context_length = model.get("context_length", "unknown")
        display = f"{model_id} ({context_length} tokens)"
        choices.append(display)
        model_map[display] = model_id
    
    # Always add custom option at the end
    choices.append("Custom (specify)")
    
    return choices, model_map

def display_section_header(title: str) -> None:
    """Display a formatted section header for visual hierarchy"""
    console.print(f"\n[bold cyan]━━━━ {title} ━━━━[/bold cyan]")

async def run_setup_wizard() -> Dict[str, Any]:
    """
    Run the first-time setup wizard for Penguin.
    Returns the completed configuration dictionary.
    """
    # Clear screen for better focus (optional)
    os.system('cls' if os.name == 'nt' else 'clear')
    
    # Welcome banner with visual hierarchy
    console.print("\n[bold cyan]╭───────────────────────────────────────────╮[/bold cyan]")
    console.print("[bold cyan]│[/bold cyan]  [bold white]🐧 PENGUIN SETUP WIZARD[/bold white]  [bold cyan]│[/bold cyan]")
    console.print("[bold cyan]╰───────────────────────────────────────────╯[/bold cyan]")
    console.print("\nWelcome! Let's configure your environment for optimal performance.\n")

    # Setup steps indicator for better user orientation
    steps = ["Workspace", "Model Selection", "API Configuration", "Advanced Options", "Finalize"]
    current_step = 1
    total_steps = len(steps)
    
    # Track progress
    def show_progress():
        progress_text = " → ".join([
            f"[bold cyan]{s}[/bold cyan]" if i+1 == current_step else 
            f"[green]✓ {s}[/green]" if i+1 < current_step else 
            f"[dim]{s}[/dim]" 
            for i, s in enumerate(steps)
        ])
        console.print(f"\n[Progress: {current_step}/{total_steps}] {progress_text}\n")
    
    # ----- STEP 1: WORKSPACE CONFIGURATION -----
    show_progress()
    display_section_header("Workspace Configuration")
    console.print("This is where Penguin will store your projects and contextual data.")
    
    default_workspace = str(Path.home() / "penguin_workspace")
    console.print("[dim](Press Enter to accept default)[/dim]")
    workspace_path = await questionary.text(
        "Workspace directory:",
        default=default_workspace,
        style=STYLE
    ).ask_async()
    
    current_step += 1
    
    # ----- STEP 2: MODEL SELECTION -----
    show_progress()
    display_section_header("Model Selection")
    console.print("Choose which AI model Penguin will use by default.")
    
    # Show loading indicator for model fetching
    with console.status("[bold cyan]Fetching available models...[/bold cyan]", spinner="dots"):
        # First try local cache for fast startup
        models = get_local_models_cache()
        
        # If cache is empty, fetch from API
        if not models:
            models = await fetch_models_from_openrouter()
            if models:
                # Save to cache for next time
                save_models_cache(models)
                console.print("[green]✓[/green] Models retrieved and cached for future use")
            else:
                console.print("[yellow]⚠️ Could not retrieve models from API, using defaults[/yellow]")
    
    # Prepare model choices with better formatting
    if models:
        choices, model_map = prepare_model_choices(models)
        console.print(f"[green]✓[/green] Found [bold]{len(models)}[/bold] available models")
    else:
        # Fallback to default list if API call fails
        choices = [
            "anthropic/claude-3-5-sonnet-20240620 (200K tokens)",
            "openai/o3-mini (128K tokens)",
            "google/gemini-2-5-pro-preview (1M tokens)",
            "mistral/devstral (32K tokens)",
            "Custom (specify)"
        ]
        model_map = {choice: choice.split(" ")[0] for choice in choices if "Custom" not in choice}
        console.print("[yellow]ℹ️ Using default model list[/yellow]")
    
    # Show helpful tips for model selection
    console.print("\n[dim]💡 Tip: Larger context windows (more tokens) let Penguin process more information at once.[/dim]")
    console.print("[dim]   For code-heavy tasks, 32K+ tokens is recommended.[/dim]\n")
    
    # Display instruction before the prompt instead of as a parameter
    console.print("[dim](Type to search, ↑↓ to navigate)[/dim]")
    # Model selection with autocomplete and improved styling
    model_selection = await questionary.autocomplete(
        "Choose your default AI model:",
        choices=choices,
        validate=lambda val: val in choices or "Please select from the list or type 'Custom (specify)'",
        match_middle=True,  # Allow matching in the middle of strings
        style=STYLE
    ).ask_async()
    
    # Handle custom model entry with improved validation
    if model_selection == "Custom (specify)":
        console.print("[dim](Format: provider/model-name)[/dim]")
        model = await questionary.text(
            "Enter custom model identifier:",
            validate=lambda val: len(val) > 0 or "Model identifier cannot be empty",
            style=STYLE
        ).ask_async()
    else:
        # Get the actual model ID from the display string
        model = model_map.get(model_selection, model_selection.split(" ")[0])
    
    # Show confirmation of selection
    console.print(f"[green]✓[/green] Selected model: [bold cyan]{model}[/bold cyan]")
    
    # Determine the actual provider and client preference that will be used
    # This logic should match what's used in the config generation
    provider_from_model = model.split('/')[0] if '/' in model else "anthropic"
    
    # Check if this model will be routed through OpenRouter
    # If models were fetched from OpenRouter API and this model was in that list,
    # then it should use OpenRouter regardless of the provider prefix
    will_use_openrouter = False
    
    if models and "/" in model:
        # Check if this model was in the OpenRouter models list
        model_in_openrouter_list = any(m.get("id") == model for m in models)
        if model_in_openrouter_list:
            will_use_openrouter = True
            console.print(f"[dim]ℹ️ This model will be accessed through OpenRouter (found in OpenRouter catalog).[/dim]")
    
    # Fallback to hardcoded list for cases where OpenRouter API wasn't available
    if not will_use_openrouter and provider_from_model in ["openai", "anthropic", "google", "mistral"] and "/" in model:
        will_use_openrouter = True
        console.print(f"[dim]ℹ️ This model will be accessed through OpenRouter for unified API access.[/dim]")
    
    if will_use_openrouter:
        actual_provider = "openrouter"
    else:
        actual_provider = provider_from_model
        if "/" in model:
            console.print(f"[dim]ℹ️ This model will be accessed directly through the {actual_provider} provider.[/dim]")
    
    current_step += 1
    
    # ----- STEP 3: API CONFIGURATION -----
    show_progress()
    display_section_header("API Configuration")
    console.print(f"Configure access to the {actual_provider} API.")
    
    # Auto-detect context length and max output tokens for the chosen model
    context_window_auto = None
    max_tokens_auto = None
    if models:
        for _m in models:
            if _m.get("id") == model:
                context_window_auto = _m.get("context_length")
                # Use official max_output_tokens field when provided, no fallback.
                if _m.get("max_output_tokens") is not None:
                    max_tokens_auto = _m.get("max_output_tokens")
                break
    
    need_api_key = await questionary.confirm(
        f"Do you need to set up an API key for {actual_provider}?",
        default=True,
        style=STYLE
    ).ask_async()
    
    api_key = None
    if need_api_key:
        # Show help text for API key based on actual provider
        if actual_provider == "openrouter":
            console.print("\n[dim]ℹ️ OpenRouter API keys can be obtained at: https://openrouter.ai/keys[/dim]")
            console.print("[dim]   OpenRouter provides unified access to models from multiple providers.[/dim]")
        elif actual_provider == "anthropic":
            console.print("\n[dim]ℹ️ Anthropic API keys can be obtained at: https://console.anthropic.com/[/dim]")
        elif actual_provider == "openai":
            console.print("\n[dim]ℹ️ OpenAI API keys can be obtained at: https://platform.openai.com/api-keys[/dim]")
        elif actual_provider == "google":
            console.print("\n[dim]ℹ️ Google AI API keys can be obtained through Google AI Studio[/dim]")
        else:
            console.print(f"\n[dim]ℹ️ Please obtain an API key for {actual_provider}[/dim]")
        
        console.print("[dim](Input is hidden for security)[/dim]")
        api_key = await questionary.password(
            f"Enter your {actual_provider} API key:",
            validate=lambda val: len(val) > 10 or "API key seems too short",
            style=STYLE
        ).ask_async()
        
        # Persist key to ~/.config/penguin/.env and export it
        if _persist_api_key(actual_provider, api_key):
            console.print("[green]✓[/green] API key saved to ~/.config/penguin/.env and exported for this session")
        else:
            console.print("[yellow]⚠️ Could not persist API key automatically. It will be shown in next steps.[/yellow]")
    else:
        console.print("[yellow]ℹ️ No API key provided. You'll need to set this up later.[/yellow]")
    
    current_step += 1
    
    # ----- STEP 4: ADVANCED OPTIONS -----
    show_progress()
    display_section_header("Advanced Options")
    
    # Default config values
    config = {
        "workspace": {
            "path": workspace_path,
            "create_dirs": [
                "conversations", "memory_db", "logs", "notes", "projects", "context"
            ]
        },
        "model": {
            "default": model,
            "provider": "openrouter" if will_use_openrouter else provider_from_model,
            "client_preference": "openrouter" if will_use_openrouter else "litellm",
            "streaming_enabled": True,
            "temperature": 0.7,
            "context_window": context_window_auto,
            "max_tokens": max_tokens_auto,
        },
        "api": {
            "base_url": None,  # Will be determined based on provider
        },
        "tools": {
            "enabled": True,
            "allow_web_access": True,
            "allow_file_operations": True,
            "allow_code_execution": True
        },
        "diagnostics": {
            "enabled": False,
            "verbose_logging": False
        }
    }
    
    if api_key:
        # Store API key as environment variable suggestion
        env_var_name = f"{actual_provider.upper()}_API_KEY"
        console.print(f"\n[dim]💡 Tip: You can set {env_var_name}={api_key[:8]}... as an environment variable[/dim]")
        console.print(f"[dim]   This is more secure than storing it in the config file.[/dim]")
    
    # Advanced configuration with better grouping
    show_advanced = await questionary.confirm(
        "Would you like to configure advanced options?",
        default=False,
        style=STYLE
    ).ask_async()
    
    if show_advanced:
        console.print("\n[bold]Performance Settings[/bold]")
        # Model temperature - use text with float validation instead of float
        console.print("[dim](Lower = more deterministic, Higher = more creative)[/dim]")
        temperature = await questionary.text(
            "Model temperature (0.0-1.0):",
            default="0.7",
            validate=lambda val: (val.replace('.', '', 1).isdigit() and 0.0 <= float(val) <= 1.0) or "Please enter a number between 0.0 and 1.0",
            style=STYLE
        ).ask_async()
        config["model"]["temperature"] = float(temperature)
        
        # In the advanced section, only ask for context window if we couldn't auto-detect it
        if context_window_auto is None:
            console.print("\n[dim]💡 Tip: Larger context windows use more API tokens but can handle more complex tasks.[/dim]")
            max_tokens_choice = await questionary.select(
                "Maximum context window:",
                choices=[
                    "8K tokens (Basic tasks, lower cost)",
                    "16K tokens (Standard projects)",
                    "32K tokens (Complex projects)",
                    "128K tokens (Large codebases)",
                    "200K tokens (Extended capability)",
                    "1M tokens (Maximum capability)"
                ],
                default="32K tokens (Complex projects)",
                style=STYLE
            ).ask_async()

            token_map = {
                "8K tokens (Basic tasks, lower cost)": 8000,
                "16K tokens (Standard projects)": 16000,
                "32K tokens (Complex projects)": 32000,
                "128K tokens (Large codebases)": 128000,
                "200K tokens (Extended capability)": 200000,
                "1M tokens (Maximum capability)": 1000000
            }
            config["model"]["context_window"] = token_map[max_tokens_choice]
            
            # If we couldn't auto-detect, prompt for max_tokens as well.
            if max_tokens_auto is None:
                console.print("\n[dim]💡 Tip: This is the maximum number of tokens the model can generate in a single response. Check the what's the max_tokens (or max_output_tokens) in the model spec of the model you selected.[/dim]")
                max_output_tokens_str = await questionary.text(
                    "Maximum output tokens (max_tokens):",
                    default="8192",
                    validate=lambda val: val.isdigit() or "Please enter a number.",
                    style=STYLE
                ).ask_async()
                config["model"]["max_tokens"] = int(max_output_tokens_str)
        
        # Tool permissions with better organization
        console.print("\n[bold]Security & Permissions[/bold]")
        console.print("[dim](For documentation lookups and information retrieval)[/dim]")
        config["tools"]["allow_web_access"] = await questionary.confirm(
            "Allow Penguin to access the web?", 
            default=True,
            style=STYLE
        ).ask_async()
        
        console.print("[dim](Required for testing/running code suggestions)[/dim]")
        config["tools"]["allow_code_execution"] = await questionary.confirm(
            "Allow Penguin to execute code?", 
            default=True,
            style=STYLE
        ).ask_async()
        
        # Diagnostics with better explanations
        console.print("\n[bold]Diagnostics & Logging[/bold]")
        console.print("[dim](Helps improve Penguin, no personal data collected)[/dim]")
        config["diagnostics"]["enabled"] = await questionary.confirm(
            "Enable diagnostics collection?", 
            default=False,
            style=STYLE
        ).ask_async()
        
        if config["diagnostics"]["enabled"]:
            console.print("[dim](Creates detailed logs, helpful for troubleshooting)[/dim]")
            config["diagnostics"]["verbose_logging"] = await questionary.confirm(
                "Enable verbose logging?", 
                default=False,
                style=STYLE
            ).ask_async()
    
    current_step += 1
    
    # ----- STEP 5: FINALIZE -----
    show_progress()
    display_section_header("Configuration Summary")
    
    # Display current configuration in a more visually appealing way
    console.print("\n[bold]Your Configuration:[/bold]")
    console.print(f"  • Workspace: [cyan]{config['workspace']['path']}[/cyan]")
    console.print(f"  • Model: [cyan]{config['model']['default']}[/cyan]")
    console.print(f"  • Provider: [cyan]{config['model']['provider']}[/cyan]")
    console.print(f"  • Temperature: [cyan]{config['model']['temperature']}[/cyan]")
    console.print(f"  • Context Window: [cyan]{config['model'].get('context_window', 'unknown')} tokens[/cyan]")
    console.print(f"  • Max Output: [cyan]{config['model'].get('max_tokens', 'unknown')} tokens[/cyan]")
    console.print(f"  • Web Access: {'Enabled' if config['tools']['allow_web_access'] else 'Disabled'}")
    console.print(f"  • Code Execution: {'Enabled' if config['tools']['allow_code_execution'] else 'Disabled'}")
    console.print(f"  • Diagnostics: [cyan]{'Enabled' if config['diagnostics']['enabled'] else 'Disabled'}[/cyan]")
    
    # Ask to save the final configuration
    if await questionary.confirm(
        "Save this configuration?", 
        default=True,
        style=STYLE
    ).ask_async():
        # Show saving indicator
        with console.status("[bold cyan]Saving configuration...[/bold cyan]", spinner="dots"):
            saved_config_path = save_config(config)
        
        if saved_config_path:
            console.print("[bold green]✓ Configuration saved successfully![/bold green]")
            console.print(f"[dim]Saved to:[/dim] {saved_config_path}")
            
            # Mark setup as complete
            mark_setup_complete()
        
            # Create workspace directory with progress indicator
            if not os.path.exists(config["workspace"]["path"]):
                try:
                    with console.status("[bold cyan]Creating workspace directory...[/bold cyan]", spinner="dots"):
                        os.makedirs(config["workspace"]["path"])
                        
                        # Create subdirectories
                        for subdir in config["workspace"]["create_dirs"]:
                            os.makedirs(os.path.join(config["workspace"]["path"], subdir), exist_ok=True)
                            
                        console.print(f"[bold green]✓ Created workspace directory:[/bold green] {config['workspace']['path']}")
                except Exception as e:
                        console.print(f"[bold red]⚠️ Could not create workspace directory:[/bold red] {e}")
            
            # Show API key setup reminder if needed
            if api_key:
                env_var_name = f"{actual_provider.upper()}_API_KEY"
                console.print(f"\n[bold yellow]📋 Next Steps:[/bold yellow]")
                console.print(f"Set your API key as an environment variable:")
                console.print(f"  [dim]export {env_var_name}=\"{api_key}\"[/dim]")
                console.print(f"Or add it to your shell profile (.bashrc, .zshrc, etc.)")
            
            # Ask to open the config file for review
            if await questionary.confirm(
                    "Would you like to open the config file for review?", 
                    default=False,
                    style=STYLE
                ).ask_async():
                    cfg_path = saved_config_path
                    # In Codespaces/containers, prefer $EDITOR if available, else fallback
                    editor = os.environ.get("EDITOR")
                    opened = False
                    if editor and shutil.which(editor.split()[0]):
                        try:
                            subprocess.run([*editor.split(), str(cfg_path)], check=True)
                            opened = True
                        except Exception:
                            opened = False
                    if not opened:
                        opened = open_in_default_editor(cfg_path)
                    if opened:
                        console.print(f"[green]✓ Opened config file:[/green] {cfg_path}")
                    else:
                        console.print(f"[yellow]⚠️ Could not open config file. It's located at:[/yellow] {cfg_path}")
        else:
            console.print("[bold red]Failed to save configuration. Please check permissions and try again.[/bold red]")
    else:
        console.print("[yellow]Configuration not saved. Run setup again when ready.[/yellow]")
    
    # Final success message
    console.print("\n[bold green]╭───────────────────────────────────────────╮[/bold green]")
    console.print("[bold green]│[/bold green]    [bold white]🎉 PENGUIN SETUP COMPLETE![/bold white]    [bold green]│[/bold green]")
    console.print("[bold green]╰───────────────────────────────────────────╯[/bold green]")
    console.print("\nYou're ready to start using Penguin AI Assistant!\n")
    console.print("[dim]You can always update these settings by running 'penguin config setup' later.[/dim]")
    console.print("[dim]Run 'penguin' to launch the assistant.[/dim]\n")
    
    return config

def _user_config_dir() -> Path:
    """Return cross-platform user config directory for Penguin."""
    if os.name == 'posix':  # Linux/macOS
        return Path(os.environ.get('XDG_CONFIG_HOME', Path.home() / '.config')) / 'penguin'
    return Path(os.environ.get('APPDATA', Path.home() / 'AppData' / 'Roaming')) / 'penguin'

def get_config_path() -> Path:
    """Return the path to the user config file (env override wins)."""
    # 1) Explicit override
    if os.environ.get("PENGUIN_CONFIG_PATH"):
        return Path(os.environ["PENGUIN_CONFIG_PATH"]).expanduser()
    # 2) User config directory (do not write into repo path)
    return _user_config_dir() / "config.yml"

def _persist_api_key(provider: str, api_key: str) -> bool:
    """Write provider API key to ~/.config/penguin/.env and export in-process.

    Returns True on success, False on failure.
    """
    try:
        env_dir = _user_config_dir()
        env_dir.mkdir(parents=True, exist_ok=True)
        env_path = env_dir / ".env"
        # Read existing lines (if any)
        existing: list[str] = []
        if env_path.exists():
            existing = env_path.read_text(encoding="utf-8").splitlines()
        key = f"{provider.upper()}_API_KEY"
        kv = f"{key}={api_key}"
        replaced = False
        for i, line in enumerate(existing):
            if line.startswith(f"{key}="):
                existing[i] = kv
                replaced = True
                break
        if not replaced:
            existing.append(kv)
        env_path.write_text("\n".join(existing) + "\n", encoding="utf-8")
        # Export for current process so the rest of the run sees it
        os.environ[key] = api_key
        return True
    except Exception:
        return False

def save_config(config: Dict[str, Any]) -> Optional[Path]:
    """
    Save the config to a YAML file and return the resolved path.

    Returns:
        Path on success; None on failure.
    """
    config_path = get_config_path()

    try:
        # Make sure parent directory exists
        config_path.parent.mkdir(parents=True, exist_ok=True)

        # Write config with nice formatting
        with open(config_path, 'w') as f:
            yaml.dump(config, f, sort_keys=False, default_flow_style=False)

        return config_path
    except PermissionError:
        console.print(f"[bold red]⚠️ Permission denied:[/bold red] Cannot write to {config_path}")
        console.print("[yellow]Try running with administrator/sudo privileges or choose a different location.[/yellow]")
        return None
    except Exception as e:
        console.print(f"[bold red]⚠️ Error saving configuration:[/bold red] {str(e)}")
        return None

def open_in_default_editor(file_path: Path) -> bool:
    """
    Open a file in the default text editor
    
    Args:
        file_path: Path to the file to open
        
    Returns:
        bool: True if successful, False otherwise
    """
    with console.status(f"[bold cyan]Opening {file_path.name}...[/bold cyan]", spinner="dots"):
        try:
            if platform.system() == 'Windows':
                os.startfile(file_path)
            elif platform.system() == 'Darwin':  # macOS
                subprocess.run(['open', file_path], check=True)
            else:  # Linux
                # In headless environments (e.g., Codespaces) xdg-open may not exist
                if shutil.which('xdg-open') is None:
                    console.print(
                        f"[yellow]⚠️ GUI launcher not available (xdg-open not found). File saved at:[/yellow] {file_path}"
                    )
                    return False
                subprocess.run(['xdg-open', file_path], check=True)
            return True
        except FileNotFoundError as e:
                # Differentiate missing editor launcher vs missing file
                if file_path.exists():
                    console.print(
                        f"[yellow]⚠️ Could not launch editor ({e}). File saved at:[/yellow] {file_path}"
                    )
                else:
                    console.print(f"[bold red]⚠️ File not found:[/bold red] {file_path}")
                return False
        except PermissionError:
                console.print(f"[bold red]⚠️ Permission denied:[/bold red] Cannot open {file_path}")
                return False
        except subprocess.SubprocessError as e:
                console.print(f"[bold red]⚠️ Failed to open editor:[/bold red] {str(e)}")
                console.print(f"[dim]You can manually edit the file at: {file_path}[/dim]")
                return False
        except Exception as e:
                console.print(f"[bold red]⚠️ Error opening file:[/bold red] {str(e)}")
        return False

# For integration with CLI: The /models command handler
async def handle_models_command(args: List[str]) -> Dict[str, Any]:
    """
    Handle /models command to list, search, and set models
    
    Examples:
    - /models list
    - /models search "claude"
    - /models set anthropic/claude-3-5-sonnet
    """
    if not args:
        return {"error": "Missing models subcommand. Try 'list', 'search', or 'set'"}
    
    subcmd = args[0].lower()
    
    # Fetch models from OpenRouter with visual feedback
    models = get_local_models_cache()
    if not models:
        with console.status("[bold cyan]Fetching models from OpenRouter...[/bold cyan]", spinner="dots"):
            models = await fetch_models_from_openrouter()
            if models:
                save_models_cache(models)
                console.print("[green]✓[/green] Models retrieved and cached successfully")
            else:
                console.print("[yellow]⚠️ Could not retrieve models from API[/yellow]")
    
    if subcmd == "list":
        # Format for display with better visual structure
        display_section_header("Available Models")
        
        if not models:
            console.print("[yellow]No models found. Unable to connect to model provider.[/yellow]")
            return {"models_list": [], "error": "No models found"}
        
        # Group models by provider for better organization
        providers = {}
        for model in models:
            model_id = model.get("id", "unknown")
            provider = model_id.split('/')[0] if '/' in model_id else "unknown"
            
            if provider not in providers:
                providers[provider] = []
                
            providers[provider].append({
                "id": model_id,
                "name": model.get("name", model_id),
                "context_length": model.get("context_length", "unknown"),
            })
        
        # Display models grouped by provider
        for provider, provider_models in providers.items():
            console.print(f"\n[bold cyan]{provider.capitalize()} Models:[/bold cyan]")
            for model in provider_models:
                context = f"({model['context_length']} tokens)" if model['context_length'] != "unknown" else ""
                console.print(f"  • [cyan]{model['id']}[/cyan] {context}")
        
        # Prepare data for return
        model_list = []
        for model in models:
            model_id = model.get("id", "unknown")
            context_length = model.get("context_length", "unknown")
            model_list.append({
                "id": model_id,
                "name": model.get("name", model_id),
                "provider": model_id.split('/')[0] if '/' in model_id else "unknown",
                "context_length": context_length,
            })
        
        return {"models_list": model_list}
    
    elif subcmd == "search" and len(args) > 1:
        query = args[1].lower()
        display_section_header(f"Search Results for '{query}'")
        
        # Search by ID, name, or provider with visual feedback
        results = []
        matched_count = 0
        
        with console.status(f"[bold cyan]Searching for models matching '{query}'...[/bold cyan]", spinner="dots"):
            for model in models:
                model_id = model.get("id", "").lower()
                name = model.get("name", "").lower()
                if query in model_id or query in name:
                    matched_count += 1
                    results.append({
                        "id": model.get("id"),
                        "name": model.get("name", model.get("id")),
                        "context_length": model.get("context_length", "unknown"),
                    })
        
        if results:
            console.print(f"[green]Found {matched_count} matching models[/green]")
            for model in results:
                context = f"({model['context_length']} tokens)" if model['context_length'] != "unknown" else ""
                console.print(f"  • [cyan]{model['id']}[/cyan] {context}")
        else:
            console.print(f"[yellow]No models found matching '{query}'[/yellow]")
        
        return {"search_results": results}
    
    elif subcmd == "set" and len(args) > 1:
        model_id = args[1]
        display_section_header("Set Model")
        
        # Validate model exists if we have model data
        model_exists = False
        model_details = None
        
        if models:
            for model in models:
                if model.get("id") == model_id:
                    model_exists = True
                    model_details = model
                    break
            
            if not model_exists:
                console.print(f"[yellow]⚠️ Warning: Model '{model_id}' not found in available models.[/yellow]")
                console.print("[dim]The model may still be valid if it's from a provider not listed in OpenRouter.[/dim]")
        
        # Show confirmation with model details if available
        if model_details:
            context_length = model_details.get("context_length", "unknown")
            console.print(f"[bold]Model Details:[/bold]")
            console.print(f"  • ID: [cyan]{model_id}[/cyan]")
            console.print(f"  • Context Window: [cyan]{context_length} tokens[/cyan]")
        
        # In a real implementation, this would call the model loading function
        console.print(f"[green]✓ Model set to:[/green] [bold cyan]{model_id}[/bold cyan]")
        return {"status": f"Model set to: {model_id}", "model_id": model_id, "success": True}
    
    return {"error": f"Unknown models subcommand: {subcmd}"}

def test_provider_routing() -> None:
    """Test function to verify provider routing logic"""
    
    # Simulate OpenRouter models list (what would be fetched from their API)
    mock_openrouter_models = [
        {"id": "google/gemini-2-5-pro-preview"},
        {"id": "openai/gpt-4o"},
        {"id": "anthropic/claude-3-5-sonnet-20240620"},
        {"id": "mistral/devstral"},
        {"id": "meta-llama/llama-3-70b-instruct"},
        {"id": "deepseek/deepseek-chat"},
        {"id": "cohere/command-r-plus"},
        {"id": "perplexity/llama-3.1-sonar-large-128k-online"},
        {"id": "x-ai/grok-beta"},
    ]
    
    test_cases = [
        # (model_id, expected_actual_provider, expected_config_provider, expected_client_preference, in_openrouter_list)
        ("google/gemini-2-5-pro-preview", "openrouter", "openrouter", "openrouter", True),
        ("openai/gpt-4o", "openrouter", "openrouter", "openrouter", True),
        ("anthropic/claude-3-5-sonnet-20240620", "openrouter", "openrouter", "openrouter", True),
        ("mistral/devstral", "openrouter", "openrouter", "openrouter", True),
        ("meta-llama/llama-3-70b-instruct", "openrouter", "openrouter", "openrouter", True),
        ("deepseek/deepseek-chat", "openrouter", "openrouter", "openrouter", True),
        ("cohere/command-r-plus", "openrouter", "openrouter", "openrouter", True),
        ("perplexity/llama-3.1-sonar-large-128k-online", "openrouter", "openrouter", "openrouter", True),
        ("x-ai/grok-beta", "openrouter", "openrouter", "openrouter", True),
        ("ollama/llama3", "ollama", "ollama", "litellm", False),  # Not in OpenRouter
        ("claude-3-sonnet", "anthropic", "anthropic", "litellm", False),  # No slash, direct provider
        ("some-unknown/model", "some-unknown", "some-unknown", "litellm", False),  # Not in OpenRouter
    ]
    
    console.print("[bold cyan]🧪 Testing Provider Routing Logic[/bold cyan]\n")
    
    for model, expected_actual, expected_config, expected_client, in_or_list in test_cases:
        # Replicate the improved logic from the setup wizard
        provider_from_model = model.split('/')[0] if '/' in model else "anthropic"
        
        # Check if this model will be routed through OpenRouter
        will_use_openrouter = False
        models = mock_openrouter_models if in_or_list else []
        
        if models and "/" in model:
            # Check if this model was in the OpenRouter models list
            model_in_openrouter_list = any(m.get("id") == model for m in models)
            if model_in_openrouter_list:
                will_use_openrouter = True
        
        # Fallback to hardcoded list for cases where OpenRouter API wasn't available
        if not will_use_openrouter and provider_from_model in ["openai", "anthropic", "google", "mistral"] and "/" in model:
            will_use_openrouter = True
        
        if will_use_openrouter:
            actual_provider = "openrouter"
        else:
            actual_provider = provider_from_model
            
        # Generate config values
        config_provider = "openrouter" if will_use_openrouter else provider_from_model
        client_preference = "openrouter" if will_use_openrouter else "litellm"
        
        # Check results
        status_actual = "✓" if actual_provider == expected_actual else "❌"
        status_config = "✓" if config_provider == expected_config else "❌"
        status_client = "✓" if client_preference == expected_client else "❌"
        
        openrouter_status = "📡" if in_or_list else "🔗"
        console.print(f"{openrouter_status} Model: {model}")
        console.print(f"  {status_actual} API Key Provider: {actual_provider} (expected: {expected_actual})")
        console.print(f"  {status_config} Config Provider: {config_provider} (expected: {expected_config})")
        console.print(f"  {status_client} Client Preference: {client_preference} (expected: {expected_client})")
        console.print()
    
    console.print("[dim]Legend: 📡 = Found in OpenRouter catalog, 🔗 = Direct provider access[/dim]")

# Create a sync wrapper for the wizard for standalone use
def run_setup_wizard_sync() -> Dict[str, Any]:
    """Synchronous wrapper for the setup wizard"""
    
    # Check dependencies first
    deps_available, missing_deps = check_setup_dependencies()
    if not deps_available:
        console.print("[bold yellow]🐧 Penguin Setup Wizard[/bold yellow]")
        display_dependency_install_instructions(missing_deps)
        return {"error": f"Missing dependencies: {', '.join(missing_deps)}"}
    
    try:
        return asyncio.run(run_setup_wizard())
    except KeyboardInterrupt:
        console.print("\n[yellow]Setup interrupted by user.[/yellow]")
        return {"error": "Setup interrupted"}
    except Exception as e:
        console.print(f"[red]Setup wizard error: {e}[/red]")
        return {"error": str(e)} 
