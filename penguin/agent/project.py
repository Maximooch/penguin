from typing import List
from .task import Task, TaskStatus
import logging

class Project:
    def __init__(self, name: str, description: str, logger: logging.Logger):
        self.name = name
        self.description = description
        self.logger = logger
        self.tasks: List[Task] = []
        self.status = TaskStatus.NOT_STARTED
        self.progress = 0

    def add_task(self, task: Task) -> None:
        self.tasks.append(task)

    def update_progress(self) -> None:
        if not self.tasks:
            return
        
        completed_tasks = sum(1 for task in self.tasks if task.status == TaskStatus.COMPLETED)
        self.progress = (completed_tasks / len(self.tasks)) * 100
        
        if self.progress == 100:
            self.status = TaskStatus.COMPLETED
        elif self.progress > 0:
            self.status = TaskStatus.IN_PROGRESS

    def __str__(self) -> str:
        return f"Project: {self.name} - Status: {self.status.value} - Progress: {self.progress:.2f}%"