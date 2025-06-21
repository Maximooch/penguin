"""Task Executor for Penguin Project Management.

This module is responsible for executing a single project task by invoking
the RunMode system.
"""

import logging
from typing import Any, Dict

from penguin.project.models import Task, TaskStatus
from .git_integration import GitIntegration

logger = logging.getLogger(__name__)


class ProjectTaskExecutor:
    """Executes a single project task using the RunMode system."""

    def __init__(self, run_mode, project_manager, git_integration: GitIntegration):
        """Initialize the task executor.

        Args:
            run_mode: An instance of the RunMode class for task execution.
            project_manager: An instance of the ProjectManager for updating task status.
            git_integration: An instance of the GitIntegration for checking file changes.
        """
        self.run_mode = run_mode
        self.project_manager = project_manager
        self.git_integration = git_integration
        logger.info("ProjectTaskExecutor initialized.")

    async def execute_task(self, task: Task) -> Dict[str, Any]:
        """
        Executes a single task using RunMode, captures file changes, and returns the result.

        Args:
            task: The Task object to execute.

        Returns:
            A dictionary containing the execution result and a list of changed files.
        """
        logger.info(f"Executing task: '{task.title}' (ID: {task.id})")

        # Get file status *before* execution to diff against later
        initial_changed_files = self.git_integration.get_changed_files()

        try:
            # Prepare context for RunMode. For the MVP, this is minimal.
            # In the future, this could include file context, etc.
            execution_context = {
                "task_id": task.id,
                "project_id": task.project_id,
                "acceptance_criteria": task.acceptance_criteria,
            }

            # Invoke RunMode to execute the task.
            # The `run_mode.start` method encapsulates the agent's entire lifecycle.
            run_result = await self.run_mode.start(
                name=task.title,
                description=task.description,
                context=execution_context,
            )
            
            # Get file status *after* execution
            final_changed_files = self.git_integration.get_changed_files()
            
            # Determine the files that were actually changed during this task run
            changed_by_task = list(set(final_changed_files) - set(initial_changed_files))
            logger.info(f"Task '{task.title}' modified {len(changed_by_task)} files.")

            return {
                "status": "success",
                "message": "Task execution completed by RunMode.",
                "run_mode_result": run_result,
                "changed_files": changed_by_task,
            }

        except Exception as e:
            logger.error(f"A critical error occurred in ProjectTaskExecutor for task '{task.title}': {e}", exc_info=True)
            return {
                "status": "error",
                "message": f"Critical executor error: {str(e)}",
            } 