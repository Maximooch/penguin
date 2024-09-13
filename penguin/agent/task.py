from typing import Optional, Callable, Any, List
import logging
from enum import Enum

class TaskStatus(Enum):
    NOT_STARTED = "Not Started"
    IN_PROGRESS = "In Progress"
    COMPLETED = "Completed"
    FAILED = "Failed"

class Task:
    def __init__(self, name: str, description: str):
        self.name = name
        self.description = description
        self.status = TaskStatus.NOT_STARTED
        self.progress = 0

    def update_progress(self, progress: int):
        self.progress = progress
        if progress == 100:
            self.status = TaskStatus.COMPLETED
        elif progress > 0:
            self.status = TaskStatus.IN_PROGRESS

    def run(self, chat_function: Callable, message_count: int):
        from agent.run_agent import run_task
        run_task(self, chat_function, message_count)

    def __str__(self):
        return f"Task: {self.name} - {self.description} - Status: {self.status.value} - Progress: {self.progress}%"