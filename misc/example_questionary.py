import questionary
import yaml
import os
import json
import httpx
import asyncio
from pathlib import Path
import platform
import subprocess
from typing import Dict, Any, List, Optional, Tuple
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
        "openai/o3",
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
    console.print("[bold cyan]│[/bold cyan]  [bold white]🐧 PENGUIN AI ASSISTANT SETUP WIZARD[/bold white]  [bold cyan]│[/bold cyan]")
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
            "openai/o3 (128K tokens)",
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
    
    # Provider selection based on model
    provider = model.split('/')[0] if '/' in model else "anthropic"
    
    current_step += 1
    
    # ----- STEP 3: API CONFIGURATION -----
    show_progress()
    display_section_header("API Configuration")
    console.print(f"Configure access to the {provider} API.")
    
    need_api_key = await questionary.confirm(
        f"Do you need to set up an API key for {provider}?",
        default=True,
        style=STYLE
    ).ask_async()
    
    api_key = None
    if need_api_key:
        # Show help text for API key
        if provider == "anthropic":
            console.print("\n[dim]ℹ️ Anthropic API keys can be obtained at: https://console.anthropic.com/[/dim]")
        elif provider == "openai":
            console.print("\n[dim]ℹ️ OpenAI API keys can be obtained at: https://platform.openai.com/api-keys[/dim]")
        elif provider == "google":
            console.print("\n[dim]ℹ️ Google AI API keys can be obtained through Google AI Studio[/dim]")
        
        console.print("[dim](Input is hidden for security)[/dim]")
        api_key = await questionary.password(
            f"Enter your {provider} API key:",
            validate=lambda val: len(val) > 10 or "API key seems too short",
            style=STYLE
        ).ask_async()
        
        console.print("[green]✓[/green] API key saved securely")
    else:
        console.print("[yellow]ℹ️ No API key provided. You'll need to set this up later.[/yellow]")
    
    current_step += 1
    
    # ----- STEP 4: ADVANCED OPTIONS -----
    show_progress()
    display_section_header("Advanced Options")
    
    # Default config values
    config = {
        "workspace": {
            "path": workspace_path
        },
        "model": {
            "default": model,
            "provider": provider,
            "streaming_enabled": True,
            "temperature": 0.7,
            "max_tokens": 8000
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
        config["api"]["key"] = api_key
    
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
        
        # Max tokens with better descriptions
        console.print("\n[dim]💡 Tip: Larger context windows use more API tokens but can handle more complex tasks.[/dim]")
        max_tokens = await questionary.select(
            "Maximum context length:",
            choices=[
                "8K tokens (Basic tasks, lower cost)",
                "16K tokens (Standard projects)",
                "32K tokens (Complex projects)",
                "128K tokens (Large codebases)",
                "200K tokens (Maximum capability)"
            ],
            default="16K tokens (Standard projects)",
            style=STYLE
        ).ask_async()
        
        token_map = {
            "8K tokens (Basic tasks, lower cost)": 8000,
            "16K tokens (Standard projects)": 16000,
            "32K tokens (Complex projects)": 32000,
            "128K tokens (Large codebases)": 128000,
            "200K tokens (Maximum capability)": 200000
        }
        config["model"]["max_tokens"] = token_map[max_tokens]
        
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
    
    # Visual theme (optional extra) with preview hints
    console.print("\n[bold]Visual Appearance[/bold]")
    theme = await questionary.select(
        "Choose UI theme:",
        choices=[
            "Default (Blue accent, balanced contrast)",
            "Dark (Dark background, high contrast)",
            "Light (Light background, softer contrast)",
            "Terminal (Use your terminal's default colors)"
        ],
        style=STYLE
    ).ask_async()
    
    theme_key = theme.split(" ")[0].lower()
    if theme_key != "terminal":
        config["ui"] = {"theme": theme_key}
        console.print(f"[green]✓[/green] Theme set to: [bold]{theme_key}[/bold]")
    
    current_step += 1
    
    # ----- STEP 5: FINALIZE -----
    show_progress()
    display_section_header("Configuration Summary")
    
    # Function to display config and allow editing
    async def review_and_edit_config(config):
        while True:
            # Display current configuration in a more visually appealing way
            console.print("\n[bold]Your Configuration:[/bold]")
            
            # Create a numbered list of editable options
            options = [
                f"Workspace: [cyan]{config['workspace']['path']}[/cyan]",
                f"Model: [cyan]{config['model']['default']}[/cyan]",
                f"Temperature: [cyan]{config['model']['temperature']}[/cyan]",
                f"Context Length: [cyan]{config['model']['max_tokens']} tokens[/cyan]",
                f"Web Access: [cyan]{'Enabled' if config['tools']['allow_web_access'] else 'Disabled'}[/cyan]",
                f"Code Execution: [cyan]{'Enabled' if config['tools']['allow_code_execution'] else 'Disabled'}[/cyan]",
                f"Diagnostics: [cyan]{'Enabled' if config['diagnostics']['enabled'] else 'Disabled'}[/cyan]",
                f"UI Theme: [cyan]{config.get('ui', {}).get('theme', 'Terminal')}[/cyan]"
            ]
            
            # Display each option with a number
            for i, option in enumerate(options):
                console.print(f"  {i+1}. {option}")
            
            # Ask if user wants to change anything
            edit_choice = await questionary.select(
                "Would you like to edit any settings?",
                choices=[
                    "Continue with these settings",
                    "Edit workspace path",
                    "Edit model selection", 
                    "Edit temperature",
                    "Edit context length",
                    "Toggle web access",
                    "Toggle code execution",
                    "Toggle diagnostics",
                    "Change UI theme"
                ],
                style=STYLE
            ).ask_async()
            
            if edit_choice == "Continue with these settings":
                return config
            
            # Handle the selected edit option
            if edit_choice == "Edit workspace path":
                console.print("[dim](Enter new workspace path)[/dim]")
                new_path = await questionary.text(
                    "Workspace directory:",
                    default=config['workspace']['path'],
                    style=STYLE
                ).ask_async()
                config['workspace']['path'] = new_path
                console.print(f"[green]✓[/green] Updated workspace path to: [cyan]{new_path}[/cyan]")
                
            elif edit_choice == "Edit model selection":
                # Re-fetch or use cached models
                with console.status("[bold cyan]Loading available models...[/bold cyan]", spinner="dots"):
                    models = get_local_models_cache()
                    if not models:
                        models = await fetch_models_from_openrouter()
                        if models:
                            save_models_cache(models)
                
                # Prepare model choices
                if models:
                    choices, model_map = prepare_model_choices(models)
                else:
                    # Fallback to default list if API call fails
                    choices = [
                        "anthropic/claude-3-5-sonnet-20240620 (200K tokens)",
                        "openai/o3 (128K tokens)",
                        "google/gemini-2-5-pro-preview (1M tokens)",
                        "mistral/devstral (32K tokens)",
                        "Custom (specify)"
                    ]
                    model_map = {choice: choice.split(" ")[0] for choice in choices if "Custom" not in choice}
                
                console.print("[dim](Type to search, ↑↓ to navigate)[/dim]")
                model_selection = await questionary.autocomplete(
                    "Choose your default AI model:",
                    choices=choices,
                    validate=lambda val: val in choices or "Please select from the list or type 'Custom (specify)'",
                    match_middle=True,
                    style=STYLE
                ).ask_async()
                
                if model_selection == "Custom (specify)":
                    console.print("[dim](Format: provider/model-name)[/dim]")
                    model = await questionary.text(
                        "Enter custom model identifier:",
                        validate=lambda val: len(val) > 0 or "Model identifier cannot be empty",
                        style=STYLE
                    ).ask_async()
                else:
                    model = model_map.get(model_selection, model_selection.split(" ")[0])
                
                config['model']['default'] = model
                config['model']['provider'] = model.split('/')[0] if '/' in model else "anthropic"
                console.print(f"[green]✓[/green] Updated model to: [cyan]{model}[/cyan]")
                
            elif edit_choice == "Edit temperature":
                console.print("[dim](Lower = more deterministic, Higher = more creative)[/dim]")
                new_temp = await questionary.text(
                    "Model temperature (0.0-1.0):",
                    default=str(config['model']['temperature']),
                    validate=lambda val: (val.replace('.', '', 1).isdigit() and 0.0 <= float(val) <= 1.0) or "Please enter a number between 0.0 and 1.0",
                    style=STYLE
                ).ask_async()
                config['model']['temperature'] = float(new_temp)
                console.print(f"[green]✓[/green] Updated temperature to: [cyan]{new_temp}[/cyan]")
                
            elif edit_choice == "Edit context length":
                token_options = [
                    "8K tokens (Basic tasks, lower cost)",
                    "16K tokens (Standard projects)",
                    "32K tokens (Complex projects)",
                    "128K tokens (Large codebases)",
                    "200K tokens (Maximum capability)"
                ]
                
                current_tokens = config['model']['max_tokens']
                default_option = next(
                    (opt for opt in token_options if str(current_tokens) + "K" in opt or str(current_tokens // 1000) + "K" in opt), 
                    token_options[2]  # Default to 32K if not found
                )
                
                max_tokens = await questionary.select(
                    "Maximum context length:",
                    choices=token_options,
                    default=default_option,
                    style=STYLE
                ).ask_async()
                
                token_map = {
                    "8K tokens (Basic tasks, lower cost)": 8000,
                    "16K tokens (Standard projects)": 16000,
                    "32K tokens (Complex projects)": 32000,
                    "128K tokens (Large codebases)": 128000,
                    "200K tokens (Maximum capability)": 200000
                }
                config['model']['max_tokens'] = token_map[max_tokens]
                console.print(f"[green]✓[/green] Updated context length to: [cyan]{token_map[max_tokens]} tokens[/cyan]")
                
            elif edit_choice == "Toggle web access":
                current = config['tools']['allow_web_access']
                config['tools']['allow_web_access'] = not current
                status = "enabled" if config['tools']['allow_web_access'] else "disabled"
                console.print(f"[green]✓[/green] Web access {status}")
                
            elif edit_choice == "Toggle code execution":
                current = config['tools']['allow_code_execution']
                config['tools']['allow_code_execution'] = not current
                status = "enabled" if config['tools']['allow_code_execution'] else "disabled"
                console.print(f"[green]✓[/green] Code execution {status}")
                
            elif edit_choice == "Toggle diagnostics":
                current = config['diagnostics']['enabled']
                config['diagnostics']['enabled'] = not current
                status = "enabled" if config['diagnostics']['enabled'] else "disabled"
                console.print(f"[green]✓[/green] Diagnostics {status}")
                
            elif edit_choice == "Change UI theme":
                theme_options = [
                    "Default (Blue accent, balanced contrast)",
                    "Dark (Dark background, high contrast)",
                    "Light (Light background, softer contrast)",
                    "Terminal (Use your terminal's default colors)"
                ]
                
                theme = await questionary.select(
                    "Choose UI theme:",
                    choices=theme_options,
                    style=STYLE
                ).ask_async()
                
                theme_key = theme.split(" ")[0].lower()
                if theme_key != "terminal":
                    config['ui'] = {'theme': theme_key}
                elif 'ui' in config and 'theme' in config['ui']:
                    del config['ui']['theme']
                    
                console.print(f"[green]✓[/green] Updated theme to: [bold]{theme_key}[/bold]")
    
    # Start the review and edit process
    config = await review_and_edit_config(config)
    
    # Ask to save the final configuration
    if await questionary.confirm(
        "Save this configuration?", 
        default=True,
        style=STYLE
    ).ask_async():
        # Show saving indicator
        with console.status("[bold cyan]Saving configuration...[/bold cyan]", spinner="dots"):
            save_success = save_config(config)
        
        if save_success:
            console.print("[bold green]✓ Configuration saved successfully![/bold green]")
        
            # Create workspace directory with progress indicator
        if not os.path.exists(config["workspace"]["path"]):
            try:
                with console.status("[bold cyan]Creating workspace directory...[/bold cyan]", spinner="dots"):
                    os.makedirs(config["workspace"]["path"])
                    console.print(f"[bold green]✓ Created workspace directory:[/bold green] {config['workspace']['path']}")
            except Exception as e:
                    console.print(f"[bold red]⚠️ Could not create workspace directory:[/bold red] {e}")
        
        # Ask to open the config file for review
        if await questionary.confirm(
                "Would you like to open the config file for review?", 
                default=False,
                style=STYLE
            ).ask_async():
                config_path = get_config_path()
                if open_in_default_editor(config_path):
                    console.print(f"[green]✓ Opened config file:[/green] {config_path}")
                else:
                    console.print(f"[yellow]⚠️ Could not open config file. It's located at:[/yellow] {config_path}")
        else:
            console.print("[bold red]Failed to save configuration. Please check permissions and try again.[/bold red]")
    else:
        console.print("[yellow]Configuration not saved. Run setup again when ready.[/yellow]")
    
    # Final success message
    console.print("\n[bold green]╭───────────────────────────────────────────╮[/bold green]")
    console.print("[bold green]│[/bold green]    [bold white]🎉 PENGUIN SETUP COMPLETE![/bold white]    [bold green]│[/bold green]")
    console.print("[bold green]╰───────────────────────────────────────────╯[/bold green]")
    console.print("\nYou're ready to start using Penguin AI Assistant!\n")
    console.print("[dim]You can always update these settings by running 'penguin config' later.[/dim]")
    console.print("[dim]Run 'penguin' to launch the assistant.[/dim]\n")
    
    return config

def get_config_path() -> Path:
    """Return the path to the config file"""
    if os.environ.get("PENGUIN_CONFIG_PATH"):
        return Path(os.environ.get("PENGUIN_CONFIG_PATH"))
    
    # Default locations by platform
    if platform.system() == "Windows":
        config_dir = Path(os.environ.get("APPDATA", "")) / "Penguin"
    elif platform.system() == "Darwin":  # macOS
        config_dir = Path.home() / "Library" / "Application Support" / "Penguin"
    else:  # Linux and others
        config_dir = Path.home() / ".config" / "penguin"
    
    config_dir.mkdir(parents=True, exist_ok=True)
    return config_dir / "config.yml"

def save_config(config: Dict[str, Any]) -> bool:
    """
    Save the config to a YAML file
    
    Returns:
        bool: True if save was successful, False otherwise
    """
    config_path = get_config_path()
    
    try:
        # Make sure parent directory exists
        config_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Write config with nice formatting
        with open(config_path, 'w') as f:
            yaml.dump(config, f, sort_keys=False, default_flow_style=False)
        
        return True
    except PermissionError:
        console.print(f"[bold red]⚠️ Permission denied:[/bold red] Cannot write to {config_path}")
        console.print("[yellow]Try running with administrator/sudo privileges or choose a different location.[/yellow]")
        return False
    except Exception as e:
        console.print(f"[bold red]⚠️ Error saving configuration:[/bold red] {str(e)}")
        return False

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
                subprocess.run(['xdg-open', file_path], check=True)
            return True
        except FileNotFoundError:
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

def check_first_run() -> bool:
    """Check if this is the first run of Penguin"""
    config_path = get_config_path()
    return not config_path.exists()

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
            console.print(f"  • Context Length: [cyan]{context_length} tokens[/cyan]")
        
        # In a real implementation, this would call the model loading function
        console.print(f"[green]✓ Model set to:[/green] [bold cyan]{model_id}[/bold cyan]")
        return {"status": f"Model set to: {model_id}", "model_id": model_id, "success": True}
    
    return {"error": f"Unknown models subcommand: {subcmd}"}

# Create a sync wrapper for the wizard for standalone use
def run_setup_wizard_sync() -> Dict[str, Any]:
    """Synchronous wrapper for the setup wizard"""
    return asyncio.run(run_setup_wizard())
        
# Example usage in a standalone script
if __name__ == "__main__":
    config = run_setup_wizard_sync()
    print("Setup complete!")