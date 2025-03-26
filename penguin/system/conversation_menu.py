from dataclasses import dataclass
from typing import List, Optional, Any

from rich.console import Console  # type: ignore
from rich.prompt import Prompt  # type: ignore
from rich.table import Table  # type: ignore


@dataclass
class ConversationSummary:
    session_id: str
    title: str
    message_count: int
    last_active: Any  # Can be string or datetime

    @property
    def display_date(self) -> str:
        """Format the last_active date for display"""
        if hasattr(self.last_active, 'strftime'):
            # It's a datetime object
            return self.last_active.strftime("%Y-%m-%d %H:%M")
        elif isinstance(self.last_active, str):
            # It's already a string
            return self.last_active
        else:
            # Something else
            return str(self.last_active) if self.last_active else "Unknown"

    @property
    def display_name(self) -> str:
        """Format conversation for display"""
        return f"{self.title[:40]} ({self.message_count} msgs) - {self.display_date}"


class ConversationMenu:
    def __init__(self, console: Console):
        self.console = console

    def display_conversations(self, conversations: List[ConversationSummary]) -> None:
        """Display conversations in a formatted table"""
        table = Table(show_header=True, header_style="bold blue")
        table.add_column("#", style="dim", width=4)
        table.add_column("Title", width=40)
        table.add_column("Messages", justify="right", width=10)
        table.add_column("Last Active", width=20)

        for idx, conv in enumerate(conversations, 1):
            table.add_row(
                str(idx), conv.title[:40], str(conv.message_count), conv.display_date
            )

        self.console.print("\n📝 Available Conversations:\n")
        self.console.print(table)

    def select_conversation(
        self, conversations: List[ConversationSummary]
    ) -> Optional[str]:
        """Display menu and get user selection"""
        if not conversations:
            self.console.print("[yellow]No saved conversations found[/yellow]")
            return None

        self.display_conversations(conversations)

        # Get user selection
        choice = Prompt.ask(
            "\nSelect conversation number (or press Enter to cancel)", default=""
        )

        if not choice:
            return None

        try:
            idx = int(choice) - 1
            if 0 <= idx < len(conversations):
                return conversations[idx].session_id
            else:
                self.console.print("[red]Invalid selection[/red]")
                return None
        except ValueError:
            self.console.print("[red]Please enter a valid number[/red]")
            return None
            
    def display_summary(self, messages: List[dict]) -> None:
        """Display conversation summary"""
        if not messages:
            self.console.print("[yellow]No messages in this conversation[/yellow]")
            return
            
        table = Table(show_header=True, header_style="bold blue")
        table.add_column("#", style="dim", width=4)
        table.add_column("Role", width=12)
        table.add_column("Content", width=60)
        
        # Get message snippets
        for idx, msg in enumerate(messages, 1):
            role = msg.get("role", "unknown")
            content = msg.get("content", "")
            
            # Truncate content for display
            if isinstance(content, str):
                content_preview = content[:60] + "..." if len(content) > 60 else content
            elif isinstance(content, list):
                # Handle structured content (e.g. messages with images)
                content_preview = "Structured content"
            else:
                content_preview = str(content)[:60]
                
            table.add_row(str(idx), role, content_preview)
            
        self.console.print("\n📝 Conversation Summary:\n")
        self.console.print(table)
        self.console.print(f"\nTotal messages: {len(messages)}\n")
