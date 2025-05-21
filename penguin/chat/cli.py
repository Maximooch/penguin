import asyncio
import datetime
import os
import signal
import traceback
import re
from pathlib import Path
from typing import List, Optional, Callable, Dict, Any, Set, Union

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
    rich = time_import("rich.console")
    Console = rich.Console
    Markdown = time_import("rich.markdown").Markdown
    Panel = time_import("rich.panel").Panel 
    Progress = time_import("rich.progress").Progress
    SpinnerColumn = time_import("rich.progress").SpinnerColumn
    TextColumn = time_import("rich.progress").TextColumn
    Syntax = time_import("rich.syntax").Syntax
    Live = time_import("rich.live").Live
    
    prompt_toolkit = time_import("prompt_toolkit")
    KeyBindings = time_import("prompt_toolkit.key_binding").KeyBindings
    Keys = time_import("prompt_toolkit.keys").Keys
    Style = time_import("prompt_toolkit.styles").Style
    HTML = time_import("prompt_toolkit.formatted_text").HTML
    
    # Time internal imports
    config = time_import("penguin.config")
    PenguinCore = time_import("penguin.core").PenguinCore
    APIClient = time_import("penguin.llm.api_client").APIClient
    ModelConfig = time_import("penguin.llm.model_config").ModelConfig
    RunMode = time_import("penguin.run_mode").RunMode
    MessageCategory = time_import("penguin.system.state").MessageCategory
    parse_iso_datetime = time_import("penguin.system.state").parse_iso_datetime
    ConversationMenu = time_import("penguin.system.conversation_menu").ConversationMenu
    ConversationSummary = time_import("penguin.system.conversation_menu").ConversationSummary
    SYSTEM_PROMPT = time_import("penguin.system_prompt").SYSTEM_PROMPT
    ToolManager = time_import("penguin.tools").ToolManager
    log_error = time_import("penguin.utils.log_error").log_error
    setup_logger = time_import("penguin.utils.logs").setup_logger
    PenguinInterface = time_import("penguin.chat.interface").PenguinInterface
    
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
    from rich.console import Console  # type: ignore
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

# Most of these Penguin imports aside from the interface are not used in the CLI
    from penguin.config import config
    from penguin.core import PenguinCore
    from penguin.llm.api_client import APIClient
    from penguin.llm.model_config import ModelConfig
    from penguin.run_mode import RunMode
    from penguin.system.state import parse_iso_datetime, MessageCategory
    from penguin.system.conversation_menu import ConversationMenu, ConversationSummary
    from penguin.system_prompt import SYSTEM_PROMPT
    from penguin.tools import ToolManager
    from penguin.utils.log_error import log_error
    from penguin.utils.logs import setup_logger


    from penguin.chat.interface import PenguinInterface

app = typer.Typer(help="Penguin AI Assistant")
console = Console()

