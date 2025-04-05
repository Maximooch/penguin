#!/usr/bin/env python3
"""
Penguin Textual CLI
A rich, interactive terminal interface for Penguin AI using the Textual framework.
"""

import asyncio
import sys
import os
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional, cast

from textual import on, work # type: ignore
from textual.app import App, ComposeResult # type: ignore
from textual.containers import Container, Horizontal, Vertical, VerticalScroll # type: ignore
from textual.widgets import Button, Footer, Header, Input, Static, TextArea, LoadingIndicator, Log, Markdown # type: ignore
from textual.widgets.text_area import Selection # type: ignore
from textual.reactive import reactive # type: ignore
from textual.css.query import NoMatches # type: ignore
from rich.markdown import Markdown as RichMarkdown # type: ignore
from rich.syntax import Syntax # type: ignore
from rich.panel import Panel # type: ignore
from rich.text import Text # type: ignore

from penguin.core import PenguinCore
from penguin.chat.interface import PenguinInterface
# from penguin.llm.model_config import ModelConfig

# Configure directory for Textual logs (create if needed)
log_dir = Path.home() / ".penguin" / "logs"
log_dir.mkdir(parents=True, exist_ok=True)


class MessageDisplay(Static):
    """Widget to display a single message with role-based styling"""
    def __init__(self, role: str, content: str, **kwargs):
        super().__init__(**kwargs)
        self.role = role.lower()
        self.content = content
        
    def compose(self) -> ComposeResult:
        yield Static(f"[b]{self.role.upper()}[/b]", classes=f"msg-role {self.role}-role")
        
        # Handle different types of content
        if self.role == "system" and "Action executed:" in self.content:
            # Format tool execution results differently
            self.add_class("tool-message")
            
            # Extract action type and result
            action_type = self.content.split("Action executed:", 1)[1].split("\n", 1)[0].strip()
            lines = self.content.split("\n")
            result_line = next((line for line in lines if line.startswith("Result:")), "")
            result = result_line.replace("Result:", "").strip() if result_line else ""
            status_line = next((line for line in lines if line.startswith("Status:")), "")
            status = status_line.replace("Status:", "").strip() if status_line else ""
            
            # Create styled widget
            yield Static(f"[b]Tool:[/b] {action_type}")
            
            # Format code differently when present
            if "```" in result:
                try:
                    code_parts = result.split("```", 2)
                    if len(code_parts) >= 3:
                        pre_code = code_parts[0].strip()
                        if pre_code:
                            yield Static(pre_code)
                        
                        # Get language if specified (python, json, etc.)
                        code_block = code_parts[1]
                        lang = code_block.split("\n")[0].strip()
                        code = "\n".join(code_block.split("\n")[1:]) if "\n" in code_block else code_block
                        
                        syntax = Syntax(code, lang if lang else "text", theme="monokai", line_numbers=True, word_wrap=True)
                        yield Static(syntax)
                        
                        post_code = code_parts[2].strip()
                        if post_code:
                            yield Static(post_code)
                    else:
                        yield Static(result)
                except Exception:
                    yield Static(result)
            else:
                yield Static(result)
                
            yield Static(f"[b]Status:[/b] {status}", classes=f"status-{status}")
            
        else:
            # Process content differently based on format
            if "```" in self.content:
                try:
                    # Handle markdown with code blocks
                    md = RichMarkdown(self.content)
                    yield Static(md)
                except Exception:
                    yield Static(self.content)
            else:
                # Regular text content
                yield Static(self.content, classes="message-content")


