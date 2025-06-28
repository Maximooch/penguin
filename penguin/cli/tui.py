from __future__ import annotations
import asyncio
import logging
import traceback
from typing import Any, Dict
from textual.app import App, ComposeResult
from textual.containers import Container
from textual.widgets import Header, Footer, Input, RichLog, Static
from textual.reactive import reactive
from rich.panel import Panel
from rich.text import Text
from rich.console import Group
from rich.markdown import Markdown
from rich.syntax import Syntax
import os
import signal
import shlex

from penguin.core import PenguinCore
from penguin.cli.interface import PenguinInterface

# Set up logging for debug purposes
logger = logging.getLogger(__name__)

class PenguinTextualApp(App):
    """A Textual-based chat interface for Penguin AI."""
    
    CSS_PATH = "tui.css"
    
    # Add key bindings
    BINDINGS = [
        ("ctrl+c", "quit", "Quit"),
        ("ctrl+q", "quit", "Quit"),
        ("ctrl+l", "clear_log", "Clear"),
        ("ctrl+d", "show_debug", "Debug"),
    ]
    
    status_text = reactive("Initializing...")
    
    def __init__(self):
        super().__init__()
        self.core = None
        self.interface = None
        self.log_widget = None
        self.debug_messages = []  # Store debug messages for later viewing
        self.streaming_content = ""  # Accumulate streaming content
        self.is_streaming = False
        self.current_assistant_message = ""  # Track current assistant message for streaming
        self.last_final_content = "" # Prevent duplicate final message rendering

    def compose(self) -> ComposeResult:
        """Create child widgets for the app."""
        yield Header()
        with Container(id="main-container"):
            yield RichLog(id="log", markup=True, highlight=True, wrap=True)
            yield Static(id="streaming-output", classes="hidden")  # For streaming
            yield Input(placeholder="Type your message... (Ctrl+L=clear, Ctrl+D=debug, Ctrl+C=quit)", id="input-box")
        yield Static(id="status-bar")  # Create widget without initial text
        yield Footer()

    async def on_mount(self) -> None:
        """Called when the app is mounted."""
        self.log_widget = self.query_one(RichLog)

        # Now that widgets are mounted, set the initial status text
        self.query_one("#status-bar", Static).update(self.status_text)
        
        self.query_one(Input).focus()
        asyncio.create_task(self.initialize_core())

    async def initialize_core(self) -> None:
        """Initialize the PenguinCore and interface."""
        try:
            self.status_text = "Initializing Penguin Core..."
            
            # Use fast startup and disable progress bars to speed up initialization
            self.core = await PenguinCore.create(
                fast_startup=True,
                show_progress=False  # Disable progress bars in TUI mode
            )
            
            self.status_text = "Setting up interface..."
            
            # Register our event handler with the core FIRST
            self.core.register_ui(self.handle_core_event)
            self.debug_messages.append("Registered UI event handler with core")
            
            # Then create the interface
            self.interface = PenguinInterface(self.core)
            
            self.status_text = "Ready"
            self.log_widget.write(Panel("🐧 [bold cyan]Penguin AI[/bold cyan] is ready!", title="Welcome", border_style="cyan"))
            
            # Add helpful information about browser tools
            browser_info = Group(
                Text("💡 Browser Tools Info:", style="bold yellow"),
                Text("• Regular browser tools are temporarily disabled", style="dim"),
                Text("• Use PyDoll browser tools instead:", style="dim"),
                Text("  - Ask me to navigate: 'Go to https://example.com'", style="green"),
                Text("  - Ask for screenshots: 'Take a screenshot of the page'", style="green"),
                Text("  - Ask to interact: 'Click the login button'", style="green"),
                Text("• Type /help for more commands", style="dim")
            )
            self.log_widget.write(browser_info)
            self.log_widget.write("")  # Add spacing
            
        except Exception as e:
            self.status_text = f"Error initializing core: {e}"
            self.log_widget.write(Panel(f"[bold red]Fatal Error[/bold red]\n{e}", title="Initialization Failed", border_style="red"))
            # Log the full traceback for debugging
            error_details = traceback.format_exc()
            logger.error(f"TUI initialization error: {error_details}")
            self.debug_messages.append(f"Initialization Error: {error_details}")

    def watch_status_text(self, status: str) -> None:
        """Update the status bar when status_text changes."""
        try:
            # Only update if the app is fully mounted
            if hasattr(self, '_mounted') and self._mounted:
                status_bar = self.query_one("#status-bar", Static)
                status_bar.update(f"[dim]{status}[/dim]")
        except Exception:
            # Ignore errors during app initialization
            pass

    async def handle_core_event(self, event_type: str, data: Any) -> None:
        """Handle events from PenguinCore."""
        try:
            self.debug_messages.append(f"Received event: {event_type} with data keys: {list(data.keys()) if isinstance(data, dict) else 'not dict'}")
            
            if event_type == "message":
                role = data.get("role", "unknown")
                content = data.get("content", "")
                
                if role == "user":
                    self.log_widget.write(f"[bold cyan]You:[/bold cyan]\n{content}")
                elif role == "assistant":
                    # Don't render a non-streaming message if it's identical to the one
                    # we just finalized from a stream.
                    if content != self.last_final_content:
                        self.log_widget.write(
                            Group(
                                Text("🐧 Penguin:", style="bold green"),
                                Markdown(content, style="green")
                            )
                        )
                    self.last_final_content = "" # Reset after use
            
            elif event_type == "stream_chunk":
                chunk = data.get("chunk", "")
                is_final = data.get("is_final", False)
                streaming_widget = self.query_one("#streaming-output", Static)

                if not self.is_streaming and chunk:
                    # First chunk of a new stream
                    self.is_streaming = True
                    self.current_assistant_message = chunk
                    streaming_widget.remove_class("hidden")
                elif self.is_streaming and not is_final:
                    # Subsequent chunk
                    self.current_assistant_message += chunk
                
                if self.is_streaming and not is_final:
                    # Update the streaming widget with accumulated content
                    try:
                        markdown_content = Markdown(self.current_assistant_message)
                        group = Group(Text("🐧 Penguin (streaming):", style="bold green"), markdown_content)
                        streaming_widget.update(group)
                    except Exception as e:
                        streaming_widget.update(f"[bold green]🐧 Penguin (streaming):[/bold green] {self.current_assistant_message}\nError: {e}")

                elif is_final:
                    # Finalize the message
                    if self.is_streaming:
                        streaming_widget.add_class("hidden")
                        streaming_widget.update("")
                        
                        final_content = data.get("content", self.current_assistant_message)
                        # Store the content to prevent the subsequent `message` event from re-rendering it
                        self.last_final_content = final_content 
                        
                        self.log_widget.write(
                             Group(
                                Text("🐧 Penguin:", style="bold green"),
                                Markdown(final_content, style="green")
                            )
                        )

                    # Reset state
                    self.is_streaming = False
                    self.current_assistant_message = ""
            
            elif event_type == "tool_call":
                tool_name = data.get("name", "unknown")
                self.log_widget.write(f"[yellow]🔧 Using tool: {tool_name}[/yellow]")
            
            elif event_type == "tool_result":
                result = data.get("result", "")
                action_name = data.get("action_name", "unknown")
                status = data.get("status", "completed")
                
                # Handle different types of tool results
                if status == "error":
                    self.log_widget.write(f"[red]❌ Tool '{action_name}' failed:[/red]\n[red]{result[:500]}{'...' if len(result) > 500 else ''}[/red]\n")
                elif action_name in ["execute_code", "run_code", "python_exec"]:
                    # Special handling for code execution
                    if result.strip():
                        self.log_widget.write(Group(
                            Text(f"📋 Code output:", style="bold blue"),
                            Syntax(result[:1000] + ("..." if len(result) > 1000 else ""), "text", theme="monokai", line_numbers=False)
                        ))
                        self.log_widget.write("")  # Add spacing
                    else:
                        self.log_widget.write(f"[blue]✅ Code executed successfully (no output)[/blue]\n")
                elif action_name in ["execute_command", "shell_command"]:
                    # Special handling for shell commands
                    if result.strip():
                        self.log_widget.write(Group(
                            Text(f"🖥️  Command output:", style="bold magenta"),
                            Syntax(result[:1000] + ("..." if len(result) > 1000 else ""), "bash", theme="monokai", line_numbers=False)
                        ))
                        self.log_widget.write("")  # Add spacing
                    else:
                        self.log_widget.write(f"[magenta]✅ Command executed successfully (no output)[/magenta]\n")
                elif action_name in ["browser_navigate", "pydoll_browser_navigate"]:
                    # Browser navigation
                    self.log_widget.write(f"[cyan]🌐 {result}[/cyan]\n")
                elif action_name in ["browser_screenshot", "pydoll_browser_screenshot"]:
                    # Screenshot results
                    self.log_widget.write(f"[green]📸 {result}[/green]\n")
                elif action_name in ["memory_search", "workspace_search"]:
                    # Search results with better formatting
                    if result.strip():
                        self.log_widget.write(Group(
                            Text(f"🔍 Search results:", style="bold yellow"),
                            Text(result[:800] + ("..." if len(result) > 800 else ""), style="dim white")
                        ))
                        self.log_widget.write("")  # Add spacing
                    else:
                        self.log_widget.write(f"[yellow]🔍 No search results found[/yellow]\n")
                else:
                    # Regular tool result with improved formatting
                    if len(result) > 300:
                        preview = result[:300] + "..."
                    else:
                        preview = result
                    
                    if preview.strip():
                        self.log_widget.write(f"[dim]🔧 {action_name}:[/dim]\n[white]{preview}[/white]\n")
                    else:
                        self.log_widget.write(f"[dim]🔧 {action_name}: ✅ completed[/dim]\n")
            
            elif event_type == "error":
                error_msg = data.get("message", "Unknown error")
                self.log_widget.write(Panel(f"[bold red]Error:[/bold red] {error_msg}", border_style="red"))
                self.debug_messages.append(f"Core Event Error: {error_msg}")
                
        except Exception as e:
            error_msg = f"Error handling core event {event_type}: {e}"
            logger.error(error_msg, exc_info=True)
            self.debug_messages.append(f"Event Handler Error ({event_type}): {e}")
            # Don't let event handling errors crash the UI
            try:
                self.log_widget.write(f"[red]Event handling error: {error_msg}[/red]")
            except:
                pass  # If even logging fails, just continue

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        """Handle user input submission."""
        if not self.interface:
            self.log_widget.write("[red]Core not initialized yet. Please wait.[/red]")
            return
        
        user_input = event.value.strip()
        if not user_input:
            return
        
        # Clear the input
        event.input.value = ""
        
        # Handle commands
        if user_input.startswith("/"):
            command_str = user_input[1:]
            # Use shlex to handle quoted arguments in commands
            try:
                parts = shlex.split(command_str)
                command, args = parts[0], parts[1:]
            except ValueError:
                # Fallback for simple splitting if shlex fails (e.g., unmatched quotes)
                parts = command_str.split(" ", 1)
                command, args = parts[0], parts[1:] if len(parts) > 1 else []

            if command == "clear":
                self.action_clear_log()
                return
            elif command in ["quit", "exit"]:
                self.action_quit()
                return
            elif command == "debug":
                self.action_show_debug()
                return
            elif command == "help":
                # Explicitly handle help here to show the new formatted output
                await self.show_help()
                return
        
        # Process the input with a dummy stream callback to enable streaming
        # We rely on the core's event system for actual display, but we need
        # to pass a callback to trigger streaming mode in the core
        try:
            self.debug_messages.append(f"Processing input: {user_input[:50]}...")
            
            # Dummy stream callback - it's synchronous, as the interface expects.
            def dummy_stream_callback(chunk: str) -> None:
                """Dummy callback to enable streaming - events handle the actual display."""
                pass
            
            # Set up signal handling for subprocess isolation
            original_sigint_handler = None
            try:
                # Temporarily ignore SIGINT during processing to prevent subprocess interference
                original_sigint_handler = signal.signal(signal.SIGINT, signal.SIG_IGN)
            except (ValueError, OSError):
                # Signal handling might not be available in all contexts
                pass
            
            try:
                # The interface expects a dictionary with 'text' key
                # Pass the dummy stream callback to enable streaming
                await self.interface.process_input({'text': user_input}, stream_callback=dummy_stream_callback)
                
                self.debug_messages.append("Input processing completed")
            finally:
                # Restore original signal handler
                if original_sigint_handler is not None:
                    try:
                        signal.signal(signal.SIGINT, original_sigint_handler)
                    except (ValueError, OSError):
                        pass
                
        except KeyboardInterrupt:
            # Handle user interruption gracefully
            self.log_widget.write("[yellow]⚠️ Processing interrupted by user[/yellow]")
            self.debug_messages.append("Input processing interrupted by user")
        except OSError as e:
            # Handle file descriptor and system-level errors
            error_msg = f"System error during processing: {e}"
            logger.error(error_msg, exc_info=True)
            self.debug_messages.append(error_msg)
            self.log_widget.write(f"[red]⚠️ System error: {e}[/red]")
            
            # If it's a file descriptor error, suggest restart
            if "Bad file descriptor" in str(e):
                self.log_widget.write("[yellow]💡 This is likely from code execution. Try restarting the TUI if issues persist.[/yellow]")
        except Exception as e:
            error_msg = f"Error processing input: {e}"
            logger.error(error_msg, exc_info=True)
            self.debug_messages.append(error_msg)
            self.log_widget.write(Panel(f"[bold red]Error processing input:[/bold red] {e}", border_style="red"))

    def action_clear_log(self) -> None:
        """Clear the chat log."""
        self.log_widget.clear()
        self.log_widget.write(Panel("🐧 [bold cyan]Chat cleared[/bold cyan]", border_style="cyan"))

    def action_show_debug(self) -> None:
        """Show debug information."""
        if not self.debug_messages:
            self.log_widget.write(Panel("[green]No debug messages to show[/green]", title="Debug", border_style="green"))
        else:
            debug_content = "\n".join(self.debug_messages[-20:])  # Show last 20 debug messages
            self.log_widget.write(Panel(debug_content, title="Debug Messages (Last 20)", border_style="yellow"))

    async def show_help(self) -> None:
        """Display the structured help message."""
        help_data = await self.interface._handle_help_command([])
        
        if "commands" in help_data:
            help_content = []
            title = help_data.get("help_title", "Available Commands")
            
            for category, commands in help_data["commands"].items():
                help_content.append(f"\n[bold yellow]{category}[/bold yellow]")
                for command, description in commands.items():
                    help_content.append(f"  [cyan]{command:<25}[/cyan] [white]{description}[/white]")
            
            self.log_widget.write(
                Panel(
                    "\n".join(help_content),
                    title=f"🐧 {title}",
                    border_style="blue",
                    padding=(1, 2)
                )
            )
        else:
            # Fallback for old format or error
            self.log_widget.write(Panel("Could not retrieve help information.", border_style="red"))

    def action_quit(self) -> None:
        """Quit the application and show debug info if available."""
        if self.debug_messages:
            print("\n" + "="*60)
            print("PENGUIN TUI DEBUG LOG")
            print("="*60)
            for i, msg in enumerate(self.debug_messages, 1):
                print(f"{i:3d}. {msg}")
            print("="*60)
        self.exit()

