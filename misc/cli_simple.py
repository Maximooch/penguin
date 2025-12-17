"""
Simplified CLI for Penguin - Single UI System Approach

This replaces the complex cli.py with a minimal implementation that:
1. Uses ONLY CLIRenderer for all display
2. Has NO duplicate event handling
3. Has NO streaming logic (CLIRenderer handles it)
4. Focuses on input handling and command routing

Target: ~400 lines vs 2936 lines in cli.py
"""

import asyncio
import sys
from typing import Optional
from pathlib import Path

from rich.console import Console
from rich.live import Live
from rich.prompt import Prompt
from rich.panel import Panel
from rich.text import Text

from penguin.core import PenguinCore
from penguin.cli.ui import CLIRenderer
from penguin.cli.interface import PenguinInterface


class SimplePenguinCLI:
    """Minimal CLI that delegates all display to CLIRenderer"""
    
    def __init__(self, core: PenguinCore):
        self.core = core
        self.console = Console()
        self.interface = PenguinInterface(core)
        
        # Single UI system - CLIRenderer handles ALL display
        self.renderer = CLIRenderer(self.console, core)
        self.renderer.initialize()
        
        # Live display managed by renderer
        self.live = Live(
            self.renderer.get_display_renderable(),
            console=self.console,
            refresh_per_second=4,
            vertical_overflow="visible",
            auto_refresh=True
        )
        self.renderer.set_live_display(self.live)
        
        self._running = False

    async def start(self):
        """Start the CLI"""
        self.console.print("🐧 Penguin CLI (Simplified)")
        self.console.print("Type your message or /help for commands")
        self.console.print("Press Ctrl+C to exit\n")
        
        self._running = True
        
        with self.live:
            await self._main_loop()

    async def _main_loop(self):
        """Main processing loop that gets input and processes messages"""
        while self._running:
            try:
                # Stop live display temporarily for input
                self.live.stop()
                
                try:
                    # Get user input
                    user_input = input("You: ")
                    if user_input.strip():
                        # Handle commands vs regular messages
                        if user_input.startswith("/"):
                            await self._handle_command(user_input[1:])
                        else:
                            await self._handle_message(user_input)
                except EOFError:
                    break
                finally:
                    # Always restart live display
                    self.live.start()
                    
            except KeyboardInterrupt:
                self.console.print("\n👋 Goodbye!")
                break
            except Exception as e:
                self.console.print(f"Error: {e}")

    async def _handle_message(self, message: str):
        """Handle regular chat messages"""
        try:
            # Process through interface - NO stream callback needed
            # CLIRenderer gets updates via Core events
            await self.interface.process_input({"text": message})
            
        except Exception as e:
            self.console.print(f"Error processing message: {e}")

    async def _handle_command(self, command: str):
        """Handle slash commands"""
        try:
            parts = command.split(" ", 1)
            cmd = parts[0].lower()
            args = parts[1] if len(parts) > 1 else ""
            
            if cmd == "help":
                self._show_help()
            elif cmd == "exit" or cmd == "quit":
                self._running = False
            elif cmd == "clear":
                self.renderer.reset_response_area()
            else:
                # Delegate to interface
                result = await self.interface.handle_command(command)
                if result.get("error"):
                    self.console.print(f"Error: {result['error']}")
                elif result.get("status"):
                    self.console.print(result["status"])
                    
        except Exception as e:
            self.console.print(f"Error handling command: {e}")

    def _show_help(self):
        """Show help message"""
        help_text = """
Available Commands:
/help - Show this help
/exit - Exit the CLI
/clear - Clear the display
/models - Select a model
/tokens - Show token usage
/run <task> - Start run mode
/chat list - List conversations
/context list - List context files

Just type a message to chat with Penguin!
        """
        self.console.print(help_text)


async def main():
    """Main entry point"""
    try:
        # Create core instance
        core = await PenguinCore.create(show_progress=True)
        
        # Start simplified CLI
        cli = SimplePenguinCLI(core)
        await cli.start()
        
    except KeyboardInterrupt:
        print("\n👋 Goodbye!")
    except Exception as e:
        print(f"Failed to start CLI: {e}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main()) 