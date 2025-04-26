"""
Execution record tracking for tasks.

This module provides data structures for tracking task execution history,
enabling analysis of task performance over time and debugging of execution issues.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, Any, List, Optional, Set
from enum import Enum
import uuid
import logging

logger = logging.getLogger(__name__)


class ExecutionResult(Enum):
    """Possible results of a task execution attempt."""
    SUCCESS = "success"
    FAILURE = "failure"
    INTERRUPTED = "interrupted"
    TIMEOUT = "timeout"
    INCOMPLETE = "incomplete"


@dataclass
class ExecutionRecord:
    """
    Records details about a specific execution of a task.
    
    This provides historical data about when and how a task was executed,
    enabling analysis and improvement of task performance over time.
    """
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    task_id: str = ""  # ID of the task that was executed
    started_at: str = field(default_factory=lambda: datetime.now().isoformat())
    completed_at: Optional[str] = None
    duration_seconds: float = 0.0
    result: ExecutionResult = ExecutionResult.INCOMPLETE
    executor_id: str = "system"  # ID of the executor (user, agent, etc.)
    
    # Execution details
    iterations: int = 0
    max_iterations: int = 0
    tools_used: List[str] = field(default_factory=list)
    token_usage: Dict[str, int] = field(default_factory=dict)
    
    # Context and outputs
    task_prompt: str = ""
    final_response: str = ""
    error_message: Optional[str] = None
    execution_context: Dict[str, Any] = field(default_factory=dict)
    
    def complete(self, result: ExecutionResult, response: str = "") -> None:
        """Mark execution as complete with result."""
        self.completed_at = datetime.now().isoformat()
        self.duration_seconds = (datetime.fromisoformat(self.completed_at) - 
                                datetime.fromisoformat(self.started_at)).total_seconds()
        self.result = result
        self.final_response = response
    
    def add_tool_usage(self, tool_name: str) -> None:
        """Track usage of a tool."""
        if tool_name not in self.tools_used:
            self.tools_used.append(tool_name)
    
    def update_token_usage(self, new_usage: Dict[str, int]) -> None:
        """Update token usage statistics."""
        for key, value in new_usage.items():
            if key in self.token_usage:
                self.token_usage[key] += value
            else:
                self.token_usage[key] = value
    
    def set_error(self, error_message: str) -> None:
        """Set error message for failed executions."""
        self.error_message = error_message
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        result = {
            "id": self.id,
            "task_id": self.task_id,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "duration_seconds": self.duration_seconds,
            # Convert the enum to a string value for JSON serialization
            "result": self.result.value if isinstance(self.result, ExecutionResult) else self.result,
            "executor_id": self.executor_id,
            "iterations": self.iterations,
            "max_iterations": self.max_iterations,
            "tools_used": self.tools_used,
            "token_usage": self.token_usage,
            "task_prompt": self.task_prompt,
            "final_response": self.final_response,
            "error_message": self.error_message,
            "execution_context": self.execution_context,
        }
        return result
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ExecutionRecord":
        """Create instance from dictionary."""
        # Handle enum conversion for result field
        if "result" in data and isinstance(data["result"], str):
            try:
                data["result"] = ExecutionResult(data["result"])
            except ValueError:
                data["result"] = ExecutionResult.INCOMPLETE
                
        return cls(**data)


def calculate_execution_metrics(records: List[ExecutionRecord]) -> Dict[str, Any]:
    """
    Calculate aggregate metrics from execution records.
    
    Args:
        records: List of execution records to analyze
        
    Returns:
        Dictionary of metrics including:
        - success_rate: Percentage of successful executions
        - avg_duration: Average execution time in seconds
        - avg_iterations: Average number of iterations per execution
        - common_tools: List of most commonly used tools 
        - token_efficiency: Average tokens per iteration
    """
    if not records:
        return {
            "success_rate": 0,
            "avg_duration": 0,
            "avg_iterations": 0,
            "common_tools": [],
            "token_efficiency": 0,
        }
    
    # Filter to only completed executions
    completed_records = [r for r in records if r.completed_at is not None]
    if not completed_records:
        return {
            "success_rate": 0,
            "avg_duration": 0,
            "avg_iterations": 0, 
            "common_tools": [],
            "token_efficiency": 0,
        }
    
    # Calculate success rate
    success_count = sum(1 for r in completed_records if r.result == ExecutionResult.SUCCESS)
    success_rate = (success_count / len(completed_records)) * 100
    
    # Calculate average duration
    avg_duration = sum(r.duration_seconds for r in completed_records) / len(completed_records)
    
    # Calculate average iterations
    avg_iterations = sum(r.iterations for r in completed_records) / len(completed_records)
    
    # Find common tools
    tool_counts = {}
    for record in completed_records:
        for tool in record.tools_used:
            tool_counts[tool] = tool_counts.get(tool, 0) + 1
    
    common_tools = sorted(tool_counts.items(), key=lambda x: x[1], reverse=True)
    common_tools = [t[0] for t in common_tools[:5]]  # Top 5 tools
    
    # Calculate token efficiency
    total_tokens = sum(sum(r.token_usage.values()) for r in completed_records if r.token_usage)
    total_iterations = sum(r.iterations for r in completed_records if r.iterations > 0)
    token_efficiency = total_tokens / total_iterations if total_iterations > 0 else 0
    
    return {
        "success_rate": success_rate,
        "avg_duration": avg_duration,
        "avg_iterations": avg_iterations,
        "common_tools": common_tools,
        "token_efficiency": token_efficiency,
    } 