class TUI:
    """Entry point for the Textual UI."""
    
    @staticmethod
    def run():
        """Run the Textual application."""
        # Set environment variable to indicate TUI mode
        os.environ['PENGUIN_TUI_MODE'] = '1'
        
        app = PenguinTextualApp()
        try:
            app.run()
        except OSError as e:
            if "Bad file descriptor" in str(e):
                logger.warning(f"TUI encountered file descriptor issue (likely from subprocess): {e}")
                print(f"\n⚠️  TUI encountered a file descriptor issue, likely from code execution.")
                print(f"This is usually harmless and the application can be restarted.")
                print(f"Error details: {e}")
            else:
                logger.error(f"TUI crashed with OSError: {e}")
                print(f"\nTUI crashed with system error: {e}")
                print(f"Full traceback:\n{traceback.format_exc()}")
        except KeyboardInterrupt:
            logger.info("TUI interrupted by user")
            print("\n👋 Goodbye!")
        except Exception as e:
            logger.error(f"TUI crashed: {e}")
            print(f"\nTUI crashed with error: {e}")
            print(f"Full traceback:\n{traceback.format_exc()}")
        finally:
            # Clean up environment variable
            os.environ.pop('PENGUIN_TUI_MODE', None)
            
            # Always show debug info on exit if available
            if hasattr(app, 'debug_messages') and app.debug_messages:
                print("\n" + "="*60)
                print("PENGUIN TUI DEBUG LOG")
                print("="*60)
                for i, msg in enumerate(app.debug_messages, 1):
                    print(f"{i:3d}. {msg}")
                print("="*60) 