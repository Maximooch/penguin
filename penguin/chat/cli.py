import os
import typer # type: ignore
from typing import Optional
from pathlib import Path
import asyncio
from rich.console import Console # type: ignore
from rich.markdown import Markdown # type: ignore
from rich.panel import Panel # type: ignore
from core import PenguinCore

from config import config
from llm.model_config import ModelConfig
from llm.api_client import APIClient
from tools import ToolManager
from utils.log_error import log_error
from system_prompt import SYSTEM_PROMPT

app = typer.Typer(help="Penguin AI Assistant")
console = Console()

class PenguinCLI:
    # Color constants matching prompt_ui.py
    USER_COLOR = "cyan"
    PENGUIN_COLOR = "blue"
    TOOL_COLOR = "yellow"
    RESULT_COLOR = "green"
    PENGUIN_EMOJI = "🐧"

    def __init__(self, core):
        self.core = core
        self.message_count = 0
        self.console = Console()

    def display_message(self, message: str, role: str = "assistant"):
        """Display a message with proper formatting"""
        styles = {
            "assistant": self.PENGUIN_COLOR,
            "user": self.USER_COLOR,
            "system": self.TOOL_COLOR,
            "error": "red bold",
            "output": self.RESULT_COLOR
        }
        
        emojis = {
            "assistant": self.PENGUIN_EMOJI,
            "user": "👤",
            "system": "🐧",
            "error": "⚠️"
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
            width=self.console.width - 4
        )
        self.console.print(panel)

    async def chat_loop(self):
        """Main chat loop"""
        welcome_message = """Welcome to the Penguin AI Assistant!

Available Commands:
 • /task or task: Task management commands
   - list: View all tasks
   - create [name] [description]: Create a new task
   - run [name]: Run a task
   - status [name]: Check task status
   
 • /project or project: Project management commands
   - list: View all projects
   - create [name] [description]: Create a new project
   - run [name]: Run a project
   - status [name]: Check project status
   
 • /exit or exit: End the conversation
 • /image or image: Include an image in your message
 • /help or help: Show this help message
 
Press Tab for command completion
Use ↑↓ to navigate command history
Press Ctrl+C to stop a running task

Press Tab for command completion Use ↑↓ to navigate command history Press Ctrl+C to stop a running task"""

        self.display_message(welcome_message, "system")
        
        while True:
            try:
                user_input = input(f"You [{self.message_count}]: ")
                
                if user_input.lower() in ['exit', 'quit']:
                    break

                if not user_input.strip():
                    continue
                    
                # Handle /image command
                if user_input.lower().startswith('/image'):
                    image_path = input("Drag and drop your image here: ").strip().replace("'", "")
                    if not os.path.exists(image_path):
                        self.display_message(f"Image file not found: {image_path}", "error")
                        continue
                        
                    image_prompt = input("Description (optional): ")
                    
                    # Process image with core
                    input_data = {
                        "text": image_prompt,
                        "image_path": image_path
                    }
                    
                    await self.core.process_input(input_data)
                    response, _ = await self.core.get_response()
                    
                    # Display response
                    if isinstance(response, dict):
                        if 'assistant_response' in response:
                            self.display_message(response['assistant_response'])
                        if 'action_results' in response:
                            for result in response['action_results']:
                                self.display_message(str(result), "system")
                    else:
                        self.display_message(str(response))
                    
                    continue

                # Process input and get response
                await self.core.process_input({"text": user_input})
                response, _ = await self.core.get_response()
                
                # Display response
                if isinstance(response, dict):
                    if 'assistant_response' in response:
                        self.display_message(response['assistant_response'])
                    if 'action_results' in response:
                        for result in response['action_results']:
                            self.display_message(str(result), "system")
                else:
                    self.display_message(str(response))
                
                self.message_count += 1

            except KeyboardInterrupt:
                break
            except Exception as e:
                console.print(f"[red]Error: {str(e)}[/red]")

        console.print("\nGoodbye! 👋")

@app.command()
def chat(
    model: str = typer.Option(None, "--model", "-m", help="Specify the model to use"),
    workspace: Path = typer.Option(None, "--workspace", "-w", help="Set custom workspace path")
):
    """Start an interactive chat session with Penguin"""
    async def run():
        # Initialize core components
        model_config = ModelConfig(
            model=model or config['model']['default'],
            provider=config['model']['provider'],
            api_base=config['api']['base_url']
        )
        
        api_client = APIClient(model_config=model_config)
        api_client.set_system_prompt(SYSTEM_PROMPT)
        tool_manager = ToolManager(log_error)
        
        # Create core and CLI
        core = PenguinCore(
            api_client=api_client,
            tool_manager=tool_manager
        )
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