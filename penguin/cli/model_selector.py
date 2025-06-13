"""
Model selector for the /models command.
Provides an autocomplete interface for selecting models without conflicts with the main chat session.
Always fetches fresh data to ensure new models are available.
"""

import asyncio
import json
import httpx
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
from prompt_toolkit import PromptSession
from prompt_toolkit.completion import Completer, Completion
from prompt_toolkit.styles import Style
from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.keys import Keys
from rich.console import Console

console = Console()

# Reuse the style from wizard.py
STYLE = Style([
    ('completion-menu.completion', 'bg:#008888 #ffffff'),
    ('completion-menu.completion.current', 'bg:#00aaaa #000000'),
    ('bottom-toolbar', '#ffffff bg:#333333'),
])

class ModelCompleter(Completer):
    """Custom completer for model selection with fuzzy matching"""
    
    def __init__(self, models: List[Dict[str, Any]]):
        self.models = models
        self.model_choices = self._prepare_choices()
        
    def _prepare_choices(self) -> List[Tuple[str, str, Dict[str, Any]]]:
        """Prepare choices in format: (display_text, model_id, model_data)"""
        choices = []
        
        # Group by provider for better organization
        providers = {}
        for model in self.models:
            model_id = model.get("id", "")
            provider = model_id.split('/')[0] if '/' in model_id else "unknown"
            
            if provider not in providers:
                providers[provider] = []
            providers[provider].append(model)
        
        # Add popular models first
        popular = ["anthropic", "openai", "google", "mistral", "deepseek", "x-ai"]
        for provider_name in popular:
            if provider_name in providers:
                for model in providers[provider_name]:
                    model_id = model.get("id", "")
                    context_length = model.get("context_length", "unknown")
                    display = f"{model_id} ({context_length} tokens) [{provider_name}]"
                    choices.append((display, model_id, model))
        
        # Add remaining models
        for provider_name, models_list in providers.items():
            if provider_name not in popular:
                for model in models_list:
                    model_id = model.get("id", "")
                    context_length = model.get("context_length", "unknown")
                    display = f"{model_id} ({context_length} tokens) [{provider_name}]"
                    choices.append((display, model_id, model))
        
        return choices
        
    def get_completions(self, document, complete_event):
        """Generate completions based on user input"""
        text = document.text.lower()
        
        # If no input, show first 10 popular models
        if not text.strip():
            for i, (display, model_id, model_data) in enumerate(self.model_choices[:10]):
                yield Completion(
                    model_id,
                    start_position=0,
                    display=display,
                    style='class:completion'
                )
            return
        
        # Fuzzy matching - check if search terms appear in model ID or display text
        search_terms = text.split()
        matches = []
        
        for display, model_id, model_data in self.model_choices:
            score = 0
            display_lower = display.lower()
            model_id_lower = model_id.lower()
            
            # Exact match gets highest score
            if text in model_id_lower:
                score += 100
            elif text in display_lower:
                score += 50
            
            # Partial matches
            for term in search_terms:
                if term in model_id_lower:
                    score += 20
                elif term in display_lower:
                    score += 10
            
            if score > 0:
                matches.append((score, display, model_id, model_data))
        
        # Sort by score and yield completions
        matches.sort(key=lambda x: x[0], reverse=True)
        for score, display, model_id, model_data in matches[:20]:  # Limit to 20 results
            yield Completion(
                model_id,
                start_position=-len(document.text),
                display=display,
                style='class:completion'
            )

async def fetch_models_from_openrouter() -> List[Dict[str, Any]]:
    """Fetch models from OpenRouter API"""
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get("https://openrouter.ai/api/v1/models", timeout=10.0)
            response.raise_for_status()
            data = response.json()
            return data.get("data", [])
    except Exception as e:
        console.print(f"[bold red]⚠️ Failed to fetch models from OpenRouter:[/bold red] {e}")
        return []

