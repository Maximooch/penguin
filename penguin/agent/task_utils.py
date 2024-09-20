from typing import List, Optional
from .task import Task, TaskStatus
from .project import Project
from .task_manager import TaskManager
import os

def create_task(task_manager: TaskManager, name: str, description: str, project_name: Optional[str] = None) -> str:
    task = task_manager.create_task(name.strip(), description)
    if project_name:
        project = task_manager.get_project_by_name(project_name)
        if project:
            task_manager.add_task_to_project(project, task)
            task_manager.save_tasks()  # Moved here
            return f"Task created and added to project '{project_name}': {task}"
        else:
            task_manager.save_tasks()  # Ensure task is saved even if project isn't found
            return f"Task created, but project '{project_name}' not found: {task}"
    else:
        task_manager.save_tasks()  # Save the task when no project is specified
        return f"Task created: {task}"

def create_project(task_manager: TaskManager, name: str, description: str) -> str:
    project = task_manager.create_project(name.strip(), description)
    return f"Project created: {project}"

def update_task(task_manager: TaskManager, name: str, progress: int) -> str:
    task = task_manager.get_task_by_name(name)
    if task:
        task.update_progress(int(progress))
        task_manager.save_tasks()
        return f"Task updated: {task}"
    return f"Task not found: {name}"

def complete_task(task_manager: TaskManager, name: str) -> str:
    task = task_manager.get_task_by_name(name)
    if task:
        task.update_progress(100)
        task_manager.save_tasks()
        return f"Task completed: {task}"
    return f"Task not found: {name}"

def list_tasks(task_manager: TaskManager) -> str:
    return task_manager.get_task_board()

def add_subtask(task_manager: TaskManager, parent_name: str, subtask_name: str, subtask_description: str) -> str:
    parent_task = task_manager.get_task_by_name(parent_name)
    if parent_task:
        subtask = Task(subtask_name, subtask_description)
        parent_task.add_subtask(subtask)
        task_manager.save_tasks()
        return f"Subtask added to '{parent_name}': {subtask}"
    return f"Parent task not found: {parent_name}"

def remove_task(task_manager: TaskManager, name: str) -> str:
    task = task_manager.get_task_by_name(name)
    if task:
        task_manager.remove_task(task)
        task_manager.save_tasks()
        return f"Task removed: {task}"
    return f"Task not found: {name}"

def clear_completed_tasks(task_manager: TaskManager) -> str:
    task_manager.clear_completed_tasks()
    task_manager.save_tasks()
    return "Completed tasks have been cleared."

def get_task_details(task_manager: TaskManager, name: str) -> str:
    task = task_manager.get_task_by_name(name)
    if task:
        details = [f"Task: {task.name}",
                   f"Description: {task.description}",
                   f"Status: {task.status.value}",
                   f"Progress: {task.progress}%"]
        if task.subtasks:
            details.append("Subtasks:")
            for subtask in task.subtasks:
                details.append(f"  - {subtask.name}: {subtask.status.value} ({subtask.progress}%)")
        return "\n".join(details)
    return f"Task not found: {name}"

def get_project_details(task_manager: TaskManager, name: str) -> str:
    project = task_manager.get_project_by_name(name)
    if project:
        tasks = [task_manager.get_task(task_id) for task_id in project.task_ids]
        details = [
            f"Project: {project.name}",
            f"Description: {project.description}",
            f"Status: {project.status.value}",
            f"Progress: {project.progress:.2f}%",
            "Tasks:"
        ]
        for task in tasks:
            if task:
                details.append(f"  - {task.name}: {task.status.value} ({task.progress}%)")
        return "\n".join(details)
    return f"Project not found: {name}"

def list_projects(task_manager: TaskManager) -> str:
    return task_manager.get_project_board()