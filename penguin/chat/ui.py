import re
from textwrap import wrap
from colorama import Fore, Style # type: ignore
from pygments import highlight # type: ignore
from pygments.lexers import get_lexer_by_name # type: ignore
from pygments.formatters import TerminalFormatter # type: ignore
import pygments.util # type: ignore

from rich.console import Console # type: ignore
from rich.markdown import Markdown # type: ignore
from rich.syntax import Syntax # type: ignore
from rich.panel import Panel # type: ignore
from rich.text import Text # type: ignore
import logging

# Color constants
USER_COLOR = "cyan"
PENGUIN_COLOR = "blue"
TOOL_COLOR = "yellow"
RESULT_COLOR = "green"
PENGUIN_EMOJI = "🐧"  # Keep this for systems that support it

console = Console()
logger = logging.getLogger(__name__)

def print_bordered_message(message, color, role, message_number, message_type="default"):
    emoji_icon = PENGUIN_EMOJI if role in ["assistant", "system"] else "👤"
    header = f"{emoji_icon} {role.capitalize()} ({message_type.capitalize()} {message_number}):"
    width = console.width - 4  # Subtract 4 for panel borders
    panel = Panel(
        Markdown(message, code_theme="monokai"),
        title=header,
        title_align="left",
        border_style=color,
        expand=False,
        width=width
    )
    console.print(panel)

def print_code(code, language):
    try:
        width = console.width - 4  # Subtract 4 for panel borders
        syntax = Syntax(code, language, theme="monokai", line_numbers=True, word_wrap=True)
        console.print(Panel(syntax, expand=False, border_style=PENGUIN_COLOR, width=width))
    except pygments.util.ClassNotFound:
        print_bordered_message(f"Code (language: {language}):\n{code}", PENGUIN_COLOR, "assistant", "N/A")

def print_tool_output(tool_name, tool_input, tool_result):
    width = console.width - 4  # Subtract 4 for panel borders
    content = Text.assemble(
        ("Tool Used: ", "bold"),
        (f"{tool_name}\n", "yellow"),
        ("Tool Input: ", "bold"),
        (f"{tool_input}\n", "cyan"),
        ("Tool Result: ", "bold"),
        (f"{tool_result}", "green")
    )
    content = Text(content)
    content.wrap(width - 2)  # Subtract 2 for inner padding
    tool_panel = Panel(
        content,
        border_style="yellow",
        expand=False,
        width=width
    )
    console.print(tool_panel)

def process_and_display_response(response, message_number):
    if isinstance(response, str):
        if response.startswith("Tool Used:"):
            # This is a tool use response
            parts = response.split('\n', 2)
            if len(parts) == 3:
                tool_name = parts[0].split(': ', 1)[1]
                tool_input = parts[1].split(': ', 1)[1]
                tool_result = parts[2].split(': ', 1)[1]
                print_tool_output(tool_name, tool_input, tool_result)
            else:
                print_bordered_message(response, TOOL_COLOR, "system", message_number)
        else:
            # Format the response as markdown
            markdown_response = f"```markdown\n{response}\n```"
            print_bordered_message(markdown_response, PENGUIN_COLOR, "assistant", message_number)
    elif isinstance(response, dict):
        if "error" in response:
            print_bordered_message(response["error"], TOOL_COLOR, "system", message_number)
        elif "tool_use" in response:
            tool_use = response["tool_use"]
            print_tool_output(tool_use["name"], tool_use["input"], tool_use["result"])
        else:
            # Format the response as markdown
            markdown_response = f"```markdown\n{str(response)}\n```"
            print_bordered_message(markdown_response, PENGUIN_COLOR, "assistant", message_number)
    else:
        print_bordered_message(f"Unexpected response format: {type(response)}", TOOL_COLOR, "system", message_number)

    # Additional logging for debugging
    logger.debug(f"Response type: {type(response)}")
    logger.debug(f"Response content: {response}")

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