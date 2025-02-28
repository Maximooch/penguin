import asyncio
import datetime
import os
import traceback
from pathlib import Path
from typing import List, Optional, Callable, Dict, Any

import typer  # type: ignore
from rich.console import Console  # type: ignore
from rich.markdown import Markdown  # type: ignore
from rich.panel import Panel  # type: ignore
from rich.progress import Progress, SpinnerColumn, TextColumn  # type: ignore

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
    PENGUIN_EMOJI = "🐧"

    def __init__(self, core):
        self.core = core
        self.in_247_mode = False
        self.message_count = 0
        self.console = Console()
        self.conversation_menu = ConversationMenu(self.console)
        self.core.register_progress_callback(self.on_progress_update)
        self.progress = None

    def display_message(self, message: str, role: str = "assistant"):
        """Display a message with proper formatting"""
        styles = {
            "assistant": self.PENGUIN_COLOR,
            "user": self.USER_COLOR,
            "system": self.TOOL_COLOR,
            "error": "red bold",
            "output": self.RESULT_COLOR,
        }

        emojis = {
            "assistant": self.PENGUIN_EMOJI,
            "user": "👤",
            "system": "🐧",
            "error": "⚠️",
        }

        style = styles.get(role, "white")
        emoji = emojis.get(role, "💬")

        # Special handling for welcome message
        if role == "system" and "Welcome to the Penguin AI Assistant!" in message:
            header = f"{emoji} System (Welcome):"
        else:
            display_role = "Penguin" if role == "assistant" else role.capitalize()
            header = f"{emoji} {display_role}"

        panel = Panel(
            Markdown(message),
            title=header,
            title_align="left",
            border_style=style,
            width=self.console.width - 4,
        )
        self.console.print(panel)

    def on_progress_update(self, iteration: int, max_iterations: int, message: Optional[str] = None):
        """Handle progress updates from the core during multi-step processing"""
        if self.progress is None:
            self.progress = Progress(
                SpinnerColumn(),
                TextColumn("[bold blue]{task.description}"),
                console=self.console
            )
            self.progress.start()
            self.progress_task = self.progress.add_task(
                f"Thinking... (Step {iteration}/{max_iterations})", total=max_iterations
            )
        else:
            self.progress.update(
                self.progress_task, 
                description=f"{message or 'Thinking...'} (Step {iteration}/{max_iterations})",
                completed=iteration
            )
            
            # If processing is complete, finish the progress bar
            if iteration >= max_iterations or message and "Finalizing" in message:
                self.progress.update(self.progress_task, completed=max_iterations)
                self.progress.stop()
                self.progress = None

    async def chat_loop(self):
        """Main chat loop"""
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
                                self.display_message(str(result), "system")
                    else:
                        self.display_message(str(response))
                except KeyboardInterrupt:
                    # Clean up progress display if interrupted
                    if self.progress:
                        self.progress.stop()
                        self.progress = None
                    raise
                except Exception as e:
                    # Clean up progress display on error
                    if self.progress:
                        self.progress.stop()
                        self.progress = None
                    self.display_message(f"Error processing your request: {str(e)}", "error")

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
