from typing import Dict, Any

class TaskTools:
    """Tools for managing task lifecycle and completion."""
    
    def task_completed(self, summary: str) -> str:
        """
        Signal that the current task has been successfully completed.
        
        Args:
            summary: A concise summary of what was accomplished.
            
        Returns:
            A confirmation message.
        """
        # This tool is primarily a signal for the Engine/RunMode to stop.
        # The actual stopping logic is handled by the Engine observing this tool call.
        return f"Task marked as completed. Summary: {summary}"
