from prompt_toolkit import PromptSession
from prompt_toolkit.styles import Style
from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.history import FileHistory
from prompt_toolkit.auto_suggest import AutoSuggestFromHistory
from prompt_toolkit.completion import WordCompleter
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.syntax import Syntax
import os
import logging
from typing import Dict, Any
import re

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
        self.style = Style.from_dict({
            'prompt': f'fg:{self.USER_COLOR}',
            'command': 'fg:white bold',
        })
        
        # Command completion
        self.commands = WordCompleter([
            'exit', 'image', 'task', 'project', 'resume',
            'task create', 'task run', 'task list', 'task status',
            'project status', 'project list'
        ])
        
        # Initialize prompt session with history
        history_file = os.path.expanduser('~/.penguin_history')
        self.session = PromptSession(
            history=FileHistory(history_file),
            auto_suggest=AutoSuggestFromHistory(),
            completer=self.commands,
            style=self.style
        )

    def get_user_input(self, message_number: int) -> str:
        prompt_message = HTML(f'<prompt>👤 You (Message {message_number}): </prompt>')
        return self.session.prompt(prompt_message, style=self.style)

    def print_bordered_message(self, message: str, color: str, role: str, message_number: int):
        """Display a message in a bordered panel with proper formatting"""
        emoji_icon = self.PENGUIN_EMOJI if role in ["penguin", "assistant", "system"] else "👤"
        header = f"{emoji_icon} {role.capitalize()} ({message_number}):"
        
        # Convert message to string and clean it
        if isinstance(message, (dict, list)):
            message = str(message)
        message = str(message).strip()
        
        width = console.width - 4
        try:
            # Try markdown first
            panel = Panel(
                Markdown(message, code_theme="monokai"),
                title=header,
                title_align="left",
                border_style=color,
                expand=False,
                width=width
            )
            console.print(panel)
        except Exception as e:
            # Fallback to plain text
            console.print(f"[{color}]{header}[/]\n{message}")

    def print_code(self, code: str, language: str):
        width = console.width - 4
        syntax = Syntax(code, language, theme="monokai", line_numbers=True, word_wrap=True)
        console.print(Panel(syntax, expand=False, border_style=self.PENGUIN_COLOR, width=width))

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
        if isinstance(response, dict):
            # Extract the main response and action results
            main_response = response.get("assistant_response", "")
            action_results = response.get("action_results", [])
            
            # Extract and execute any code blocks from the response
            code_blocks = re.findall(r'```(\w+)?\n(.*?)```', main_response, re.DOTALL)
            
            # Display the main response without the code blocks and extra formatting
            clean_response = re.sub(r'```.*?```', '', main_response, flags=re.DOTALL).strip()
            clean_response = re.sub(r'┏.*?┓', '', clean_response, flags=re.DOTALL)
            clean_response = re.sub(r'┗.*?┛', '', clean_response, flags=re.DOTALL)
            clean_response = re.sub(r'%.*?\n', '', clean_response)
            
            if clean_response:
                self.print_bordered_message(clean_response, self.PENGUIN_COLOR, "assistant", "Response")
            
            # Display code blocks
            for lang, code in code_blocks:
                lang = lang.strip() if lang else 'plaintext'
                self.print_code(code.strip(), lang)
            
            # Display action results in a more readable format
            if action_results:
                results_text = ""
                seen_results = set()  # To track unique results
                
                for result in action_results:
                    result_value = result.get("result", "No result")
                    if result_value not in [None, 'None', '', *seen_results]:
                        results_text += f"{result_value}\n"
                        seen_results.add(result_value)
                
                if results_text:
                    self.print_bordered_message(
                        results_text.strip(), 
                        self.RESULT_COLOR, 
                        "output", 
                        "Result"
                    )
