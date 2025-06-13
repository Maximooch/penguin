"""Project and Task Management System

This module provides a comprehensive project and task management system for Penguin,
featuring:

- SQLite-backed persistent storage with ACID transactions
- Event-driven updates with EventBus integration  
- Hierarchical project/task structure with dependencies
- Dual sync/async API for non-blocking operations
- Execution tracking and metrics
- Checkpoint/rollback capabilities

Key Classes:
    - ProjectManager: Main interface for project/task operations
    - Project: Container for related tasks and context
    - Task: Individual work item with execution tracking
    - TaskEvent: Event types for task lifecycle

Example Usage:
    ```python
    from penguin.project import ProjectManager, Task
    
    # Initialize manager
    manager = ProjectManager(workspace_path="./workspace")
    
    # Create project and tasks
    project = await manager.create_project("My Project", "A sample project")
    task = await manager.create_task("Implement feature", "Add new functionality", project.id)
    
    # Query and update
    active_tasks = await manager.get_active_tasks()
    await manager.complete_task(task.id)
    ```
"""

from .manager import ProjectManager
from .models import Project, Task, TaskStatus, TaskEvent, ExecutionRecord
from .storage import ProjectStorage
from .exceptions import ProjectError, TaskError, ValidationError

__all__ = [
    # Main classes
    "ProjectManager",
    "Project", 
    "Task",
    
    # Enums and events
    "TaskStatus",
    "TaskEvent", 
    "ExecutionRecord",
    
    # Storage
    "ProjectStorage",
    
    # Exceptions
    "ProjectError",
    "TaskError", 
    "ValidationError",
] 