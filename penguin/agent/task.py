from typing import Optional, Callable, Any
import logging
from enum import Enum

class TaskStatus(Enum):
    NOT_STARTED = "Not Started"
    IN_PROGRESS = "In Progress"
    COMPLETED = "Completed"
    FAILED = "Failed"

class Task:
    def __init__(self, description: str, logger: logging.Logger):
        self.description = description
        self.logger = logger
        self.status = TaskStatus.NOT_STARTED
        self.progress = 0
        self.subtasks = []

    def run(self, chat_function: Callable) -> None:
        self.status = TaskStatus.IN_PROGRESS
        self.logger.info(f"Starting task: {self.description}")
        
        while self.status == TaskStatus.IN_PROGRESS:
            try:
                response = chat_function(self.description, current_progress=self.progress)
                self._process_response(response)
            except Exception as e:
                self._handle_error(e)

    def _process_response(self, response: Any) -> None:
        # Process the response from the chat function
        # Update progress, status, and subtasks as needed
        # This is a placeholder and should be implemented based on your specific requirements
        pass

    def _handle_error(self, e: Exception) -> None:
        self.logger.error(f"Error in task '{self.description}': {str(e)}")
        self.status = TaskStatus.FAILED

    def add_subtask(self, subtask_description: str) -> None:
        subtask = Task(subtask_description, self.logger)
        self.subtasks.append(subtask)

    def update_progress(self, progress: int) -> None:
        self.progress = progress
        if self.progress >= 100:
            self.status = TaskStatus.COMPLETED

    def __str__(self) -> str:
        return f"Task: {self.description} - Status: {self.status.value} - Progress: {self.progress}%"