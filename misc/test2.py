#!/usr/bin/env python3
import asyncio

from penguin.core import PenguinCore
from rich.console import Console  # type: ignore

console = Console()


async def example():
    try:
        # Initialize core without CLI
        penguin = await PenguinCore.create()

        # Process messages
        console.print("\n=== Testing Basic Interaction ===")
        response = await penguin.process("Hello! This is just a test, could you repeat 'Hello there Maximus!' back to me?")
        console.print(response)

        # console.print("\n=== Testing file creation ===")
        # # response = await penguin.process("Create a new project called 'test_project'")
        # response = await penguin.process(
        #     "Create a file named test1.js in the workspace directory. It will print hello world. Execute it after creating/saving the file"
        # )
        # console.print(response)

    except Exception as e:
        console.print(f"[red]Error: {str(e)}[/red]")
        raise


if __name__ == "__main__":
    asyncio.run(example())
