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
    if not response:
        print_bordered_message("I apologize, but I couldn't generate a response. Please try again.", PENGUIN_COLOR, "assistant", message_number)
        return

    content = ""
    if isinstance(response, dict):
        if "error" in response:
            print_bordered_message(response["error"], TOOL_COLOR, "system", message_number)
            return
        elif "tool_use" in response:
            tool_use = response["tool_use"]
            print_tool_output(tool_use["name"], tool_use["input"], tool_use["result"])
            return
        elif "choices" in response and len(response["choices"]) > 0:
            choice = response["choices"][0]
            if "message" in choice:
                content = choice["message"].get("content", "")
            elif "text" in choice:
                content = choice["text"]
            else:
                content = str(choice)
        else:
            content = str(response)
    elif isinstance(response, str):
        content = response
    elif isinstance(response, list):
        for item in response:
            if isinstance(item, dict) and 'type' in item and item['type'] == 'text':
                content += item.get('text', '')
            elif isinstance(item, str):
                content += item

    content = content.strip()
    if not content:
        print_bordered_message("I apologize, but I couldn't generate a meaningful response. Please try again.", PENGUIN_COLOR, "assistant", message_number)
        return

    if "Provider List:" in content:
        content = content.split("Provider List:", 1)[0].strip()

    print_bordered_message(content, PENGUIN_COLOR, "assistant", message_number)

    # Log the raw response for debugging
    logger.debug(f"Raw response: {response}")
    logger.debug(f"Processed content: {content}")

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