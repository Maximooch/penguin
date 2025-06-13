"""Exception classes for the Project and Task Management System.

This module defines custom exceptions used throughout the project management
system to provide specific error handling and meaningful error messages.
"""

from typing import Optional, Any


class ProjectError(Exception):
    """Base exception for project management errors."""
    
    def __init__(self, message: str, project_id: Optional[str] = None, details: Optional[Any] = None):
        self.project_id = project_id
        self.details = details
        super().__init__(message)


class TaskError(Exception):
    """Base exception for task management errors."""
    
    def __init__(self, message: str, task_id: Optional[str] = None, details: Optional[Any] = None):
        self.task_id = task_id
        self.details = details
        super().__init__(message)


class ValidationError(Exception):
    """Exception for data validation errors."""
    
    def __init__(self, message: str, field: Optional[str] = None, value: Optional[Any] = None):
        self.field = field
        self.value = value
        super().__init__(message)


class StorageError(ProjectError):
    """Exception for storage-related errors."""
    pass


class DependencyError(TaskError):
    """Exception for task dependency errors."""
    pass


class StateTransitionError(TaskError):
    """Exception for invalid state transitions."""
    
    def __init__(self, message: str, from_state: str, to_state: str, task_id: Optional[str] = None):
        self.from_state = from_state
        self.to_state = to_state
        super().__init__(message, task_id)


class ResourceConstraintError(TaskError):
    """Exception for resource constraint violations."""
    
    def __init__(self, message: str, constraint_type: str, limit: Any, attempted: Any, task_id: Optional[str] = None):
        self.constraint_type = constraint_type
        self.limit = limit
        self.attempted = attempted
        super().__init__(message, task_id)


class ProjectNotFoundError(ProjectError):
    """Exception when a project cannot be found."""
    pass


class TaskNotFoundError(TaskError):
    """Exception when a task cannot be found."""
    pass


class DuplicateError(Exception):
    """Exception when attempting to create duplicate entities."""
    
    def __init__(self, message: str, entity_type: str, identifier: str):
        self.entity_type = entity_type
        self.identifier = identifier
        super().__init__(message) 