"""Base widget classes for Penguin TUI."""

from textual.widgets import Static
from textual.reactive import reactive
from typing import Optional, Dict, Any


class PenguinWidget(Static):
    """Base class for all Penguin TUI widgets."""
    
    # Common reactive properties
    is_expanded = reactive(False)
    is_loading = reactive(False)
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.metadata: Dict[str, Any] = {}
    
    def toggle_expansion(self) -> None:
        """Toggle the expanded/collapsed state."""
        self.is_expanded = not self.is_expanded
    
    def set_loading(self, loading: bool) -> None:
        """Set the loading state."""
        self.is_loading = loading
    
    def update_metadata(self, key: str, value: Any) -> None:
        """Update widget metadata."""
        self.metadata[key] = value