class ChatScreen(Container):
    """The main chat interface screen"""
    
    def __init__(self, interface: PenguinInterface, **kwargs):
        super().__init__(**kwargs)
        self.interface = interface
        self.is_processing = False
        
    def compose(self) -> ComposeResult:
        """Create child widgets"""
        with Container(id="chat-container"):
            with VerticalScroll(id="message-container"):
                # Messages will be added here dynamically
                pass
                
            with Container(id="input-container"):
                with Horizontal():
                    yield Input(placeholder="Type a message or /command...", id="user-input")
                    yield Button("Send", id="send-button", variant="primary")
                
                with Horizontal(id="status-bar"):
                    yield Static("", id="model-info")
                    yield Static("Ready", id="status-text")
                    yield Static("Tokens: 0", id="token-count")
                    
            # Loading indicator for async operations
            yield LoadingIndicator(id="loading-indicator")
            
        # Help screen (hidden by default)
        with Container(id="help-container", classes="hidden"):
            yield Static("Penguin CLI Help", id="help-title")
            with VerticalScroll(id="help-content"):
                yield Static("", id="help-text")
            yield Button("Close", id="close-help-button")
            
        # Model selector screen (hidden by default)
        with Container(id="model-selector", classes="hidden"):
            yield Static("Select Model", id="model-selector-title")
            with VerticalScroll(id="model-list"):
                # Model items will be added here
                pass
            yield Button("Close", id="close-model-selector-button")
            
    def on_mount(self) -> None:
        """Set up the interface when the app is mounted"""
        # Set up model info display
        if hasattr(self.interface.core, 'model_config'):
            model_name = getattr(self.interface.core.model_config, 'model', 'Unknown')
            provider = getattr(self.interface.core.model_config, 'provider', 'Unknown')
            model_info = self.query_one("#model-info", Static)
            model_info.update(f"Model: {model_name.split('/')[-1]} ({provider})")
        
        # Add welcome message
        self.add_message("system", "Welcome to Penguin AI! Type a message to begin or /help for available commands.")
    
    @on(Input.Submitted, "#user-input")
    @on(Button.Pressed, "#send-button")
    async def handle_input(self) -> None:
        """Process user input when submitted"""
        if self.is_processing:
            return
            
        # Get user input
        input_widget = self.query_one("#user-input", Input)
        message = input_widget.value.strip()
        
        if not message:
            return
            
        # Clear input
        input_widget.value = ""
        
        # Handle commands differently
        if message.startswith("/"):
            await self.handle_command(message)
            return
            
        # Display user message
        self.add_message("user", message)
        
        # Process the message
        self.is_processing = True
        self.update_status("Processing...", "busy")
        
        try:
            # Show loading indicator while processing
            loading = self.query_one("#loading-indicator", LoadingIndicator)
            loading.play()
            
            # Process in background to avoid blocking UI
            result = await self.process_message(message)
            
            # Display assistant response
            assistant_response = result.get("assistant_response", "")
            if assistant_response:
                self.add_message("assistant", assistant_response)
                
            # Check for OpenRouter empty content note
            if "openrouter_note" in result:
                self.add_message("system", result["openrouter_note"], classes="warning-message")
                
            # Display any action results
            action_results = result.get("action_results", [])
            for action_result in action_results:
                action_type = action_result.get("action", "unknown")
                result_text = action_result.get("result", "")
                status = action_result.get("status", "unknown")
                
                if result_text:
                    content = f"Action executed: {action_type}\nResult: {result_text}\nStatus: {status}"
                    self.add_message("system", content)
            
            # Update token usage display
            if hasattr(self.interface, 'get_token_usage'):
                usage = self.interface.get_token_usage()
                token_count = self.query_one("#token-count", Static)
                token_count.update(f"Tokens: {usage.get('total_tokens', 0)}")
                
        except Exception as e:
            self.add_message("system", f"Error: {str(e)}", classes="error-message")
        
        finally:
            # Hide loading indicator and reset status
            try:
                loading = self.query_one("#loading-indicator", LoadingIndicator)
                loading.stop()
            except NoMatches:
                pass
                
            self.is_processing = False
            self.update_status("Ready", "idle")
            
            # Scroll to the bottom
            message_container = self.query_one("#message-container", VerticalScroll)
            message_container.scroll_end(animate=False)
    
    @work
    async def process_message(self, message: str) -> Dict[str, Any]:
        """Process user message in a background worker"""
        return await self.interface.process_input({"text": message})
    
    async def handle_command(self, command: str) -> None:
        """Handle slash commands"""
        cmd_parts = command[1:].split(" ")
        cmd = cmd_parts[0].lower()
        args = cmd_parts[1:] if len(cmd_parts) > 1 else []
        
        # Handle some UI-specific commands directly
        if cmd == "clear":
            # Clear the message container
            message_container = self.query_one("#message-container", VerticalScroll)
            message_container.remove_children()
            return
        elif cmd == "help":
            # Show the help screen
            self.show_help(args[0] if args else None)
            return
        elif cmd == "model" and args and args[0] == "select":
            # Show the model selector
            await self.show_model_selector()
            return
            
        # Process other commands through the interface
        self.update_status(f"Running command: {cmd}", "busy")
        
        try:
            # Show loading indicator
            loading = self.query_one("#loading-indicator", LoadingIndicator)
            loading.play()
            
            # Process command through interface
            result = await self.interface.handle_command(command[1:])
            
            # Display command result
            if "error" in result:
                self.add_message("system", f"Error: {result['error']}", classes="error-message")
            elif "status" in result:
                self.add_message("system", f"Command result: {result['status']}")
            elif "help" in result:
                if "guide_content" in result:
                    # Display markdown content from guide
                    self.show_help(None, guide_content=result["guide_content"])
                else:
                    # Display command list
                    commands = result.get("commands", [])
                    help_text = "Available Commands:\n" + "\n".join(f"- {cmd}" for cmd in commands)
                    self.add_message("system", help_text)
            elif "conversations" in result:
                # Display conversation list
                conversations = result["conversations"]
                if conversations:
                    conv_text = "Available Conversations:\n" + "\n".join(
                        f"- {conv.session_id}: {conv.title} ({conv.message_count} msgs)"
                        for conv in conversations
                    )
                else:
                    conv_text = "No saved conversations found."
                self.add_message("system", conv_text)
            elif "token_usage" in result:
                # Display token usage
                usage = result["token_usage"]
                usage_text = f"Token Usage:\n- Prompt: {usage.get('prompt_tokens', 0)}\n- Completion: {usage.get('completion_tokens', 0)}\n- Total: {usage.get('total_tokens', 0)}"
                self.add_message("system", usage_text)
            elif "context_files" in result:
                # Display context files
                files = result["context_files"]
                if files:
                    files_text = "Available Context Files:\n" + "\n".join(
                        f"- {file['path']}"
                        for file in files
                    )
                else:
                    files_text = "No context files found."
                self.add_message("system", files_text)
            else:
                # Generic result display
                self.add_message("system", f"Command completed: {cmd}")
                
        except Exception as e:
            self.add_message("system", f"Error executing command: {str(e)}", classes="error-message")
            
        finally:
            # Hide loading indicator and reset status
            try:
                loading = self.query_one("#loading-indicator", LoadingIndicator)
                loading.stop()
            except NoMatches:
                pass
                
            self.update_status("Ready", "idle")
    
    def add_message(self, role: str, content: str, classes: str = "") -> None:
        """Add a message to the chat display"""
        message_container = self.query_one("#message-container", VerticalScroll)
        message = MessageDisplay(role, content)
        
        if classes:
            for cls in classes.split():
                message.add_class(cls)
                
        message_container.mount(message)
        message_container.scroll_end(animate=False)
    
    def update_status(self, text: str, state: str = "idle") -> None:
        """Update the status text display"""
        status_text = self.query_one("#status-text", Static)
        status_text.update(text)
        
        # Update status bar classes
        status_bar = self.query_one("#status-bar", Horizontal)
        status_bar.remove_class("status-busy")
        status_bar.remove_class("status-idle")
        status_bar.remove_class("status-error")
        status_bar.add_class(f"status-{state}")
    
    def show_help(self, topic: Optional[str] = None, guide_content: Optional[str] = None) -> None:
        """Show the help screen with content for the specified topic"""
        help_container = self.query_one("#help-container", Container)
        help_text = self.query_one("#help-text", Static)
        
        # Remove hidden class to display
        help_container.remove_class("hidden")
        
        # Determine help content based on topic
        content = ""
        if guide_content:
            # Use provided guide content
            help_text.update(RichMarkdown(guide_content))
        elif topic == "openrouter":
            # OpenRouter-specific help (fallback if guide not loaded)
            help_text.update(RichMarkdown("""
# OpenRouter Help

## Common Commands
- `/model list` - Show available models
- `/model load MODEL_NAME` - Switch to a different model
- `/help openrouter` - Show this help

## Troubleshooting
- If you get empty responses, try using GPT-3.5 Turbo
- Rate limits? Switch to a different provider
            """))
        else:
            # General help
            commands = [
                ("/help [topic]", "Show this help or topic-specific help"),
                ("/clear", "Clear the chat history"),
                ("/model list", "List available models"),
                ("/model load MODEL_NAME", "Switch to a different model"),
                ("/model select", "Open interactive model selector"),
                ("/chat list", "List saved conversations"),
                ("/chat load ID", "Load a saved conversation"),
                ("/stream on|off", "Enable/disable streaming"),
                ("/tokens", "Show token usage"),
                ("/context list", "List available context files"),
                ("/context load PATH", "Load a context file"),
                ("/exit", "Exit the application")
            ]
            
            # Format help text
            help_md = "# Penguin AI Commands\n\n"
            for cmd, desc in commands:
                help_md += f"- **{cmd}** - {desc}\n"
                
            help_text.update(RichMarkdown(help_md))
    
    @on(Button.Pressed, "#close-help-button")
    def close_help(self) -> None:
        """Close the help screen"""
        help_container = self.query_one("#help-container", Container)
        help_container.add_class("hidden")
    
    async def show_model_selector(self) -> None:
        """Show the model selector screen"""
        model_selector = self.query_one("#model-selector", Container)
        model_list = self.query_one("#model-list", VerticalScroll)
        
        # Clear existing models
        model_list.remove_children()
        
        # Remove hidden class to display
        model_selector.remove_class("hidden")
        
        # Show loading state
        self.update_status("Loading models...", "busy")
        
        try:
            # Get available models from interface
            models = self.interface.list_available_models()
            
            if not models:
                model_list.mount(Static("No models found"))
            else:
                # Group models by provider
                providers = {}
                for model in models:
                    provider = model.get("provider", "unknown")
                    if provider not in providers:
                        providers[provider] = []
                    providers[provider].append(model)
                
                # Add provider sections
                for provider, provider_models in providers.items():
                    model_list.mount(Static(f"[b]{provider.upper()}[/b]", classes="provider-header"))
                    
                    # Add models for this provider
                    for model in provider_models:
                        name = model.get("name", "Unknown")
                        pref = model.get("client_preference", "native")
                        vision = "✓" if model.get("vision_enabled", False) else "✗"
                        current = "➤ " if model.get("current", False) else ""
                        
                        # Create model button
                        btn = Button(
                            f"{current}{name} [{pref}] Vision: {vision}", 
                            id=f"model-{name.replace('/', '-')}", 
                            classes="model-button"
                        )
                        btn.data = name  # Store model name for loading
                        model_list.mount(btn)
                        
                        # Add event handler for button
                        @on(Button.Pressed, f"#{btn.id}")
                        async def load_model_handler(event) -> None:
                            model_name = event.button.data
                            await self.load_model(model_name)
                
        except Exception as e:
            model_list.mount(Static(f"Error loading models: {str(e)}", classes="error-message"))
            
        finally:
            self.update_status("Ready", "idle")
    
    @on(Button.Pressed, "#close-model-selector-button")
    def close_model_selector(self) -> None:
        """Close the model selector screen"""
        model_selector = self.query_one("#model-selector", Container)
        model_selector.add_class("hidden")
    
    @work
    async def load_model(self, model_name: str) -> None:
        """Load a model in the background"""
        self.update_status(f"Loading model: {model_name}", "busy")
        
        try:
            # Show loading indicator
            loading = self.query_one("#loading-indicator", LoadingIndicator)
            loading.play()
            
            # Load model through interface
            success = self.interface.load_model(model_name)
            
            if success:
                # Update model info display
                model_info = self.query_one("#model-info", Static)
                
                if hasattr(self.interface.core, 'model_config'):
                    model = getattr(self.interface.core.model_config, 'model', model_name)
                    provider = getattr(self.interface.core.model_config, 'provider', 'Unknown')
                    model_display = model.split('/')[-1] if '/' in model else model  # Show only the model name part
                    model_info.update(f"Model: {model_display} ({provider})")
                
                self.add_message("system", f"Loaded model: {model_name}")
                
                # Close model selector
                model_selector = self.query_one("#model-selector", Container)
                model_selector.add_class("hidden")
            else:
                self.add_message("system", f"Failed to load model: {model_name}", classes="error-message")
                
        except Exception as e:
            self.add_message("system", f"Error loading model: {str(e)}", classes="error-message")
            
        finally:
            # Hide loading indicator and reset status
            try:
                loading = self.query_one("#loading-indicator", LoadingIndicator)
                loading.stop()
            except NoMatches:
                pass
                
            self.update_status("Ready", "idle")


