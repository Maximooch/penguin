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
        # Ensure widgets never reserve vertical space unnecessarily.
        # In Textual, some containers default to a non-zero min-height which can
        # create trailing gaps when stacked inside a VerticalScroll. Enforce a
        # compact baseline here so specialized widgets don't need to repeat it.
        try:
            self.styles.min_height = 0  # type: ignore[attr-defined]
            self.styles.height = "auto"  # type: ignore[attr-defined]
        except Exception:
            # Styles may not be available early during construction in some
            # Textual versions; fail open rather than raising.
            pass
    
    def toggle_expansion(self) -> None:
        """Toggle the expanded/collapsed state."""
        self.is_expanded = not self.is_expanded
    
    def set_loading(self, loading: bool) -> None:
        """Set the loading state."""
        self.is_loading = loading
    
    def update_metadata(self, key: str, value: Any) -> None:
        """Update widget metadata."""
        self.metadata[key] = value
