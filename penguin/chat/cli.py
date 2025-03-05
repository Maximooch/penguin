import asyncio
import datetime
import os
import signal
import traceback
import re
from pathlib import Path
from typing import List, Optional, Callable, Dict, Any

import typer  # type: ignore
from rich.console import Console  # type: ignore
from rich.markdown import Markdown  # type: ignore
from rich.panel import Panel  # type: ignore
from rich.progress import Progress, SpinnerColumn, TextColumn  # type: ignore
from rich.syntax import Syntax  # type: ignore
import rich  # type: ignore

from penguin.config import config
from penguin.core import PenguinCore
from penguin.llm.api_client import APIClient
from penguin.llm.model_config import ModelConfig
from penguin.run_mode import RunMode
from penguin.system.conversation import parse_iso_datetime
from penguin.system.conversation_menu import ConversationMenu, ConversationSummary
from penguin.system_prompt import SYSTEM_PROMPT
from penguin.tools import ToolManager
from penguin.utils.log_error import log_error
from penguin.utils.logs import setup_logger

app = typer.Typer(help="Penguin AI Assistant")
console = Console()


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
        (r'```(\w+)(.*?)```', '{}'),  # Captures language and code
        # Execute blocks (for backward compatibility)
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
    
    # Language detection patterns for auto-detection
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
    
    # Language display names (for panel titles)
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

    def __init__(self, core):
        self.core = core
        self.in_247_mode = False
        self.message_count = 0
        self.console = Console()
        self.conversation_menu = ConversationMenu(self.console)
        self.core.register_progress_callback(self.on_progress_update)
        self.progress = None
        # self._active_contexts = set()
        
        # Add signal handler for clean interrupts
        signal.signal(signal.SIGINT, self._handle_interrupt)
    
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
        
        # Special case: Look for code-like content in non-tagged system messages
        if role == "system" and not code_blocks_found:
            # Try to find code-like blocks in the message
            lines = processed_message.split('\n')
            code_block_lines = []
            in_code_block = False
            start_line = 0
            
            for i, line in enumerate(lines):
                # Heuristics to detect code block starts:
                # - Line starts with indentation followed by code-like content
                # - Line contains common code elements like 'def', 'import', etc.
                # - Line starts with a common programming construct
                code_indicators = [
                    re.match(r'\s{2,}[a-zA-Z0-9_]', line),  # Indented code
                    re.search(r'(def|class|import|function|var|let|const)\s+', line),  # Keywords
                    re.match(r'[a-zA-Z0-9_\.]+\s*\(.*\)', line),  # Function calls
                    re.search(r'=.*?;?\s*$', line),  # Assignments
                ]
                
                if any(code_indicators) and not in_code_block:
                    # Start of a potential code block
                    in_code_block = True
                    start_line = i
                elif in_code_block and (not line.strip() or not any(code_indicators)):
                    # End of a code block
                    if i - start_line > 1:  # At least 2 lines of code
                        code_text = '\n'.join(lines[start_line:i])
                        lang = self._detect_language(code_text)
                        
                        # Only format if it looks like valid code
                        if lang != "text":
                            # Replace in the original message
                            for j in range(start_line, i):
                                lines[j] = ""
                            lines[start_line] = f"[Code block displayed below ({self.LANGUAGE_DISPLAY_NAMES.get(lang, lang.capitalize())})]"
                            
                            # Add to code blocks
                            code_block_lines.append((code_text, lang))
                    
                    in_code_block = False
            
            # Handle a code block that goes to the end
            if in_code_block and len(lines) - start_line > 1:
                code_text = '\n'.join(lines[start_line:])
                lang = self._detect_language(code_text)
                
                if lang != "text":
                    # Replace in the original message
                    for j in range(start_line, len(lines)):
                        lines[j] = ""
                    lines[start_line] = f"[Code block displayed below ({self.LANGUAGE_DISPLAY_NAMES.get(lang, lang.capitalize())})]"
                    
                    # Add to code blocks
                    code_block_lines.append((code_text, lang))
            
            # Reassemble the message
            processed_message = '\n'.join(lines)
            
            # Display the detected code blocks
            for code_text, lang in code_block_lines:
                lang_display = self.LANGUAGE_DISPLAY_NAMES.get(lang, lang.capitalize())
                highlighted_code = Syntax(
                    code_text.strip(), 
                    lang, 
                    theme="monokai", 
                    line_numbers=True,
                    word_wrap=True
                )
                
                code_panel = Panel(
                    highlighted_code,
                    title=f"📋 {lang_display} Code",
                    title_align="left",
                    border_style=self.CODE_COLOR,
                    padding=(1, 2)
                )
                self.console.print(code_panel)
        
        # Handle code blocks in tool outputs (like execute results)
        if role == "system" and "action" in message.lower() and "result" in message.lower():
            # Check if this is a code execution result
            if "execute" in message.lower():
                # Try to extract the code output
                match = re.search(r'Result: (.*?)(?:Status:|$)', message, re.DOTALL)
                if match:
                    code_output = match.group(1).strip()
                    # Detect if this contains code
                    if code_output and (code_output.count('\n') > 0 or "=" in code_output or "def " in code_output or "import " in code_output):
                        # Detect language
                        language = self._detect_language(code_output)
                        lang_display = self.LANGUAGE_DISPLAY_NAMES.get(language, language.capitalize())
                        
                        # Display output in a special panel
                        output_panel = Panel(
                            Syntax(code_output, language, theme="monokai", word_wrap=True), 
                            title=f"📤 {lang_display} Output",
                            title_align="left",
                            border_style="green",
                            padding=(1, 2)
                        )
                        self.console.print(output_panel)
                        # Simplify the message to avoid duplication
                        processed_message = message.replace(code_output, f"[{lang_display} output displayed above]")

        # Regular message display with markdown
        panel = Panel(
            Markdown(processed_message),
            title=header,
            title_align="left",
            border_style=style,
            width=self.console.width - 8,
            box=rich.box.ROUNDED
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
        
        # Choose theme based on language
        theme = "monokai"  # Default
        if language in ['html', 'xml']:
            theme = "github-dark"
        elif language in ['bash', 'shell']:
            theme = "native"
        
        # Create a syntax highlighted version
        highlighted_code = Syntax(
            code.strip(), 
            language, 
            theme=theme, 
            line_numbers=True,
            word_wrap=True,
            code_width=min(100, self.console.width - 20)  # Limit width for better readability
        )
        
        # Create a panel for the code
        code_panel = Panel(
            highlighted_code,
            title=f"📋 {lang_display} Code",
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
        status_icon = "✓" if result.get("status") == "completed" else "❌"
        
        header = f"🔧 Command Result"
        content = f"{status_icon} {result.get('action', 'unknown')}\n\n{result.get('result', '')}"
        
        # Special handling for code execution results
        if result.get('action') == 'execute':
            # Get result text
            result_text = result.get('result', '')
            
            # Auto-detect language from the code
            language = self._detect_language(result_text)
            
            # Get language display name
            lang_display = self.LANGUAGE_DISPLAY_NAMES.get(language, language.capitalize())
            
            # Display code output separately
            output_panel = Panel(
                Syntax(result_text, language, theme="monokai"),
                title=f"📤 {lang_display} Output",
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
        """Handle progress updates without interfering with execution"""
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
 • /image or image: Include an image in your message
 • /help or help: Show this help message

Press Tab for command completion Use ↑↓ to navigate command history Press Ctrl+C to stop a running task"""

        self.display_message(welcome_message, "system")

        while True:
            try:
                # Clear any lingering progress bars before showing input
                self._ensure_progress_cleared()
                user_input = input(f"You [{self.message_count}]: ")

                if user_input.lower() in ["exit", "quit"]:
                    break

                if not user_input.strip():
                    continue

                # Handle commands
                if user_input.startswith("/"):
                    command_parts = user_input[1:].split(
                        " ", 2
                    )  # Split into max 3 parts
                    command = command_parts[0].lower()

                    # Handle /chat command
                    if command == "chat":
                        await self.handle_conversation_command(command_parts)
                        continue

                    # Handle /list command
                    if command == "list":
                        response = self.core.project_manager.process_list_command()
                        if isinstance(response, dict):
                            if "assistant_response" in response:
                                self.display_message(response["assistant_response"])
                            if "action_results" in response:
                                for result in response["action_results"]:
                                    if isinstance(result, dict) and "result" in result:
                                        self.display_message(result["result"], "output")
                        continue

                    # Handle /task commands
                    if command == "task" and len(command_parts) >= 2:
                        action = command_parts[1].lower()
                        name = (
                            command_parts[2].split(" ", 1)[0]
                            if len(command_parts) > 2
                            else ""
                        )
                        description = (
                            command_parts[2].split(" ", 1)[1]
                            if len(command_parts) > 2 and " " in command_parts[2]
                            else ""
                        )

                        try:
                            # Check both continuous mode states
                            is_continuous = (
                                getattr(self.core, "_continuous_mode", False)
                                or getattr(self.core.run_mode, "continuous_mode", False)
                                if hasattr(self.core, "run_mode")
                                else False
                            )
                            self.display_message(
                                f"[DEBUG] Continuous mode state: {is_continuous}",
                                "system",
                            )

                            if action == "create":
                                response = self.core.project_manager.create_task(
                                    name, description
                                )
                            elif action == "complete":
                                response = self.core.project_manager.complete_task(name)
                                self.display_message(
                                    f"[DEBUG] Task completion response: {response}",
                                    "system",
                                )

                                if response["status"] == "completed":
                                    self.display_message(response["result"], "system")
                                    if is_continuous:
                                        self.display_message(
                                            "[DEBUG] Continuous mode active, continuing",
                                            "system",
                                        )
                                        continue
                                    else:
                                        self.display_message(
                                            "[DEBUG] Task completed, no continuous mode",
                                            "system",
                                        )
                                else:
                                    self.display_message(
                                        f"Task completion error: {response['result']}",
                                        "error",
                                    )
                                    continue
                            elif action == "status":
                                response = self.core.project_manager.get_task_status(
                                    name
                                )
                            else:
                                self.display_message(
                                    f"Unknown task action: {action}", "error"
                                )
                                continue

                            if isinstance(response, dict):
                                if "result" in response:
                                    self.display_message(response["result"], "system")
                            continue
                        except Exception as e:
                            self.display_message(
                                f"[DEBUG] Task command error: {str(e)}", "error"
                            )
                            self.display_message(
                                f"[DEBUG] Traceback:\n{traceback.format_exc()}", "error"
                            )
                            continue

                    # Handle /project commands
                    if command == "project" and len(command_parts) >= 2:
                        action = command_parts[1].lower()
                        name = (
                            command_parts[2].split(" ", 1)[0]
                            if len(command_parts) > 2
                            else ""
                        )
                        description = (
                            command_parts[2].split(" ", 1)[1]
                            if len(command_parts) > 2 and " " in command_parts[2]
                            else ""
                        )

                        try:
                            if action == "create":
                                response = self.core.project_manager.create_project(
                                    name, description
                                )
                            elif action == "run":
                                # Verify project exists
                                if not self.core.project_manager.get_project(name):
                                    self.display_message(f"Project not found: {name}", "error")
                                    continue
                                # Start run mode for project
                                await self.core.start_run_mode(name, description, mode_type="project")
                            elif action == "status":
                                response = self.core.project_manager.get_project_status(
                                    name
                                )
                            else:
                                self.display_message(
                                    f"Unknown project action: {action}", "error"
                                )
                                self.display_message(
                                    "Available actions: create, run, status", "system"
                                )
                                continue

                            if isinstance(response, dict):
                                if "result" in response:
                                    self.display_message(response["result"], "system")
                            continue
                        except Exception as e:
                            self.display_message(
                                f"Error with project command: {str(e)}", "error"
                            )
                            continue

                    # Handle /image command
                    if command.startswith("image"):
                        image_path = (
                            input("Drag and drop your image here: ")
                            .strip()
                            .replace("'", "")
                        )
                        if not os.path.exists(image_path):
                            self.display_message(
                                f"Image file not found: {image_path}", "error"
                            )
                            continue

                        image_prompt = input("Description (optional): ")

                        # Process image with core
                        input_data = {"text": image_prompt, "image_path": image_path}

                        # Use process() instead of process_input + get_response to get multi-step processing
                        response = await self.core.process(input_data, max_iterations=5)

                        # Display response
                        if isinstance(response, dict):
                            if "assistant_response" in response:
                                self.display_message(response["assistant_response"])
                            if "action_results" in response:
                                for result in response["action_results"]:
                                    self.display_message(str(result), "system")
                        else:
                            self.display_message(str(response))

                        continue

                    # Handle /run command
                    if command == "run":
                        if len(command_parts) < 2:
                            self.display_message(
                                "Usage: /run <task_name> [description] [--247]\n"
                                "Examples:\n"
                                "  Run single task: /run setup-project\n"
                                "  Run 24/7 mode: /run --247\n"
                                "  Run with time limit: /run --247 --time 5\n"
                                "\nNote: --247 enables continuous operation mode",
                                "system",
                            )
                            continue

                        # Parse continuous mode flags
                        continuous = "--247" in command_parts
                        time_limit = None

                        try:
                            if "--time" in command_parts:
                                time_index = command_parts.index("--time")
                                if len(command_parts) > time_index + 1:
                                    time_limit = int(command_parts[time_index + 1])
                        except ValueError:
                            self.display_message(
                                "Invalid time limit format. Using default.", "error"
                            )

                        if continuous:
                            # Start continuous mode
                            run_mode = RunMode(self.core)
                            self.display_message(
                                "[DEBUG] Initializing 24/7 operation mode", "system"
                            )
                            self.display_message(
                                "[DEBUG] Time limit: " + str(time_limit)
                                if time_limit
                                else "None",
                                "system",
                            )
                            await run_mode.start_continuous()
                        else:
                            # Regular single task execution
                            name = command_parts[1]
                            description = (
                                " ".join(command_parts[2:])
                                if len(command_parts) > 2
                                else None
                            )
                            self.display_message(
                                f"[DEBUG] Starting task: {name}", "system"
                            )
                            await self.core.start_run_mode(name, description)
                        continue

                # Process regular input and get response
                # Initialize progress display for multi-step processing
                self.display_message("Processing your request...", "system")
                
                # Process the input with multi-step reasoning (max_iterations=5 by default)
                try:
                    response = await self.core.process({"text": user_input}, max_iterations=5)
                    
                    # Display response
                    if isinstance(response, dict):
                        if "assistant_response" in response:
                            self.display_message(response["assistant_response"])
                        if "action_results" in response:
                            for result in response["action_results"]:
                                # Use the new display method for action results
                                if isinstance(result, dict):
                                    self.display_action_result(result)
                                else:
                                    self.display_message(str(result), "system")
                    else:
                        self.display_message(str(response))
                except KeyboardInterrupt:
                    # Handle interrupt...
                    self.display_message("Processing interrupted by user", "system")
                    self._safely_stop_progress()
                    raise
                finally:
                    # Always clean up the progress display
                    self._safely_stop_progress()

                # Save conversation after each message exchange
                self.core.conversation_system.save()

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
            conversations = [
                ConversationSummary(
                    session_id=meta.session_id,
                    title=meta.title or f"Conversation {idx + 1}",
                    message_count=meta.message_count,
                    last_active=parse_iso_datetime(meta.last_active),
                )
                for idx, meta in enumerate(
                    self.core.conversation_system.loader.list_conversations()
                )
            ]
            session_id = self.conversation_menu.select_conversation(conversations)
            if session_id:
                try:
                    self.core.conversation_system.load(session_id)
                    self.display_message("Conversation loaded successfully", "system")
                except Exception as e:
                    self.display_message(
                        f"Error loading conversation: {str(e)}", "error"
                    )

        elif action == "load":
            # Same as list for now, might add direct session_id loading later
            await self.handle_conversation_command(["conv", "list"])

        elif action == "summary":
            messages = self.core.conversation_system.get_history()
            self.conversation_menu.display_summary(messages)

        elif action == "run":
            # During task execution
            await self.core.start_run_mode(
                command_parts[2], command_parts[3] if len(command_parts) > 3 else None
            )

            # After completion
            conversation = self.core.conversation_system.get_conversation(
                command_parts[2]
            )
            conversation.messages.extend(self.core.run_mode_messages)
            conversation.save()

        else:
            self.display_message(f"Unknown conversation action: {action}", "error")


@app.command()
def chat(
    model: str = typer.Option(None, "--model", "-m", help="Specify the model to use"),
    workspace: Path = typer.Option(
        None, "--workspace", "-w", help="Set custom workspace path"
    ),
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
        core = PenguinCore(api_client=api_client, tool_manager=tool_manager)
        core.set_system_prompt(SYSTEM_PROMPT)

        cli = PenguinCLI(core)
        await cli.chat_loop()

    try:
        asyncio.run(run())
    except Exception as e:
        console.print(f"[red]Fatal error: {str(e)}[/red]")
        raise typer.Exit(1)


if __name__ == "__main__":
    app()
