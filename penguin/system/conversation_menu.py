from typing import List, Optional
from datetime import datetime
from rich.console import Console # type: ignore
from rich.table import Table # type: ignore
from rich.prompt import Prompt # type: ignore
from dataclasses import dataclass

@dataclass
class ConversationSummary:
    session_id: str
    title: str
    message_count: int
    last_active: str
    
    @property
    def display_date(self) -> str:
        """Return the already formatted date string"""
        return self.last_active
    
    @property
    def display_name(self) -> str:
        """Format conversation for display"""
        return f"{self.title[:40]} ({self.message_count} msgs) - {self.last_active}"

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
                str(idx),
                conv.title[:40],
                str(conv.message_count),
                conv.display_date
            )
            
        self.console.print("\n📝 Available Conversations:\n")
        self.console.print(table)
        
    def select_conversation(self, conversations: List[ConversationSummary]) -> Optional[str]:
        """Display menu and get user selection"""
        if not conversations:
            self.console.print("[yellow]No saved conversations found[/yellow]")
            return None
            
        self.display_conversations(conversations)
        
        # Get user selection
        choice = Prompt.ask(
            "\nSelect conversation number (or press Enter to cancel)",
            default=""
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