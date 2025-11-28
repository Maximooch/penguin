from typing import Dict, Any, Optional
import json


class TaskTools:
    """Tools for managing task lifecycle and completion signals."""
    
    def finish_response(self, summary: Optional[str] = None) -> str:
        """
        Signal that the conversational response is complete.
        
        Called by the LLM when it has finished responding to the user
        and has no more actions to take. This stops the run_response loop.
        
        Args:
            summary: Optional brief summary of the response.
            
        Returns:
            A confirmation message.
        """
        # This tool is a signal for Engine.run_response to stop.
        if summary:
            return f"Response complete. Summary: {summary}"
        return "Response complete."

    def finish_task(self, params: Optional[str] = None) -> str:
        """
        Signal that the LLM believes the task objective is achieved.
        
        This transitions the task to PENDING_REVIEW status for human approval.
        The task is NOT marked COMPLETED - a human must approve it.
        
        Args:
            params: Either a plain summary string, or JSON with:
                - summary: What was accomplished (optional)
                - status: "done" | "partial" | "blocked" (default: "done")
            
        Returns:
            A confirmation message indicating task is pending review.
        """
        # Parse params - could be plain string or JSON
        summary = None
        status = "done"
        
        if params:
            params = params.strip()
            if params.startswith("{"):
                try:
                    data = json.loads(params)
                    summary = data.get("summary")
                    status = data.get("status", "done")
                except json.JSONDecodeError:
                    summary = params
            else:
                summary = params
        
        # This tool is a signal for Engine.run_task to stop.
        # The actual state transition to PENDING_REVIEW is handled by RunMode/Engine.
        status_msg = {
            "done": "Task objective achieved",
            "partial": "Partial progress made", 
            "blocked": "Task blocked - cannot proceed"
        }.get(status, "Task objective achieved")
        
        # Include machine-readable status marker for Engine to parse reliably
        # This avoids false positives from substring matching in user summaries
        status_marker = f"[FINISH_STATUS:{status}]"
        
        if summary:
            return f"{status_msg}. Marked for human review. Summary: {summary} {status_marker}"
        return f"{status_msg}. Marked for human review. {status_marker}"

    # Deprecated: kept for backward compatibility
    def task_completed(self, summary: str) -> str:
        """Deprecated: Use finish_task instead."""
        return self.finish_task(summary)
