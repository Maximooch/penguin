from typing import Callable
from .task import Task, TaskStatus
from config import MAX_TASK_ITERATIONS, TASK_COMPLETION_PHRASE
import time
import logging
from chat import print_bordered_message, PENGUIN_COLOR, TOOL_COLOR

logger = logging.getLogger(__name__)

def run_task(task: Task, chat_function: Callable, message_count: int):
    task.status = TaskStatus.IN_PROGRESS
    task.progress = 0

    try:
        for iteration in range(MAX_TASK_ITERATIONS):
            task.progress = min(100, int((iteration + 1) / MAX_TASK_ITERATIONS * 100))
            task.update_progress(task.progress)

            prompt = f"Task: {task.name}\nDescription: {task.description}\nCurrent Progress: {task.progress}%\nIteration: {iteration + 1}/{MAX_TASK_ITERATIONS}\n\nPlease continue working on this task. If the task is completed, respond with 'TASK_COMPLETED'. Otherwise, provide an update on the progress and any next steps."

            try:
                response, _ = chat_function(prompt, message_count)
                yield iteration + 1, MAX_TASK_ITERATIONS, response

                if "TASK_COMPLETED" in response:
                    task.status = TaskStatus.COMPLETED
                    task.progress = 100
                    break

            except Exception as e:
                yield iteration + 1, MAX_TASK_ITERATIONS, f"Error occurred: {str(e)}"

            time.sleep(0.1)

        if task.status != TaskStatus.COMPLETED:
            task.status = TaskStatus.FAILED

    except Exception as e:
        task.status = TaskStatus.FAILED
        yield 0, MAX_TASK_ITERATIONS, f"Task failed: {str(e)}"

    return task