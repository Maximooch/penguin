"""Data models for the Project and Task Management System.

This module defines the core data structures used throughout the project management
system, including Projects, Tasks, and their associated metadata and execution records.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Union
import json

from penguin.utils.events import TaskEvent  ## type: ignore
from penguin.utils.serialization import to_dict, from_dict  ## type: ignore


class TaskStatus(Enum):
    """Task status enumeration with clear state transitions."""
    ACTIVE = "active"
    RUNNING = "running"
    PENDING_REVIEW = "pending_review" 
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    FAILED = "failed"
    ARCHIVED = "archived"
    
    @classmethod
    def valid_transitions(cls) -> Dict[TaskStatus, List[TaskStatus]]:
        """Return valid state transitions for task status."""
        return {
            cls.ACTIVE: [cls.RUNNING, cls.COMPLETED, cls.CANCELLED, cls.ARCHIVED],
            cls.RUNNING: [cls.ACTIVE, cls.COMPLETED, cls.FAILED, cls.PENDING_REVIEW, cls.CANCELLED],
            cls.PENDING_REVIEW: [cls.ACTIVE, cls.RUNNING, cls.COMPLETED, cls.CANCELLED, cls.FAILED],
            cls.COMPLETED: [cls.ACTIVE, cls.ARCHIVED],  # Allow reopening
            cls.CANCELLED: [cls.ACTIVE, cls.ARCHIVED],
            cls.FAILED: [cls.ACTIVE, cls.ARCHIVED], 
            cls.ARCHIVED: [cls.ACTIVE]  # Allow unarchiving
        }


class ExecutionResult(Enum):
    """Execution result enumeration."""
    SUCCESS = "success"
    FAILURE = "failure"
    INCOMPLETE = "incomplete"
    CANCELLED = "cancelled"


@dataclass
class ExecutionRecord:
    """Tracks a single execution attempt for a task."""
    
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    task_id: str = ""
    executor_id: str = "system"
    started_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    completed_at: Optional[str] = None
    result: Optional[ExecutionResult] = None
    response: str = ""
    task_prompt: str = ""
    iterations: int = 0
    max_iterations: int = 5
    tokens_used: Dict[str, int] = field(default_factory=dict)
    tools_used: List[str] = field(default_factory=list)
    execution_context: Dict[str, Any] = field(default_factory=dict)
    error_details: Optional[str] = None
    
    def complete(self, result: ExecutionResult, response: str = "", error_details: str = None) -> None:
        """Mark this execution as completed."""
        self.completed_at = datetime.utcnow().isoformat()
        self.result = result
        self.response = response
        if error_details:
            self.error_details = error_details
    
    def update_token_usage(self, token_usage: Dict[str, int]) -> None:
        """Update token usage statistics."""
        for key, value in token_usage.items():
            self.tokens_used[key] = self.tokens_used.get(key, 0) + value
    
    def add_tool_usage(self, tool_name: str) -> None:
        """Record tool usage."""
        if tool_name not in self.tools_used:
            self.tools_used.append(tool_name)
    
    @property
    def duration_seconds(self) -> Optional[float]:
        """Calculate execution duration in seconds."""
        if not self.completed_at:
            return None
        start = datetime.fromisoformat(self.started_at.replace('Z', '+00:00'))
        end = datetime.fromisoformat(self.completed_at.replace('Z', '+00:00'))
        return (end - start).total_seconds()
    
    @property
    def is_completed(self) -> bool:
        """Check if execution is completed."""
        return self.completed_at is not None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        data = to_dict(self)
        if self.result:
            data['result'] = self.result.value
        return data
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> ExecutionRecord:
        """Create from dictionary."""
        if 'result' in data and data['result']:
            data['result'] = ExecutionResult(data['result'])
        return from_dict(cls, data)


@dataclass
class StateTransition:
    """Represents a state transition in task lifecycle."""
    
    from_state: TaskStatus
    to_state: TaskStatus
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    reason: Optional[str] = None
    user_id: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            'from_state': self.from_state.value,
            'to_state': self.to_state.value, 
            'timestamp': self.timestamp,
            'reason': self.reason,
            'user_id': self.user_id
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> StateTransition:
        """Create from dictionary."""
        return cls(
            from_state=TaskStatus(data['from_state']),
            to_state=TaskStatus(data['to_state']),
            timestamp=data['timestamp'],
            reason=data.get('reason'),
            user_id=data.get('user_id')
        )


@dataclass
class Task:
    """Represents an individual task with execution tracking and state management."""
    
    id: str
    title: str
    description: str
    status: TaskStatus
    created_at: str
    updated_at: str
    priority: int = 0
    project_id: Optional[str] = None
    parent_task_id: Optional[str] = None  # For hierarchical tasks
    tags: List[str] = field(default_factory=list)
    dependencies: List[str] = field(default_factory=list)  # Task IDs that must complete first
    due_date: Optional[str] = None
    progress: int = 0  # 0-100 percentage
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    # Review and approval
    review_notes: Optional[str] = None
    reviewed_by: Optional[str] = None
    reviewed_at: Optional[str] = None
    
    # Resource constraints
    budget_tokens: Optional[int] = None
    budget_minutes: Optional[int] = None
    allowed_tools: Optional[List[str]] = None
    
    # Execution tracking
    execution_history: List[ExecutionRecord] = field(default_factory=list)
    transition_history: List[StateTransition] = field(default_factory=list)
    
    # Acceptance criteria
    acceptance_criteria: List[str] = field(default_factory=list)
    definition_of_done: Optional[str] = None
    
    def __post_init__(self):
        """Validate task data after initialization."""
        if isinstance(self.status, str):
            self.status = TaskStatus(self.status)
    
    def can_transition_to(self, new_status: TaskStatus) -> bool:
        """Check if transition to new status is valid."""
        valid_transitions = TaskStatus.valid_transitions()
        return new_status in valid_transitions.get(self.status, [])
    
    def transition_to(self, new_status: TaskStatus, reason: Optional[str] = None, user_id: Optional[str] = None) -> bool:
        """Perform state transition with validation and logging."""
        if not self.can_transition_to(new_status):
            return False
        
        # Record transition
        transition = StateTransition(
            from_state=self.status,
            to_state=new_status,
            reason=reason,
            user_id=user_id
        )
        self.transition_history.append(transition)
        
        # Update state
        old_status = self.status
        self.status = new_status
        self.updated_at = datetime.utcnow().isoformat()
        
        # Update progress based on status
        if new_status == TaskStatus.COMPLETED:
            self.progress = 100
        elif new_status == TaskStatus.FAILED:
            # Keep existing progress
            pass
        elif new_status == TaskStatus.ACTIVE and old_status == TaskStatus.COMPLETED:
            # Reopening task - reset progress if desired
            if self.progress == 100:
                self.progress = 90  # Keep most progress but indicate not complete
        
        return True
    
    def start_execution(self, executor_id: str = "system", task_prompt: str = "", context: Dict[str, Any] = None) -> ExecutionRecord:
        """Start a new execution attempt."""
        # Ensure task is running or active
        if self.status not in [TaskStatus.RUNNING, TaskStatus.ACTIVE]:
            self.transition_to(TaskStatus.ACTIVE, reason="Resetting to active to start execution")

        if self.status == TaskStatus.ACTIVE:
            self.transition_to(TaskStatus.RUNNING, reason="Starting execution")
        
        # Create execution record
        record = ExecutionRecord(
            task_id=self.id,
            executor_id=executor_id,
            task_prompt=task_prompt,
            execution_context=context or {}
        )
        
        # Set constraints from task
        if self.budget_tokens:
            record.execution_context['budget_tokens'] = self.budget_tokens
        if self.budget_minutes:
            record.execution_context['budget_minutes'] = self.budget_minutes
        if self.allowed_tools:
            record.execution_context['allowed_tools'] = self.allowed_tools
        
        self.execution_history.append(record)
        self.updated_at = datetime.utcnow().isoformat()
        
        return record
    
    def get_current_execution(self) -> Optional[ExecutionRecord]:
        """Get the most recent incomplete execution."""
        for record in reversed(self.execution_history):
            if not record.is_completed:
                return record
        return None
    
    def complete_current_execution(self, result: ExecutionResult, response: str = "", error_details: str = None) -> None:
        """Complete the current execution and update task status."""
        record = self.get_current_execution()
        if not record:
            return
        
        record.complete(result, response, error_details)
        self.updated_at = datetime.utcnow().isoformat()
        
        # Update task status based on result
        if result == ExecutionResult.SUCCESS:
            if self.status == TaskStatus.RUNNING:
                self.transition_to(TaskStatus.COMPLETED, reason="Execution successful")
        elif result == ExecutionResult.FAILURE:
            if self.status == TaskStatus.RUNNING:
                self.transition_to(TaskStatus.FAILED, reason="Execution failed")
    
    def mark_pending_review(self, notes: str, reviewer: Optional[str] = None) -> None:
        """Mark task as pending human review."""
        self.transition_to(TaskStatus.PENDING_REVIEW, reason="Pending review")
        self.review_notes = notes
        if reviewer:
            self.reviewed_by = reviewer
            self.reviewed_at = datetime.utcnow().isoformat()
    
    def approve(self, reviewer: str, notes: Optional[str] = None) -> None:
        """Approve task completion."""
        self.transition_to(TaskStatus.COMPLETED, reason="Approved by reviewer", user_id=reviewer)
        self.reviewed_by = reviewer
        self.reviewed_at = datetime.utcnow().isoformat()
        if notes:
            self.review_notes = notes
    
    def get_execution_metrics(self) -> Dict[str, Any]:
        """Calculate execution metrics from history."""
        if not self.execution_history:
            return {
                'total_attempts': 0,
                'success_rate': 0.0,
                'avg_duration': 0.0,
                'avg_iterations': 0.0,
                'total_tokens': 0,
                'common_tools': []
            }
        
        completed = [r for r in self.execution_history if r.is_completed]
        successful = [r for r in completed if r.result == ExecutionResult.SUCCESS]
        
        # Calculate metrics
        success_rate = len(successful) / len(completed) if completed else 0.0
        durations = [r.duration_seconds for r in completed if r.duration_seconds]
        avg_duration = sum(durations) / len(durations) if durations else 0.0
        avg_iterations = sum(r.iterations for r in completed) / len(completed) if completed else 0.0
        
        # Token usage
        total_tokens = sum(
            sum(r.tokens_used.values()) for r in self.execution_history
        )
        
        # Tool usage frequency
        tool_counts = {}
        for record in self.execution_history:
            for tool in record.tools_used:
                tool_counts[tool] = tool_counts.get(tool, 0) + 1
        
        common_tools = sorted(tool_counts.items(), key=lambda x: x[1], reverse=True)[:5]
        
        return {
            'total_attempts': len(self.execution_history),
            'completed_attempts': len(completed),
            'success_rate': success_rate,
            'avg_duration': avg_duration,  
            'avg_iterations': avg_iterations,
            'total_tokens': total_tokens,
            'common_tools': [tool for tool, count in common_tools],
            'tool_usage': dict(common_tools)
        }
    
    @property
    def is_blocked(self) -> bool:
        """Check if task is blocked by incomplete dependencies."""
        # This would need to be checked against other tasks in the system
        # For now, just return False - will be implemented in ProjectManager
        return len(self.dependencies) > 0
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        data = to_dict(self)
        data['status'] = self.status.value
        data['execution_history'] = [r.to_dict() for r in self.execution_history]
        data['transition_history'] = [t.to_dict() for t in self.transition_history]
        return data
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> Task:
        """Create Task from dictionary."""
        # Handle status conversion
        if 'status' in data:
            data['status'] = TaskStatus(data['status'])
        
        # Handle execution history
        if 'execution_history' in data:
            data['execution_history'] = [
                ExecutionRecord.from_dict(r) for r in data['execution_history']
            ]
        
        # Handle transition history  
        if 'transition_history' in data:
            data['transition_history'] = [
                StateTransition.from_dict(t) for t in data['transition_history']
            ]
        
        return from_dict(cls, data)


@dataclass  
class Project:
    """Represents a project containing multiple tasks and associated context."""
    
    id: str
    name: str
    description: str
    created_at: str
    updated_at: str
    status: str = "active"  # active, completed, archived
    
    # Organization
    tags: List[str] = field(default_factory=list)
    priority: int = 0
    
    # Paths
    workspace_path: Optional[Path] = None
    context_path: Optional[Path] = None
    
    # Metadata
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    # Resources and constraints
    budget_tokens: Optional[int] = None
    budget_minutes: Optional[int] = None
    
    # Timeline
    start_date: Optional[str] = None
    due_date: Optional[str] = None
    
    def __post_init__(self):
        """Initialize project paths if workspace_path is provided."""
        if self.workspace_path and not self.context_path:
            self.context_path = self.workspace_path / "context"
    
    def get_task_count(self, status: Optional[TaskStatus] = None) -> int:
        """Get count of tasks (to be implemented by ProjectManager)."""
        # This is a placeholder - actual implementation would query the storage
        return 0
    
    @property
    def is_completed(self) -> bool:
        """Check if project is completed.""" 
        return self.status == "completed"
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        data = to_dict(self)
        if self.workspace_path:
            data['workspace_path'] = str(self.workspace_path)
        if self.context_path:
            data['context_path'] = str(self.context_path)
        return data
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> Project:
        """Create Project from dictionary."""
        if 'workspace_path' in data and data['workspace_path']:
            data['workspace_path'] = Path(data['workspace_path'])
        if 'context_path' in data and data['context_path']:
            data['context_path'] = Path(data['context_path'])
        return from_dict(cls, data) 