async def interactive_model_selector(current_model: Optional[str] = None) -> Optional[str]:
    """
    Interactive model selector using prompt_toolkit autocomplete.
    Returns the selected model ID or None if cancelled.
    """
    console.print("\n[bold cyan]🤖 Model Selection[/bold cyan]")
    
    # Always fetch fresh data to get the latest models
    with console.status("[cyan]Fetching latest models...[/cyan]", spinner="dots"):
        models = await fetch_models_from_openrouter()
        if not models:
            console.print("[yellow]⚠️ Using fallback model list[/yellow]")
            # Fallback models (including Claude 4)
            models = [
                {"id": "anthropic/claude-4-opus", "context_length": 200000, "name": "Claude 4 Opus"},
                {"id": "anthropic/claude-4-sonnet", "context_length": 200000, "name": "Claude 4 Sonnet"},
                {"id": "anthropic/claude-3-5-sonnet-20240620", "context_length": 200000, "name": "Claude 3.5 Sonnet"},
                {"id": "openai/o3-mini", "context_length": 128000, "name": "O3 Mini"},
                {"id": "google/gemini-2-5-pro-preview", "context_length": 1000000, "name": "Gemini 2.5 Pro"},
                {"id": "mistral/devstral", "context_length": 32000, "name": "Devstral"},
                {"id": "deepseek/deepseek-chat", "context_length": 163840, "name": "DeepSeek V3"},
            ]
    
    if not models:
        console.print("[red]❌ No models available[/red]")
        return None
    
    console.print(f"[green]✓[/green] Found [bold]{len(models)}[/bold] available models")
    
    # Show current model
    if current_model:
        console.print(f"[dim]Current model: [bold]{current_model}[/bold][/dim]")
    
    # Create completer and session
    completer = ModelCompleter(models)
    
    # Key bindings for better UX
    kb = KeyBindings()
    
    @kb.add('c-c')  # Ctrl+C to cancel
    def _(event):
        event.app.exit(exception=KeyboardInterrupt)
    
    @kb.add('escape')  # Escape to cancel
    def _(event):
        event.app.exit(exception=KeyboardInterrupt)
    
    # Create a new prompt session specifically for model selection
    session = PromptSession(
        completer=completer,
        complete_while_typing=True,
        style=STYLE,
        key_bindings=kb,
        bottom_toolbar=HTML('<b>Tab/Arrow keys:</b> Navigate | <b>Enter:</b> Select | <b>Ctrl+C/Esc:</b> Cancel'),
    )
    
    console.print("\n[dim]💡 Tips:[/dim]")
    console.print("[dim]  • Start typing to search (e.g., 'claude', 'gpt', 'anthropic')[/dim]")
    console.print("[dim]  • Use Tab or arrow keys to navigate suggestions[/dim]")
    console.print("[dim]  • Press Enter to select, Ctrl+C or Esc to cancel[/dim]")
    
    try:
        prompt_text = "Search and select model: "
        selected_model = await session.prompt_async(prompt_text)
        
        if selected_model and selected_model.strip():
            # Validate the selection
            selected_model = selected_model.strip()
            model_exists = any(m.get("id") == selected_model for m in models)
            
            if model_exists:
                # Show selected model details
                selected_model_data = next((m for m in models if m.get("id") == selected_model), None)
                if selected_model_data:
                    console.print(f"\n[green]✓ Selected:[/green] [bold cyan]{selected_model}[/bold cyan]")
                    context_length = selected_model_data.get("context_length", "unknown")
                    name = selected_model_data.get("name", selected_model)
                    console.print(f"[dim]  Context: {context_length} tokens | Name: {name}[/dim]")
                
                return selected_model
            else:
                console.print(f"[yellow]⚠️ Model '{selected_model}' not found in available models[/yellow]")
                console.print("[dim]You can still use '/model set' to manually set this model if it's valid.[/dim]")
                return None
        else:
            console.print("[yellow]No model selected[/yellow]")
            return None
            
    except KeyboardInterrupt:
        console.print("\n[yellow]Model selection cancelled[/yellow]")
        return None
    except Exception as e:
        console.print(f"\n[red]Error during model selection: {e}[/red]")
        return None 