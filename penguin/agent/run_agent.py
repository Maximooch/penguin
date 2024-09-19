from typing import Callable, Generator, Tuple
from .task import Task, TaskStatus
from .project import Project
from config import MAX_TASK_ITERATIONS, TASK_COMPLETION_PHRASE
import time
import logging
from chat import print_bordered_message, PENGUIN_COLOR, TOOL_COLOR

logger = logging.getLogger(__name__)

def run_task(task: Task, chat_function: Callable, message_count: int) -> Generator[Tuple[int, int, str], None, Task]:
    task.status = TaskStatus.IN_PROGRESS
    task.progress = 0

    try:
        for iteration in range(MAX_TASK_ITERATIONS):
            task.progress = min(100, int((iteration + 1) / MAX_TASK_ITERATIONS * 100))
            task.update_progress(task.progress)

            prompt = f"Task: {task.name}\nDescription: {task.description}\nCurrent Progress: {task.progress}%\nIteration: {iteration + 1}/{MAX_TASK_ITERATIONS}\n\nPlease continue working on this task. If the task is completed, respond with '{TASK_COMPLETION_PHRASE}'. Otherwise, provide an update on the progress and any next steps."

            try:
                response, _ = chat_function(prompt, message_count)
                yield iteration + 1, MAX_TASK_ITERATIONS, response

                if TASK_COMPLETION_PHRASE in response:
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

def run_project(project: Project, chat_function: Callable, message_count: int) -> Generator[Tuple[int, int, str], None, Project]:
    project.status = TaskStatus.IN_PROGRESS
    project.progress = 0

    total_tasks = len(project.tasks)
    completed_tasks = 0

    for task in project.tasks:
        yield from run_task(task, chat_function, message_count)
        if task.status == TaskStatus.COMPLETED:
            completed_tasks += 1
        
        project.progress = (completed_tasks / total_tasks) * 100
        project.update_progress()

        yield total_tasks, completed_tasks, f"Project progress: {project.progress:.2f}%"

    if completed_tasks == total_tasks:
        project.status = TaskStatus.COMPLETED
    else:
        project.status = TaskStatus.FAILED

    return project

def run_agent(item: Task | Project, chat_function: Callable, message_count: int) -> Generator[Tuple[int, int, str], None, Task | Project]:
    if isinstance(item, Task):
        yield from run_task(item, chat_function, message_count)
    elif isinstance(item, Project):
        yield from run_project(item, chat_function, message_count)
    else:
        raise ValueError(f"Unsupported item type: {type(item)}")

    return item