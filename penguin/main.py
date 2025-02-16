#!/usr/bin/env python3
import asyncio
from core import PenguinCore
from rich.console import Console # type: ignore

console = Console()

async def main():
    try:
        # Initialize with CLI enabled
        penguin, cli = await PenguinCore.create(enable_cli=True)
        
        # Start CLI loop
        await cli.chat_loop()
        
    except Exception as e:
        console.print(f"[red]Error: {str(e)}[/red]")
        raise

if __name__ == "__main__":
    asyncio.run(main())