class PenguinApp(App):
    """Main Textual app for Penguin AI"""
    CSS_PATH = "textual_cli.css"
    TITLE = "Penguin AI"
    SUB_TITLE = "Advanced AI Assistant"
    
    def __init__(self, core: PenguinCore):
        super().__init__()
        self.interface = PenguinInterface(core)
    
    def compose(self) -> ComposeResult:
        """Create child widgets"""
        yield Header()
        yield ChatScreen(self.interface)
        yield Footer()
    
    def on_mount(self) -> None:
        """Event handler called when app is mounted"""
        # Focus the input when app starts
        self.query_one("#user-input").focus()


def create_css_file() -> None:
    """Create the CSS file for styling the Textual interface"""
    css_path = Path(__file__).parent / "textual_cli.css"
    
    css_content = """
/* Base styles */
Screen {
    background: #1e1e2e;
    color: #cdd6f4;
}

Header {
    background: #181825;
    color: #f5e0dc;
}

Footer {
    background: #181825;
    color: #f5e0dc;
}

/* Chat container layout */
#chat-container {
    layout: vertical;
    width: 100%;
    height: 100%;
}

#message-container {
    width: 100%;
    height: 1fr;
    border-bottom: solid #313244;
    padding: 1;
}

#input-container {
    width: 100%;
    height: auto;
    padding: 1;
}

/* Message styling */
MessageDisplay {
    margin: 0 0 1 0;
    padding: 1;
    background: #313244;
    border: solid #313244;
}

MessageDisplay.user-message {
    background: #45475a;
}

MessageDisplay.assistant-message {
    background: #313244;
}

MessageDisplay.system-message {
    background: #1e1e2e;
    border: solid #45475a;
}

MessageDisplay.tool-message {
    background: #2a2b3c;
    border: solid #45475a;
}

MessageDisplay.error-message {
    background: #432635;
    border: solid #f38ba8;
}

MessageDisplay.warning-message {
    background: #3a3530;
    border: solid #fab387;
}

.message-content {
    margin: 0 0 0 1;
    padding-left: 1;
}

.msg-role {
    color: #89b4fa;
    padding: 0 1;
    margin-bottom: 1;
}

.user-role {
    color: #a6e3a1;
}

.assistant-role {
    color: #89b4fa;
}

.system-role {
    color: #f38ba8;
}

.status-completed {
    color: #a6e3a1;
}

.status-error {
    color: #f38ba8;
}

/* Input styling */
#user-input {
    margin: 0 1 0 0;
    background: #313244;
    color: #cdd6f4;
    border: none;
    width: 1fr;
}

#send-button {
    background: #89b4fa;
    color: #1e1e2e;
    max-width: 15;
}

/* Status bar */
#status-bar {
    height: 1;
    margin-top: 1;
    width: 100%;
    background: #181825;
    color: #a6adc8;
}

#model-info {
    width: 1fr;
    text-align: left;
    padding: 0 1;
}

#status-text {
    width: 1fr;
    text-align: center;
    padding: 0 1;
}

#token-count {
    width: 1fr;
    text-align: right;
    padding: 0 1;
}

.status-busy {
    background: #45475a;
}

.status-error {
    background: #432635;
}

/* Loading indicator */
#loading-indicator {
    align: center middle;
    background: rgba(30, 30, 46, 0.8);
    color: #89b4fa;
}

/* Help container */
#help-container {
    align: center middle;
    width: 80%;
    height: 80%;
    background: #313244;
    border: solid #45475a;
    layout: vertical;
    padding: 1;
}

#help-title {
    text-align: center;
    text-style: bold;
    color: #89b4fa;
    margin-bottom: 1;
}

#help-content {
    width: 100%;
    height: 1fr;
    background: #1e1e2e;
    border: solid #45475a;
    padding: 1;
}

#close-help-button {
    margin-top: 1;
    background: #89b4fa;
    color: #1e1e2e;
    width: 100%;
}

/* Model selector */
#model-selector {
    align: center middle;
    width: 80%;
    height: 80%;
    background: #313244;
    border: solid #45475a;
    layout: vertical;
    padding: 1;
}

#model-selector-title {
    text-align: center;
    text-style: bold;
    color: #89b4fa;
    margin-bottom: 1;
}

#model-list {
    width: 100%;
    height: 1fr;
    background: #1e1e2e;
    border: solid #45475a;
    padding: 1;
}

.provider-header {
    color: #f5e0dc;
    background: #45475a;
    margin: 1 0;
    padding: 0 1;
}

.model-button {
    margin: 0 0 1 2;
    background: #313244;
    color: #cdd6f4;
    border: solid #45475a;
    width: 90%;
}

#close-model-selector-button {
    margin-top: 1;
    background: #89b4fa;
    color: #1e1e2e;
    width: 100%;
}

/* Utility */
.hidden {
    display: none;
}
    """
    
    with open(css_path, "w") as f:
        f.write(css_content)
    
    print(f"Created CSS file: {css_path}")


async def main() -> None:
    """Initialize and run the app"""
    # Import here to avoid circular imports
    import sys
    from penguin.core import PenguinCore
    
    try:
        print("Initializing Penguin Core...")
        
        # Create and initialize core
        core = await PenguinCore.create()
        
        # Force CSS file creation/update to ensure it's correct
        css_path = Path(__file__).parent / "textual_cli.css"
        create_css_file()
        print(f"CSS file updated: {css_path}")
        
        # Start the app
        app = PenguinApp(core)
        await app.run_async()
        
    except KeyboardInterrupt:
        print("\nExiting Penguin AI...")
    except Exception as e:
        print(f"Error starting Penguin: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


def main_wrapper() -> None:
    """Entry point wrapper for setuptools"""
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nExiting Penguin AI...")
    except Exception as e:
        print(f"Error starting Penguin: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main()) 