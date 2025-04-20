#!/usr/bin/env python3
import asyncio

from penguin.core import PenguinCore
from rich.console import Console  # type: ignore

console = Console()


async def example():
    try:
        # Initialize core without CLI
        console.print("[yellow]Initializing PenguinCore...[/yellow]")
        penguin = await PenguinCore.create()
        console.print("[green]PenguinCore Initialized.[/green]")

        # Define the task for run mode
        task_name = "create_and_run_js_file"
        task_description = (
            "Create a file named test123.js in the workspace directory. "
            "The file should contain code that simply prints 'Hello from test123.js!' to the console. "
            "After creating and saving the file, execute it using Node.js. "
            "Confirm execution was successful. "
            "Respond with your task completion phrase when the task is complete."
        )

        console.print(f"\\n[cyan]=== Starting Run Mode for Task: {task_name} ===[/cyan]")
        console.print(f"[dim]Description: {task_description}[/dim]")

        # Start run mode for the defined task
        # It will run until the task is marked complete by the AI or max iterations are hit
        await penguin.start_run_mode(
            name=task_name,
            description=task_description,
            continuous=True
        )

        console.print(f"\\n[cyan]=== Run Mode for Task: {task_name} Finished ===[/cyan]")

    except Exception as e:
        console.print(f"[red]Error during example execution: {str(e)}[/red]")
        # Optionally re-raise or log traceback
        # import traceback
        # console.print(traceback.format_exc())
        raise # Re-raise the exception to see the full traceback


if __name__ == "__main__":
    # It's good practice to handle potential exceptions from asyncio.run as well
    try:
        asyncio.run(example())
    except Exception as e:
        console.print(f"[bold red]Unhandled exception in main execution: {str(e)}[/bold red]")