# Add a main command that calls the chat function when no subcommand is specified
@app.callback(invoke_without_command=True)
def main(ctx: typer.Context): # TODO: variable not allowed in type expression
    """Penguin AI Assistant - Main entry point"""
    # If no subcommand was invoked, run the chat command
    if ctx.invoked_subcommand is None:
        typer.run(chat)

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
        self.console = Console()
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
                        output_panel = Panel(
                            Syntax(
                                code_output, language, theme="monokai", word_wrap=True
                            ),
                            title=f"📤 {lang_display} Output",
                            title_align="left",
                            border_style="green",
                            padding=(1, 2),
                        )
                        self.console.print(output_panel)
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

    def display_action_result(self, result: Dict[str, Any]):
        """Display action results in a more readable format"""
        # Print debug info to diagnose action result content
        print(f"[DEBUG] Action result: {result}")
        
        action_type = result.get("action", "unknown")
        result_text = result.get("result", "")
        status = result.get("status", "unknown")
        
        status_icon = "✓" if status == "completed" else "❌"
        header = f"🔧 Action Result: {action_type}"
        content = f"{status_icon} {action_type}\n\n{result_text}" if result_text else f"{status_icon} {action_type}\n\n(No output available)"

        # Special handling for code execution results
        if action_type in ["execute", "execute_code"]:
            # Auto-detect language from the code
            language = self._detect_language(result_text)

            # Get language display name
            lang_display = self.LANGUAGE_DISPLAY_NAMES.get(
                language, language.capitalize()
            )

            # Show the full action type and status first
            self.console.print(f"[bold blue]{status_icon}[/bold blue] [bold green]Python code executed[/bold green]")
            
            # Display code output separately
            output_panel = Panel(
                Syntax(result_text, language, theme="monokai", word_wrap=True),
                title=f"📤 Python Code Output",
                title_align="left",
                border_style=self.RESULT_COLOR,
                width=self.console.width - 8,
            )
            self.console.print(output_panel)
        else:
            # Regular action result display
            panel = Panel(
                Markdown(content),
                title=header,
                title_align="left",
                border_style=self.TOOL_COLOR,
                width=self.console.width - 8,
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
                            async def async_stream_callback(chunk: str):
                                self.stream_callback(chunk)
                                
                            async def ui_update_callback():
                                # Can be expanded with UI refresh logic if needed
                                pass
                                
                            # Handle through interface
                            response = await self.interface.handle_command(
                                user_input[1:],  # Remove the leading slash
                                runmode_stream_cb=async_stream_callback,
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

                                # Prepare streaming callback so the usual live render is used
                                async def async_stream_callback(chunk: str):
                                    self.stream_callback(chunk)

                                # Send the message through the standard interface path so all
                                # normal streaming / action-result handling is reused
                                response = await self.interface.process_input(
                                    {"text": description, "image_path": image_path},
                                    stream_callback=async_stream_callback,
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
                    except Exception as e:
                        self.display_message(f"Error executing command: {str(e)}", "error")
                        self.display_message(traceback.format_exc(), "error")
                    
                    continue  # Back to prompt after command processing

                # Process normal message input through interface
                try:
                    # Create streaming callback that updates our UI
                    async def stream_callback(chunk: str):
                        self.stream_callback(chunk)
                        
                    # Process user message through interface
                    response = await self.interface.process_input(
                        {"text": user_input},
                        stream_callback=stream_callback
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

    # Improved stream_callback that uses Rich Live display
    def stream_callback(self, content: str):
        """Handle streaming content from LLM using Rich Live display"""
        # Handle non-string content
        if not isinstance(content, str):
            try:
                content = str(content)
            except:
                return  # Skip content that can't be converted to string

        # Extract content from ModelResponse objects if needed
        if "ModelResponse" in content or "Message(content=" in content:
            content_patterns = [
                r'Message\(content="([^"]+)"',  # Match Message(content="text")
                r"Message\(content='([^']+)'",  # Match Message(content='text')
                r'content="([^"]+)"',  # Match content="text"
                r"content='([^']+)'",  # Match content='text'
                r"content=([^,\)]+)",  # Match content=text
            ]

            for pattern in content_patterns:
                match = re.search(pattern, content)
                if match:
                    content = match.group(1)
                    break
            else:
                return  # Skip if no pattern matched

        # Skip empty or whitespace-only content
        if not content.strip():
            return

        # Ensure progress indicators are cleared
        if self.progress:
            self._safely_stop_progress()

        # Filter out initial chunks that only repeat what we already displayed
        if (
            (not hasattr(self, "_streaming_started") or not self._streaming_started)
            and self.last_completed_message
            and content.startswith(self.last_completed_message)
        ):
            # Compute the delta (new part after the previous completed message)
            delta = content[len(self.last_completed_message):]
            if not delta.strip():
                # Nothing new – skip to avoid creating a second Live panel
                return
            content = delta  # Show only the new part

        # Initialize streaming if this is the first chunk (after duplication check)
        if not hasattr(self, "_streaming_started") or not self._streaming_started:
            # Cancel any pending messages
            print("\033[2K\r", end="")  # Clear current line
            
            # Start with a fresh line if not inside a Live display
            if not self.streaming_live:
                self._streaming_started = True
                self._streamed_content = []
                self.streaming_buffer = content
                
                # Create a simple markdown panel for ongoing streaming
                panel = Panel(
                    Markdown(content),
                    title=f"{self.PENGUIN_EMOJI} Penguin (Streaming)",
                    title_align="left",
                    border_style=self.PENGUIN_COLOR,
                    width=self.console.width - 8,
                )
                
                # Start a new Live display for the streaming content (without screen mode)
                # Setting vertical_overflow="visible" ensures that the Live
                # renderer *appends* new lines instead of re-painting only the
                # visible viewport.  This preserves the scroll-back buffer so
                # you can scroll and inspect the full history during long
                # RunMode sessions.
                self.streaming_live = Live(
                    panel,
                    refresh_per_second=10,
                    console=self.console,
                    vertical_overflow="visible",  # keep full scrollback
                )
                self.streaming_live.start()
            else:
                # Append to existing content
                self.streaming_buffer += content
                self._streamed_content.append(content)
                
                # Update the live display
                panel = Panel(
                    Markdown(self.streaming_buffer),
                    title=f"{self.PENGUIN_EMOJI} Penguin (Streaming)",
                    title_align="left",
                    border_style=self.PENGUIN_COLOR,
                    width=self.console.width - 8,
                )
                self.streaming_live.update(panel)
        else:
            # Drop exact-duplicate chunks we have already processed in this
            # streaming session (some providers re-emit the same buffer).
            if content in self._streamed_content:
                return

            # Append to existing content
            self.streaming_buffer += content
            self._streamed_content.append(content)

            # Update the live display if it exists
            if self.streaming_live:
                panel = Panel(
                    Markdown(self.streaming_buffer),
                    title=f"{self.PENGUIN_EMOJI} Penguin (Streaming)",
                    title_align="left",
                    border_style=self.PENGUIN_COLOR,
                    width=self.console.width - 8,
                )
                self.streaming_live.update(panel)
            else:
                # Fallback to print if no live display
                print(content, end="", flush=True)

        # Store for deduplication
        self.last_completed_message = self.streaming_buffer
        
        # Mark this message as processed to avoid duplication
        msg_key = f"assistant:{self.streaming_buffer[:50]}"
        self.processed_messages.add(msg_key)
        self.message_turn_map[msg_key] = self.current_conversation_turn

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
                # Handle streaming chunks
                chunk = data.get("chunk", "")
                is_final = data.get("is_final", False)
                self.streaming_role = data.get("role", "assistant")

                if is_final:
                    # Final chunk received
                    self.is_streaming = False

                    # If complete content is provided, use it
                    if data.get("content"):
                        self.streaming_buffer = data["content"]

                    # Store this message as completed to avoid duplication
                    self.last_completed_message = self.streaming_buffer

                    # Generate a message key for this completed message
                    completed_msg_key = (
                        f"{self.streaming_role}:{self.streaming_buffer[:50]}"
                    )
                    self.processed_messages.add(completed_msg_key)

                    # Associate this message with the current conversation turn
                    self.message_turn_map[completed_msg_key] = (
                        self.current_conversation_turn
                    )

                    # Display the final message if not already displayed via streaming
                    if (
                        not hasattr(self, "_streaming_started")
                        or not self._streaming_started
                    ):
                        self.display_message(self.streaming_buffer, self.streaming_role)

                    # Reset streaming buffer
                    self.streaming_buffer = ""
                    if hasattr(self, "_streaming_started"):
                        self._streaming_started = False
                    if hasattr(self, "_streamed_content"):
                        self._streamed_content = []
                else:
                    # Accumulate chunks
                    self.is_streaming = True
                    self.streaming_buffer += chunk

                    # Use existing stream_callback to maintain consistent UI
                    self.stream_callback(chunk)

            elif event_type == "token_update":
                # Could update a token display here if we add one
                pass

            elif event_type == "message":
                # A new message has been added to the conversation
                role = data.get("role", "unknown")
                content = data.get("content", "")
                category = data.get("category", MessageCategory.DIALOG)

                # Skip system messages by default (continue existing behavior)
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

                # Add to processed messages and map to current turn
                self.processed_messages.add(msg_key)
                self.message_turn_map[msg_key] = self.current_conversation_turn

                # Display the message if it's not currently being streamed
                if not self.is_streaming or role != "assistant":
                    # Don't display if it matches the last completed message which may have been shown via streaming
                    if content != self.last_completed_message or role != "assistant":
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
def chat(
    model: str = typer.Option(None, "--model", "-m", help="Specify the model to use"),
    workspace: Path = typer.Option(
        None, "--workspace", "-w", help="Set custom workspace path"
    ),
    no_streaming: bool = typer.Option(
        False, "--no-streaming", help="Disable streaming mode"
    ),
):
    """Start an interactive chat session with Penguin"""

    async def run():
        # Add timing for CLI startup
        import time
        cli_start_time = time.time()
        console.print("[bold blue]Starting Penguin...[/bold blue]")
        
        # Load configuration
        loaded_config = config
        config_time = time.time()
        console.print(f"[dim]Config loaded in {(config_time - cli_start_time)*1000:.0f}ms[/dim]")

        # Initialize model configuration - respect config but allow CLI override
        streaming_enabled = not no_streaming and loaded_config["model"].get(
            "streaming_enabled", True
        )

        model_config = ModelConfig(
            model=model or loaded_config["model"]["default"],
            provider=loaded_config["model"]["provider"],
            api_base=loaded_config["api"]["base_url"],
            client_preference=loaded_config["model"].get("client_preference", "native"),
            streaming_enabled=streaming_enabled,
        )
        model_time = time.time()
        console.print(f"[dim]Model config created in {(model_time - config_time)*1000:.0f}ms[/dim]")

        # Create API client
        console.print("[dim]Initializing API client...[/dim]")
        api_start_time = time.time()
        api_client = APIClient(model_config=model_config)
        api_client.set_system_prompt(SYSTEM_PROMPT)
        api_time = time.time()
        console.print(f"[dim]API client initialized in {(api_time - api_start_time)*1000:.0f}ms[/dim]")
        
        # Initialize tool manager
        console.print("[dim]Loading tools...[/dim]")
        tools_start_time = time.time()
        tool_manager = ToolManager(log_error)
        tools_time = time.time()
        console.print(f"[dim]Tools loaded in {(tools_time - tools_start_time)*1000:.0f}ms[/dim]")

        # Create core and interface
        console.print("[dim]Initializing Penguin core...[/dim]")
        core_start_time = time.time()
        core = PenguinCore(api_client=api_client, tool_manager=tool_manager)
        core.set_system_prompt(SYSTEM_PROMPT)
        core_time = time.time()
        console.print(f"[dim]Core initialized in {(core_time - core_start_time)*1000:.0f}ms[/dim]")
        
        # Initialize interface - now used as the adapter between CLI and Core
        interface_start_time = time.time()
        interface = PenguinInterface(core)
        interface_time = time.time()
        console.print(f"[dim]Interface initialized in {(interface_time - interface_start_time)*1000:.0f}ms[/dim]")
        
        # Initialize CLI with core reference
        cli_init_start_time = time.time()
        cli = PenguinCLI(core)
        cli.interface = interface  # Make sure the interface is set
        cli_init_time = time.time()
        console.print(f"[dim]CLI components initialized in {(cli_init_time - cli_init_start_time)*1000:.0f}ms[/dim]")
        
        # Display total startup time
        total_startup_time = time.time() - cli_start_time
        console.print(f"[bold green]Penguin started in {total_startup_time:.2f} seconds[/bold green]")
        
        # Start chat loop
        await cli.chat_loop()

    try:
        asyncio.run(run())
    except Exception as e:
        console.print(f"[red]Fatal error: {str(e)}[/red]")
        raise typer.Exit(1)


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
    from pathlib import Path
    import subprocess
    import sys
    
    # Create a profile directory if it doesn't exist
    profile_dir = Path("profiles")
    profile_dir.mkdir(exist_ok=True)
    
    # Prepare the output file name
    if not output_file:
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        output_file = f"penguin_profile_{timestamp}"
    
    output_path = profile_dir / f"{output_file}.prof"
    stats_path = profile_dir / f"{output_file}.txt"
    
    console.print(f"[bold blue]Starting Penguin with profiling enabled...[/bold blue]")
    console.print(f"Profile data will be saved to: [cyan]{output_path}[/cyan]")
    
    # Define a function that runs the "penguin" command without any subcommands
    # This will trigger our main/callback function which runs chat
    def run_profiled_penguin():
        # Rather than calling typer.run(chat), we'll run a fresh penguin process
        # with the exact same environment to get the most accurate profile of the entire startup
        cmd = [sys.executable, "-m", "penguin.penguin"]
        try:
            subprocess.run(cmd, check=True)
        except subprocess.CalledProcessError:
            console.print("[yellow]Penguin process exited with an error.[/yellow]")
        except KeyboardInterrupt:
            console.print("[yellow]Penguin process interrupted by user.[/yellow]")
    
    # Start profiler
    profiler = cProfile.Profile()
    profiler.enable()
    
    try:
        # Run Penguin with profiling
        run_profiled_penguin()
    except Exception as e:
        console.print(f"[red]Error during profiled run: {str(e)}[/red]")
    finally:
        # Stop profiler
        profiler.disable()
        console.print("[green]Profiling complete.[/green]")
        
        # Save profile data
        profiler.dump_stats(str(output_path))
        console.print(f"Profile data saved to: [cyan]{output_path}[/cyan]")
        
        # Create readable stats
        s = io.StringIO()
        ps = pstats.Stats(profiler, stream=s).sort_stats('cumulative')
        ps.print_stats(20)  # Print top 20 functions by cumulative time
        stats_content = s.getvalue()
        
        with open(stats_path, 'w') as f:
            f.write(stats_content)
        
        console.print(f"Profile summary saved to: [cyan]{stats_path}[/cyan]")
        console.print("[bold]Top 20 functions by cumulative time:[/bold]")
        console.print(stats_content)
        
        # Open visualization if requested
        if view:
            try:
                subprocess.run(["snakeviz", str(output_path)], check=True)
            except Exception as e:
                console.print(f"[yellow]Could not open visualization: {str(e)}[/yellow]")
                console.print(f"[yellow]You can manually visualize the profile with: snakeviz {output_path}[/yellow]")

        console.print("[bold green]Profiling complete.[/bold green]")
        console.print(f"[dim]You can visualize the profile using: snakeviz {output_path}[/dim]")
        console.print("[dim]Or install other profile visualization tools.[/dim]")

if __name__ == "__main__":
    app()
