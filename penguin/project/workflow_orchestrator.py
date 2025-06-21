"""Workflow Orchestrator for Penguin.

This module orchestrates task execution by selecting the next available task
and delegating it to the appropriate executor.
"""

import asyncio
import logging
from typing import Any, Dict, Optional

from .manager import ProjectManager
from .task_executor import ProjectTaskExecutor
from .validation_manager import ValidationManager
from .git_manager import GitManager
from .models import TaskStatus

logger = logging.getLogger(__name__)


class WorkflowOrchestrator:
    """Orchestrates the selection and execution of tasks."""
    
    def __init__(
        self,
        project_manager: ProjectManager,
        task_executor: ProjectTaskExecutor,
        validation_manager: ValidationManager,
        git_manager: GitManager,
    ):
        """Initialize the workflow orchestrator.
        
        Args:
            project_manager: For accessing project/task data.
            task_executor: For running individual tasks.
            validation_manager: For validating task completion.
            git_manager: For creating pull requests.
        """
        self.project_manager = project_manager
        self.task_executor = task_executor
        self.validation_manager = validation_manager
        self.git_manager = git_manager
        logger.info("WorkflowOrchestrator initialized.")

        # -----------------------------------------------------------------
        # Simple debug helper – for now we just use print() so that the
        # messages are always visible even if logging isn't configured.
        # -----------------------------------------------------------------
        self._debug_enabled = True

    def _debug(self, message: str) -> None:
        """Print a debug message if debugging is enabled."""
        if self._debug_enabled:
            print(f"[WorkflowOrchestrator DEBUG] {message}")

    async def run_next_task(self, project_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """
        Finds the next task, executes it, validates it, and creates a PR.

        This is the core method for the MVP's orchestration logic, tying
        all the components together.
            
        Returns:
            A dictionary with the execution result, or None if no task was found.
        """
        logger.info("Orchestrator looking for the next available task.")
        self._debug("run_next_task invoked – fetching next task")
        task = await self.project_manager.get_next_task_async(project_id=project_id)

        self._debug(f"get_next_task_async returned: {task!r}")

        if not task:
            logger.info("No available tasks to run.")
            return None

        logger.info(f"Found next task: '{task.title}' (ID: {task.id})")
        self._debug(f"Working on task '{task.title}' (ID: {task.id})")
        workflow_result = {"task_id": task.id, "task_title": task.title}

        try:
            # 1. Mark the task as RUNNING
            success = self.project_manager.update_task_status(
                task.id, TaskStatus.RUNNING
            )
            if not success:
                raise Exception(f"Failed to update task status to RUNNING")
            logger.info(f"Task '{task.title}' marked as RUNNING")
            self._debug("Task status set to RUNNING")

            # 2. Execute the task
            self._debug("Executing task via ProjectTaskExecutor")
            exec_result = await self.task_executor.execute_task(task)
            self._debug(f"Execution result: {exec_result}")
            if exec_result["status"] == "error":
                raise Exception(f"Task execution failed: {exec_result['message']}")
            
            changed_files = exec_result.get("changed_files", [])

            # 3. Check if task is already completed (RunMode may have completed it)
            # Reload task to get current status
            updated_task = self.project_manager.get_task(task.id)
            self._debug(f"Reloaded task after execution: {updated_task!r}")
            if not updated_task:
                raise Exception(f"Task {task.id} not found after execution")
                
            if updated_task.status == TaskStatus.COMPLETED:
                logger.info(f"Task '{task.title}' already marked as COMPLETED by executor")
                # Skip validation and PR creation for now - task is already done
                return {
                    "task_id": task.id,
                    "task_title": task.title,
                    "status": TaskStatus.COMPLETED.name,
                    "message": "Task already completed by executor"
                }
            elif updated_task.status in [TaskStatus.FAILED, TaskStatus.CANCELLED]:
                logger.warning(f"Task '{task.title}' ended with status {updated_task.status.value}")
                return {
                    "task_id": task.id,
                    "task_title": task.title,
                    "status": updated_task.status.value,
                    "message": f"Task ended with status {updated_task.status.value}"
                }

            # 4. Only proceed with validation if task is still RUNNING
            if updated_task.status == TaskStatus.RUNNING:
                # Validate the result
                await self.project_manager.update_task_status_async(
                    task.id, TaskStatus.PENDING_REVIEW, "Execution complete, running validation."
                )
                validation_result = await self.validation_manager.validate_task_completion(task, changed_files)
                workflow_result["validation"] = validation_result
                
                if not validation_result.get("validated"):
                    # Validation failed - mark as failed
                    success = self.project_manager.update_task_status(
                        task.id, TaskStatus.FAILED
                    )
                    if not success:
                        logger.error(f"Failed to update task status to FAILED for task {task.id}")
                    return {
                        "task_id": task.id,
                        "task_title": task.title,
                        "status": "validation_failed",
                        "validation_result": validation_result
                    }

                # 6. Create PR for validated task
                self._debug("Creating pull-request for validated task")
                pr_result = await self.git_manager.create_pr_for_task(task, validation_result)
                self._debug(f"PR creation result: {pr_result}")

                # 7. Finalize task as COMPLETED
                success = self.project_manager.update_task_status(
                    task.id, TaskStatus.COMPLETED
                )
                if not success:
                    raise Exception(f"Failed to update task status to COMPLETED")
                logger.info(f"Task '{task.title}' marked as COMPLETED. PR: {pr_result.get('pr_url')}")

                workflow_result['pr_result'] = pr_result
                workflow_result['final_status'] = 'COMPLETED'
                return workflow_result
            else:
                # Task is in an unexpected state
                logger.warning(f"Task '{task.title}' in unexpected state {updated_task.status.value} after execution")
            return {
                    "task_id": task.id,
                    "task_title": task.title,
                    "status": updated_task.status.value,
                    "message": f"Task in unexpected state {updated_task.status.value}"
            }
            
        except Exception as e:
            logger.error(f"Workflow for task '{task.title}' failed: {e}", exc_info=True)
            self._debug(f"Exception encountered: {e}")
            
            # Check current task status before attempting to mark as failed
            current_task = self.project_manager.get_task(task.id)
            if current_task and current_task.status not in [TaskStatus.FAILED, TaskStatus.COMPLETED, TaskStatus.CANCELLED]:
                # Only try to mark as failed if not already in a terminal state
                success = self.project_manager.update_task_status(
                    task.id, TaskStatus.FAILED
                )
                if not success:
                    logger.error(f"Failed to update task status to FAILED for task {task.id}")
                else:
                    logger.info(f"Task '{task.title}' marked as FAILED due to workflow error")
            else:
                logger.info(f"Task '{task.title}' already in terminal state {current_task.status.value if current_task else 'unknown'}, not changing status")
            
            workflow_result['error'] = str(e)
            workflow_result['final_status'] = 'FAILED'
            return workflow_result

        return workflow_result 