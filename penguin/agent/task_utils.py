from typing import List, Optional
from .task import Task, TaskStatus
from .task_manager import TaskManager

def create_task(task_manager: TaskManager, name: str, description: str) -> str:
    task = task_manager.create_task(name, description)
    return f"Task created: {task}"

def update_task(task_manager: TaskManager, description: str, progress: int) -> str:
    task = task_manager.get_task_by_description(description)
    if task:
        task.update_progress(progress)
        return f"Task updated: {task}"
    return f"Task not found: {description}"

def complete_task(task_manager: TaskManager, description: str) -> str:
    task = task_manager.get_task_by_description(description)
    if task:
        task.update_progress(100)
        return f"Task completed: {task}"
    return f"Task not found: {description}"

def list_tasks(task_manager: TaskManager) -> str:
    return task_manager.get_task_board()