# -*- coding: utf-8 -*-

"""
New, refactored CLI for Penguin AI Assistant.

This module focuses on the UI aspects, while business logic is in interface.py.
The separation of concerns allows for easier maintenance and extension.
"""

import asyncio
import os
import signal
import re
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any, Union

import typer
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.syntax import Syntax
from rich.table import Table
from rich import box
from rich.live import Live
from rich.layout import Layout
from prompt_toolkit import PromptSession
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.keys import Keys
from prompt_toolkit.styles import Style
from prompt_toolkit.formatted_text import HTML

from penguin.config import config
from penguin.core import PenguinCore
from penguin.llm.api_client import APIClient
from penguin.llm.model_config import ModelConfig
from penguin.system.conversation import parse_iso_datetime
from penguin.system.conversation_menu import ConversationMenu, ConversationSummary
from penguin.system_prompt import SYSTEM_PROMPT
from penguin.tools import ToolManager
from penguin.utils.log_error import log_error
from penguin.utils.logs import setup_logger
from penguin.chat.interface import PenguinInterface

app = typer.Typer(help="Penguin AI Assistant")
console = Console()

class PenguinCLI:
    # Colors and styling
    USER_COLOR = "cyan"
    PENGUIN_COLOR = "blue"
    TOOL_COLOR = "yellow"
    RESULT_COLOR = "green"
    CODE_COLOR = "bright_blue"
    TOKEN_COLOR = "bright_magenta"
    PENGUIN_EMOJI = "='"
    
    # Language detection and mapping
    CODE_BLOCK_PATTERNS = [
        # Standard markdown code blocks with language specification
        (r'```(\w+)(.*?)```', '{}'),  # Captures language and code
        # Execute blocks
        (r'<execute>(.*?)</execute>', 'python'),
        # Language-specific tags
        (r'<python>(.*?)</python>', 'python'),
        (r'<javascript>(.*?)</javascript>', 'javascript'),
        (r'<js>(.*?)</js>', 'javascript'),
        (r'<html>(.*?)</html>', 'html'),
        (r'<css>(.*?)</css>', 'css'),
        (r'<java>(.*?)</java>', 'java'),
        (r'<c\+\+>(.*?)</c\+\+>', 'cpp'),
        (r'<cpp>(.*?)</cpp>', 'cpp'),
        (r'<c#>(.*?)</c#>', 'csharp'),
        (r'<csharp>(.*?)</csharp>', 'csharp'),
        (r'<typescript>(.*?)</typescript>', 'typescript'),
        (r'<ts>(.*?)</ts>', 'typescript'),
        (r'<ruby>(.*?)</ruby>', 'ruby'),
        (r'<go>(.*?)</go>', 'go'),
        (r'<rust>(.*?)</rust>', 'rust'),
        (r'<php>(.*?)</php>', 'php'),
        (r'<swift>(.*?)</swift>', 'swift'),
        (r'<kotlin>(.*?)</kotlin>', 'kotlin'),
        (r'<shell>(.*?)</shell>', 'bash'),
        (r'<bash>(.*?)</bash>', 'bash'),
        (r'<sql>(.*?)</sql>', 'sql'),
        # Default code block (no language specified)
        (r'<code>(.*?)</code>', 'text'),
    ]
    
    # Language detection patterns
    LANGUAGE_DETECTION_PATTERNS = [
        # Python
        (r'import\s+[\w.]+|def\s+\w+\s*\(|class\s+\w+\s*[:\(]|print\s*\(', 'python'),
        # JavaScript
        (r'function\s+\w+\s*\(|const\s+\w+\s*=|let\s+\w+\s*=|var\s+\w+\s*=|console\.log\(', 'javascript'),
        # HTML
        (r'<!DOCTYPE\s+html>|<html>|<body>|<div>|<span>|<p>', 'html'),
        # CSS
        (r'body\s*{|\.[\w-]+\s*{|#[\w-]+\s*{|\@media', 'css'),
        # Java
        (r'public\s+class|private\s+\w+\(|protected|System\.out\.print', 'java'),
        # C++
        (r'#include\s+<\w+>|std::|namespace\s+\w+|template\s*<', 'cpp'),
        # C#
        (r'using\s+System;|namespace\s+\w+|public\s+class|Console\.Write', 'csharp'),
        # TypeScript
        (r'interface\s+\w+|type\s+\w+\s*=|export\s+class', 'typescript'),
        # Ruby
        (r'require\s+[\'\"][\w./]+[\'\"]|def\s+\w+(\s*\|\s*.*?\s*\|)?|puts\s+', 'ruby'),
        # Go
        (r'package\s+\w+|func\s+\w+|import\s+\(|fmt\.Print', 'go'),
        # Rust
        (r'fn\s+\w+|let\s+mut|struct\s+\w+|impl\s+', 'rust'),
        # PHP
        (r'<\?php|\$\w+\s*=|echo\s+|function\s+\w+\s*\(', 'php'),
        # Swift
        (r'import\s+\w+|var\s+\w+\s*:|func\s+\w+\s*\(|class\s+\w+\s*:|\@IBOutlet', 'swift'),
        # Kotlin
        (r'fun\s+\w+\s*\(|val\s+\w+\s*:|var\s+\w+\s*:|class\s+\w+\s*[:\(]', 'kotlin'),
        # Bash
        (r'#!/bin/bash|#!/bin/sh|^\s*if\s+\[\s+|^\s*for\s+\w+\s+in', 'bash'),
        # SQL
        (r'SELECT\s+.*?\s+FROM|CREATE\s+TABLE|INSERT\s+INTO|UPDATE\s+.*?\s+SET', 'sql'),
    ]
    
    # Language display names
    LANGUAGE_DISPLAY_NAMES = {
        'python': 'Python',
        'javascript': 'JavaScript',
        'html': 'HTML',
        'css': 'CSS',
        'java': 'Java',
        'cpp': 'C++',
        'csharp': 'C#',
        'typescript': 'TypeScript',
        'ruby': 'Ruby',
        'go': 'Go',
        'rust': 'Rust',
        'php': 'PHP',
        'swift': 'Swift',
        'kotlin': 'Kotlin',
        'bash': 'Shell/Bash',
        'sql': 'SQL',
        'text': 'Code',
    }

    def __init__(self, interface: PenguinInterface):
        self.interface = interface
        self.console = Console()
        self.conversation_menu = ConversationMenu(self.console)
        self.progress = None
        self.progress_task = None
        self.token_usage = {"prompt": 0, "completion": 0, "total": 0}
        self.token_display_enabled = True
        
        # Create prompt_toolkit session
        self.session = self._create_prompt_session()
        
        # Register callbacks
        self.interface.register_progress_callback(self.on_progress_update)
        self.interface.register_token_callback(self.on_token_update)
        
        # Add signal handler for clean interrupts
        signal.signal(signal.SIGINT, self._handle_interrupt)
    
    def _create_prompt_session(self):
        """Create and configure a prompt_toolkit session with multi-line support"""
        # Define key bindings
        kb = KeyBindings()
        
        # Add keybinding for Alt+Enter to create a new line
        @kb.add(Keys.Escape, Keys.Enter)
        def _(event):
            """Insert a new line when Alt (or Option) + Enter is pressed."""
            event.current_buffer.insert_text('\n')
        
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
                buffer.insert_text('\n')
        
        # Add a custom style
        style = Style.from_dict({
            'prompt': f'bold {self.USER_COLOR}',
        })
        
        # Create the PromptSession
        return PromptSession(
            key_bindings=kb,
            style=style,
            multiline=True,
            vi_mode=False,
            wrap_lines=True,
            complete_in_thread=True
        )
    
    def _handle_interrupt(self, sig, frame):
        self._safely_stop_progress()
        print("\nOperation interrupted by user.")
        raise KeyboardInterrupt

    def display_message(self, message: str, role: str = "assistant"):
        """Display a message with proper formatting"""
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
            "user": "=d",
            "system": "=�",
            "error": "�",
            "code": "=�",
        }

        style = styles.get(role, "white")
        emoji = emojis.get(role, "=�")

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
            if default_lang == '{}':  # Standard markdown code block
                for lang, code in matches:
                    if not lang:
                        lang = "text"  # Default to plain text if no language specified
                    code_blocks_found = True
                    processed_message = self._format_code_block(processed_message, code, lang, f"```{lang}{code}```")
            else:  # Tag-based code block
                for i, code_match in enumerate(matches):
                    # Handle single group or multi-group regex results
                    code = code_match if isinstance(code_match, str) else code_match[0]
                    lang = default_lang
                    
                    tag_start = f"<{lang}>" if lang != "python" else "<execute>"
                    tag_end = f"</{lang}>" if lang != "python" else "</execute>"
                    original_block = f"{tag_start}{code}{tag_end}"
                    
                    code_blocks_found = True
                    processed_message = self._format_code_block(processed_message, code, lang, original_block)

        # Regular message display with markdown
        panel = Panel(
            Markdown(processed_message),
            title=header,
            title_align="left",
            border_style=style,
            width=self.console.width - 8,
            box=box.ROUNDED
        )
        self.console.print(panel)
        
    def _format_code_block(self, message, code, language, original_block):
        """Format a code block with syntax highlighting and return updated message"""
        # Get the display name for the language or use language code as fallback
        lang_display = self.LANGUAGE_DISPLAY_NAMES.get(language, language.capitalize())
        
        # If language is 'text', try to auto-detect
        if language == 'text' and code.strip():
            detected_lang = self._detect_language(code)
            if detected_lang != 'text':
                language = detected_lang
                lang_display = self.LANGUAGE_DISPLAY_NAMES.get(language, language.capitalize())
        
        # Create a syntax highlighted version
        highlighted_code = Syntax(
            code.strip(), 
            language, 
            theme="monokai", 
            line_numbers=True,
            word_wrap=True,
            code_width=min(100, self.console.width - 20)
        )
        
        # Create a panel for the code
        code_panel = Panel(
            highlighted_code,
            title=f"=� {lang_display} Code",
            title_align="left",
            border_style=self.CODE_COLOR,
            padding=(1, 2)
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
        if code.count('#include') > 0:
            return 'cpp'
        if code.count('def ') > 0 or code.count('import ') > 0:
            return 'python'
        if code.count('function') > 0 or code.count('var ') > 0 or code.count('const ') > 0:
            return 'javascript'
        if code.count('<html') > 0 or code.count('<div') > 0:
            return 'html'
            
        # Default to text if no patterns matched
        return "text"

    def display_action_result(self, result: Dict[str, Any]):
        """Display action results in a more readable format"""
        status_icon = "" if result.get("status") == "completed" else "L"
        
        header = f"=' Command Result"
        content = f"{status_icon} {result.get('action', 'unknown')}\n\n{result.get('result', '')}"
        
        # Special handling for code execution results
        if result.get('action') == 'execute_code':
            # Get result text
            result_text = result.get('result', '')
            
            # Auto-detect language from the code
            language = self._detect_language(result_text)
            
            # Get language display name
            lang_display = self.LANGUAGE_DISPLAY_NAMES.get(language, language.capitalize())
            
            # Display code output separately
            output_panel = Panel(
                Syntax(result_text, language, theme="monokai"),
                title=f"=� {lang_display} Output",
                title_align="left", 
                border_style=self.RESULT_COLOR,
                width=self.console.width - 8
            )
            self.console.print(output_panel)
        else:
            # Regular action result display
            panel = Panel(
                Markdown(content),
                title=header,
                title_align="left",
                border_style=self.TOOL_COLOR,
                width=self.console.width - 8
            )
            self.console.print(panel)

    def on_progress_update(self, iteration: int, max_iterations: int, message: Optional[str] = None):
        """Handle progress updates"""
        if not self.progress and iteration > 0:
            # Only show progress if not already processing
            self._safely_stop_progress()
            self.progress = Progress(
                SpinnerColumn(),
                TextColumn("[bold blue]{task.description}"),
                console=self.console
            )
            self.progress.start()
            self.progress_task = self.progress.add_task(
                f"Thinking... (Step {iteration}/{max_iterations})", 
                total=max_iterations
            )
        
        if self.progress:
            # Update without completing to prevent early termination
            self.progress.update(
                self.progress_task,
                description=f"{message or 'Processing'} (Step {iteration}/{max_iterations})",
                completed=min(iteration, max_iterations-1)  # Never mark fully complete
            )

    def on_token_update(self, usage: Dict[str, int]):
        """Handle token usage updates"""
        self.token_usage = usage

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

    def display_token_usage(self):
        """Display token usage information"""
        if not self.token_display_enabled:
            return
            
        # Create a simple token usage display
        prompt_tokens = self.token_usage.get("prompt", 0)
        completion_tokens = self.token_usage.get("completion", 0)
        total_tokens = self.token_usage.get("total", 0)
        
        # Calculate costs (approximate)
        # These rates should be configurable or based on actual model rates
        input_rate = 0.000001  # $0.001 per 1K tokens
        output_rate = 0.000002  # $0.002 per 1K tokens
        
        input_cost = prompt_tokens * input_rate
        output_cost = completion_tokens * output_rate
        total_cost = input_cost + output_cost
        
        # Create token usage table
        table = Table(
            title="Token Usage", 
            box=box.SIMPLE,
            title_style=f"bold {self.TOKEN_COLOR}",
            border_style=self.TOKEN_COLOR,
            width=30
        )
        
        table.add_column("Type", style="dim")
        table.add_column("Tokens", style="bold")
        table.add_column("Cost", style="italic")
        
        table.add_row("Input", str(prompt_tokens), f"${input_cost:.5f}")
        table.add_row("Output", str(completion_tokens), f"${output_cost:.5f}")
        table.add_row("Total", str(total_tokens), f"${total_cost:.5f}")
        
        # Print in a compact way at the bottom right
        with console.capture() as capture:
            console.print(table)
        
        # Print the table to the right side
        token_display = capture.get()
        console.print(token_display, justify="right")

    def display_help(self):
        """Display help information"""
        help_panel = Panel(
            Markdown("\n".join([
                "## Available Commands",
                "",
                "- `/chat [list|load|summary]` - Conversation management",
                "- `/task [create|run|status]` - Task management",
                "- `/project [create|run|status]` - Project management",
                "- `/run [--247] [--time MINUTES]` - Run tasks or continuous mode",
                "- `/image [PATH]` - Process an image",
                "- `/tokens [reset]` - Show or reset token usage",
                "- `/context [list|load FILE]` - Manage context files",
                "- `/list` - Show projects and tasks",
                "- `/help` - Show this help message",
                "- `/exit` - Exit the program",
                "",
                "### Tips",
                "- Use Alt+Enter for multiline messages",
                "- Press Enter to send",
                "- Press Ctrl+C to interrupt processing"
            ])),
            title="=' Penguin Help",
            title_align="left",
            border_style="blue",
            width=self.console.width - 8
        )
        console.print(help_panel)

    def display_welcome_message(self):
        """Display welcome message"""
        welcome_message = """Welcome to the Penguin AI Assistant!

Use the chat interface below to communicate with Penguin.
Type /help to see available commands.

TIP: Use Alt+Enter for multiline messages, Enter to send."""

        self.display_message(welcome_message, "system")

    async def process_command_response(self, response: Dict[str, Any]):
        """Process and display command response"""
        if "error" in response:
            self.display_message(response["error"], "error")
            if "suggestions" in response:
                self.display_message("Available commands:\n" + "\n".join(response["suggestions"]), "system")
        
        elif "help" in response:
            self.display_help()
            
        elif "token_usage" in response:
            # Display detailed token usage
            usage = response["token_usage"]
            self.display_message(
                f"Token Usage:\n"
                f"- Input: {usage.get('prompt', 0)} tokens\n"
                f"- Output: {usage.get('completion', 0)} tokens\n"
                f"- Total: {usage.get('total', 0)} tokens",
                "system"
            )
            
        elif "context_files" in response:
            # Display context files
            files = response["context_files"]
            if not files:
                self.display_message("No context files available", "system")
            else:
                file_table = Table(title="Available Context Files")
                file_table.add_column("Filename", style="cyan")
                file_table.add_column("Type", style="green")
                file_table.add_column("Size", style="blue")
                file_table.add_column("Modified", style="yellow")
                file_table.add_column("Core", style="magenta")
                
                for file in files:
                    file_table.add_row(
                        file.get("path", ""),
                        file.get("type", "unknown"),
                        f"{file.get('size', 0) / 1024:.1f} KB",
                        datetime.fromtimestamp(file.get("modified", 0)).strftime("%Y-%m-%d %H:%M"),
                        "" if file.get("is_core", False) else ""
                    )
                
                console.print(file_table)
                
        elif "conversations" in response:
            # Let the conversation menu handle this
            conversations = [
                ConversationSummary(
                    session_id=meta.session_id,
                    title=meta.title or f"Conversation {idx + 1}",
                    message_count=meta.message_count,
                    last_active=parse_iso_datetime(meta.last_active),
                )
                for idx, meta in enumerate(response["conversations"])
            ]
            session_id = self.conversation_menu.select_conversation(conversations)
            if session_id:
                await self.interface.handle_command(f"chat load {session_id}")
                self.display_message("Conversation loaded successfully", "system")
                
        elif "summary" in response:
            # Display conversation summary
            messages = response["summary"]
            self.conversation_menu.display_summary(messages)
            
        elif "assistant_response" in response:
            # Display normal response
            self.display_message(response["assistant_response"])
            
            # Display action results if present
            if "action_results" in response:
                for result in response["action_results"]:
                    if isinstance(result, dict):
                        self.display_action_result(result)
                    else:
                        self.display_message(str(result), "system")
                        
        elif "status" in response:
            # Display status message
            self.display_message(response["status"], "system")
            
            # Handle exit
            if response.get("status") == "exit":
                return False
                
        return True  # Continue processing

    async def chat_loop(self):
        """Main chat loop"""
        try:
            # Setup logging
            timestamp = datetime.now()
            session_id = timestamp.strftime("%Y%m%d_%H%M")
            setup_logger(f"chat_{session_id}.log")
            
            # Display welcome message
            self.display_welcome_message()
            
            # Main chat loop
            while self.interface.is_active():
                try:
                    # Clear progress bars and show token usage
                    self._ensure_progress_cleared()
                    self.display_token_usage()
                    
                    # Get message count from interface
                    message_count = self.interface.message_count
                    
                    # Get user input with prompt
                    prompt_html = HTML(f'<prompt>You [{message_count}]: </prompt>')
                    user_input = await self.session.prompt_async(prompt_html)
                    
                    # Check for exit commands
                    if user_input.lower() in ["exit", "quit"]:
                        break
                        
                    # Skip empty messages
                    if not user_input.strip():
                        continue
                        
                    # Display user message
                    self.display_message(user_input, "user")
                    
                    # Process the input
                    if user_input.startswith("/"):
                        # Handle command
                        response = await self.interface.handle_command(user_input[1:])
                        should_continue = await self.process_command_response(response)
                        if not should_continue:
                            break
                    else:
                        # Handle regular message
                        self.display_message("Processing your request...", "system")
                        response = await self.interface.process_input({"text": user_input})
                        await self.process_command_response(response)
                        
                except KeyboardInterrupt:
                    self.display_message("Processing interrupted", "system")
                    self._safely_stop_progress()
                
                except Exception as e:
                    self.display_message(f"Error: {str(e)}", "error")
                    self._safely_stop_progress()
                    
            # Display goodbye message
            console.print("\nGoodbye! =K", style="bold blue")
            
        except Exception as e:
            console.print(f"[bold red]Fatal error: {str(e)}[/bold red]")
            raise

@app.command()
def chat(
    model: str = typer.Option(None, "--model", "-m", help="Specify the model to use"),
    workspace: Path = typer.Option(None, "--workspace", "-w", help="Set custom workspace path"),
    tokens: bool = typer.Option(True, "--tokens/--no-tokens", help="Show token usage")
):
    """Start an interactive chat session with Penguin"""

    async def run():
        # Initialize core components
        model_config = ModelConfig(
            model=model or config["model"]["default"],
            provider=config["model"]["provider"],
            api_base=config["api"]["base_url"],
        )

        api_client = APIClient(model_config=model_config)
        api_client.set_system_prompt(SYSTEM_PROMPT)
        tool_manager = ToolManager(log_error)

        # Create core and CLI
        core = PenguinCore(api_client=api_client, tool_manager=tool_manager, model_config=model_config)
        core.set_system_prompt(SYSTEM_PROMPT)
        
        # Create interface and CLI
        interface = PenguinInterface(core)
        cli = PenguinCLI(interface)
        cli.token_display_enabled = tokens
        
        # Start chat loop
        await cli.chat_loop()

    try:
        asyncio.run(run())
    except Exception as e:
        console.print(f"[red]Fatal error: {str(e)}[/red]")
        raise typer.Exit(1)

if __name__ == "__main__":
    app()