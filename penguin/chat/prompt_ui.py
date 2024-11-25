from prompt_toolkit import PromptSession  # type: ignore
# from prompt_toolkit.patch_stdout import patch_stdout  # type: ignore
from prompt_toolkit.styles import Style  # type: ignore
from prompt_toolkit.formatted_text import HTML  # type: ignore
from prompt_toolkit.history import FileHistory  # type: ignore
from rich.console import Console  # type: ignore
from rich.markdown import Markdown  # type: ignore
from rich.panel import Panel  # type: ignore
from rich.syntax import Syntax  # type: ignore
import os
import logging
from typing import Dict, Any, List
import re
import asyncio

logger = logging.getLogger(__name__)
console = Console()

class PromptUI:
    # Color constants
    USER_COLOR = "cyan"
    PENGUIN_COLOR = "blue"
    TOOL_COLOR = "yellow"
    RESULT_COLOR = "green"
    PENGUIN_EMOJI = "🐧"

    def __init__(self):
        history_file = os.path.expanduser('~/.penguin_history')
        self.session = PromptSession(history=FileHistory(history_file))
        self.style = self._create_style()
        self.console = Console()

    def _create_style(self):
        return Style.from_dict({
            'prompt': '#0000ff',  # Blue
            'penguin': '#0000ff bold',
        })

    async def get_user_input(self, message_count: int) -> str:
        try:
            user_input = await self.session.prompt_async(
                HTML(f"<penguin>You [{message_count}]:</penguin> "),
                style=self.style
            )
            return user_input.strip()
        except (EOFError, KeyboardInterrupt):
            return "exit"

    def print_bordered_message(self, message: str, color: str, role: str, message_type: str | int):
        """Display a message in a bordered panel with proper formatting"""
        emoji_icon = self.PENGUIN_EMOJI if role in ["penguin", "assistant", "system"] else "👤"
        # Convert assistant role to Penguin in the header
        display_role = "Penguin" if role == "assistant" else role.capitalize()
        header = f"{emoji_icon} {display_role} ({message_type}):"
        
        # Convert message to string and clean it
        if isinstance(message, (dict, list)):
            message = str(message)
        message = str(message).strip()
        
        try:
            # Try markdown first
            panel = Panel(
                Markdown(message, code_theme="monokai"),
                title=header,
                title_align="left",
                border_style=color,
                expand=False,
                width=self.console.width - 4
            )
            self.console.print(panel)
        except Exception as e:
            # Fallback to plain text
            self.console.print(Panel(
                message, 
                title=header,
                title_align="left",
                border_style=color, 
                width=self.console.width - 4
            ))

    def print_code(self, code: str, language: str):
        width = self.console.width - 4
        syntax = Syntax(code, language, theme="monokai", line_numbers=True, word_wrap=True)
        self.console.print(Panel(syntax, expand=False, border_style=self.PENGUIN_COLOR, width=width))

    def print_welcome_message(self):
        welcome_text = (
            "Welcome to the Penguin AI Assistant!\n\n"
            "Available Commands:\n"
            "- exit: End the conversation\n"
            "- image: Include an image in your message\n"
            "- task create [name] [description]: Create a new task\n"
            "- task run [name]: Run a task\n"
            "- task list: View all tasks\n"
            "- task status [name]: Check task status\n"
            "- project list: View all projects\n"
            "- project status [name]: Check project status\n"
            "- resume: Resume previous conversation\n\n"
            "Press Tab for command completion\n"
            "Use ↑↓ to navigate command history\n"
            "Press Ctrl+C to stop a running task"
        )
        self.print_bordered_message(welcome_text, self.PENGUIN_COLOR, "system", "Welcome")

    def get_image_path(self) -> str:
        prompt_message = HTML('<prompt>👤 Drag and drop your image here: </prompt>')
        return self.session.prompt(prompt_message, style=self.style).strip().replace("'", "")

    def get_image_prompt(self) -> str:
        prompt_message = HTML('<prompt>👤 You (prompt for image): </prompt>')
        return self.session.prompt(prompt_message, style=self.style)

    def process_and_display_response(self, response: Dict[str, Any]):
        """Process and display the AI response with proper formatting"""
        if not isinstance(response, dict):
            response = {"assistant_response": str(response), "action_results": []}
            
        main_response = response.get("assistant_response", "")
        action_results = response.get("action_results", [])
        
        # Handle main response
        if main_response:
            # Extract code blocks first
            code_blocks = re.findall(r'```(\w+)?\n(.*?)```', main_response, re.DOTALL)
            
            # Clean the response text
            clean_response = re.sub(r'```.*?```', '', main_response, flags=re.DOTALL).strip()
            clean_response = re.sub(r'┏.*?┓|┗.*?┛|%.*?\n', '', clean_response, flags=re.DOTALL)
            
            if clean_response:
                self.print_bordered_message(clean_response, self.PENGUIN_COLOR, "assistant", "Response")
            
            # Display code blocks
            for lang, code in code_blocks:
                if code:  # Only process if there's actual code
                    lang = lang.strip() if lang else 'plaintext'
                    self.print_code(code.strip(), lang)
        
        # Handle action results
        if action_results:
            self._display_action_results(action_results)

    def _display_action_results(self, results: List[Dict[str, Any]]):
        results_text = []
        for result in results:
            if not isinstance(result, dict):
                continue
                
            status = result.get("status", "unknown")
            action = result.get("action", "Unknown Action")
            value = result.get("result", "No result")
            
            if status == "interrupted":
                results_text.append(f"⚠️ {action}: {value}")
            elif status == "error":
                results_text.append(f"❌ {action}: {value}")
            elif status == "completed":
                results_text.append(f"✅ {action}: {value}")
                
        if results_text:
            self.print_bordered_message(
                "\n".join(results_text),
                self.RESULT_COLOR,
                "output",
                "Action Results"
            )