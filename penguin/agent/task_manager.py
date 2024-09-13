import json
import os


from typing import List, Optional, Callable
import logging
from .task import Task, TaskStatus


class TaskManager:
    def __init__(self, logger: logging.Logger):
        self.tasks: List[Task] = []
        self.logger = logger
        self.current_task: Optional[Task] = None
        self.load_tasks()

    def create_task(self, name: str, description: str) -> Task:
        task = Task(name, description)
        self.tasks.append(task)
        self.save_tasks()
        return task

    def run_task(self, task: Task, chat_function: Callable, message_count: int):
        from agent.run_agent import run_task
        return run_task(task, chat_function, message_count)

    def get_task_board(self) -> str:
        header = "| Task Name | Task Description | Status | Progress |"
        separator = "|-----------|-------------------|--------|----------|"
        rows = [header, separator]
        
        for task in self.tasks:
            task_str = f"| {task.name[:10]:<10} | {task.description[:17]:<17} | {task.status.value:<6} | {task.progress:>3}% |"
            rows.append(task_str)
        
        return "\n".join(rows)

    def get_task_by_name(self, name: str) -> Optional[Task]:
        for task in self.tasks:
            if task.name.lower() == name.lower():
                return task
        return None

    def remove_task(self, task: Task) -> None:
        if task in self.tasks:
            self.tasks.remove(task)
        else:
            for parent_task in self.tasks:
                if task in parent_task.subtasks:
                    parent_task.subtasks.remove(task)
                    break

    def clear_completed_tasks(self) -> None:
        def clear_completed(tasks: List[Task]) -> List[Task]:
            updated_tasks = []
            for task in tasks:
                if task.status != TaskStatus.COMPLETED:
                    task.subtasks = clear_completed(task.subtasks)
                    updated_tasks.append(task)
            return updated_tasks

        self.tasks = clear_completed(self.tasks)

    def save_tasks(self) -> None:
        tasks_data = [
            {
                "name": task.name,
                "description": task.description,
                "status": task.status.value,
                "progress": task.progress
            }
            for task in self.tasks
        ]
        with open("tasks.json", "w") as f:
            json.dump(tasks_data, f)

    def load_tasks(self) -> None:
        if os.path.exists("tasks.json"):
            with open("tasks.json", "r") as f:
                tasks_data = json.load(f)
            self.tasks = [
                Task(
                    name=task_data["name"],
                    description=task_data["description"]
                )
                for task_data in tasks_data
            ]
            for task, task_data in zip(self.tasks, tasks_data):
                task.status = TaskStatus(task_data["status"])
                task.progress = task_data["progress"]

    def get_current_task(self) -> Optional[Task]:
        return self.current_task

    def set_current_task(self, task: Task) -> None:
        self.current_task = task