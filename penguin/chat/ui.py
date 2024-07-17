from colorama import Fore, Style
from pygments import highlight
from pygments.lexers import get_lexer_by_name
from pygments.formatters import TerminalFormatter
import pygments.util

from rich.console import Console
from rich.markdown import Markdown
from rich.syntax import Syntax
from rich.panel import Panel
from rich.text import Text

# Color constants
USER_COLOR = "cyan"
PENGUIN_COLOR = "blue"
TOOL_COLOR = "yellow"
RESULT_COLOR = "green"
PENGUIN_EMOJI = "🐧"

console = Console()

def print_bordered_message(message, color, role, message_number):
    emoji = PENGUIN_EMOJI if role in ["assistant", "system"] else "👤"
    header = f"{emoji} {role.capitalize()} (Message {message_number}):"
    panel = Panel(
        Markdown(message),
        title=header,
        title_align="left",
        border_style=color,
        expand=False
    )
    console.print(panel)

def print_code(code, language):
    try:
        syntax = Syntax(code, language, theme="monokai", line_numbers=True)
        console.print(Panel(syntax, expand=False, border_style=PENGUIN_COLOR))
    except pygments.util.ClassNotFound:
        print_bordered_message(f"Code (language: {language}):\n{code}", PENGUIN_COLOR, "assistant", "N/A")

def process_and_display_response(response, message_number):
    if response.startswith("Error") or response.startswith("I'm sorry"):
        print_bordered_message(response, TOOL_COLOR, "system", message_number)
    else:
        if "```" in response:
            parts = response.split("```")
            for i, part in enumerate(parts):
                if i % 2 == 0:
                    if part.strip():
                        print_bordered_message(part, PENGUIN_COLOR, "assistant", message_number)
                else:
                    lines = part.split('\n')
                    language = lines[0].strip() if lines else ""
                    code = '\n'.join(lines[1:]) if len(lines) > 1 else ""
                    
                    if language and code:
                        print_code(code, language)
                    elif code:
                        print_bordered_message(f"Code:\n{code}", PENGUIN_COLOR, "assistant", message_number)
                    else:
                        print_bordered_message(part, PENGUIN_COLOR, "assistant", message_number)
        else:
            print_bordered_message(response, PENGUIN_COLOR, "assistant", message_number)

def print_welcome_message():
    welcome_text = (
        "Welcome to the Penguin AI Assistant!\n"
        "Type 'exit' to end the conversation.\n"
        "Type 'image' to include an image in your message.\n"
        "Type 'automode [number]' to enter Autonomous mode with a specific number of iterations.\n"
        "While in automode, press Ctrl+C at any time to exit the automode to return to regular chat."
    )
    print_bordered_message(welcome_text, PENGUIN_COLOR, "system", "Welcome")

def get_user_input(message_number):
    return console.input(f"[{USER_COLOR}]👤 You (Message {message_number}):[/] ")

def get_image_path():
    return console.input(f"[{USER_COLOR}]👤 Drag and drop your image here:[/] ").strip().replace("'", "")

def get_image_prompt():
    return console.input(f"[{USER_COLOR}]👤 You (prompt for image):[/] ")