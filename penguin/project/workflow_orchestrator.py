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
from .exceptions import ValidationError
from .models import TaskPhase, TaskStatus

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

        self._debug_enabled = True

    def _debug(self, message: str) -> None:
        """Log a debug message if debugging is enabled."""
        if self._debug_enabled:
            logger.debug("[WorkflowOrchestrator DEBUG] %s", message)

    async def _execute_use_recipe(self, recipe: Dict[str, Any]) -> Dict[str, Any]:
        """Execute a minimal usage recipe, currently supporting shell steps only."""
        recipe_name = recipe.get("name", "unnamed")
        steps = recipe.get("steps", [])
        if not steps:
            raise ValidationError(
                f"Recipe '{recipe_name}' has no executable steps",
                field="recipe",
                value=recipe_name,
            )

        results = []
        for index, step in enumerate(steps, start=1):
            if "shell" not in step:
                step_type = next(iter(step.keys()), "unknown")
                raise ValidationError(
                    f"Unsupported recipe step type '{step_type}'",
                    field="recipe_step",
                    value=step_type,
                )

            command = step["shell"]
            process = await asyncio.create_subprocess_shell(
                command,
                cwd=str(self.project_manager.workspace_path),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=120)
            step_result = {
                "index": index,
                "type": "shell",
                "command": command,
                "returncode": process.returncode,
                "stdout": stdout.decode(),
                "stderr": stderr.decode(),
            }
            results.append(step_result)

            if process.returncode != 0:
                return {
                    "success": False,
                    "recipe": recipe_name,
                    "steps": results,
                }

        return {
            "success": True,
            "recipe": recipe_name,
            "steps": results,
        }

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
            # 1. Mark the task as RUNNING and enter IMPLEMENT
            success = self.project_manager.update_task_status(
                task.id, TaskStatus.RUNNING
            )
            if not success:
                raise Exception(f"Failed to update task status to RUNNING")
            await self.project_manager.update_task_phase_async(
                task.id,
                TaskPhase.IMPLEMENT,
                "Task claimed by orchestrator; starting implementation.",
            )
            logger.info(f"Task '{task.title}' marked as RUNNING")
            self._debug("Task status set to RUNNING and phase set to IMPLEMENT")

            # 2. Execute the task
            self._debug("Executing task via ProjectTaskExecutor")
            exec_result = await self.task_executor.execute_task(task)
            self._debug(f"Execution result: {exec_result}")
            executor_status = exec_result.get("status")
            if (
                executor_status is None
                or not isinstance(executor_status, str)
                or executor_status.strip() == ""
            ):
                raise ValueError(
                    f"Malformed executor result for task {task.id} ({task.title}): {exec_result!r}"
                )
            if executor_status == "error":
                raise Exception(f"Task execution failed: {exec_result['message']}")

            if executor_status not in {"completed", "pending_review", "success"}:
                logger.info(
                    "Task '%s' returned non-terminal executor status '%s'; leaving workflow in RUNNING.",
                    task.title,
                    executor_status,
                )
                return {
                    "task_id": task.id,
                    "task_title": task.title,
                    "status": executor_status,
                    "message": exec_result.get("message", "Task execution returned a non-terminal status."),
                    "run_mode_completion_type": exec_result.get("run_mode_completion_type"),
                    "run_mode_result": exec_result.get("run_mode_result"),
                    "final_status": TaskStatus.RUNNING.value,
                }

            changed_files = exec_result.get("changed_files", [])

            # 3. Reload task and validate the post-execution state.
            # RunMode no longer owns terminal project-task transitions.
            updated_task = self.project_manager.get_task(task.id)
            self._debug(f"Reloaded task after execution: {updated_task!r}")
            if not updated_task:
                raise Exception(f"Task {task.id} not found after execution")

            if updated_task.status in [TaskStatus.FAILED, TaskStatus.CANCELLED]:
                logger.warning(f"Task '{task.title}' ended with status {updated_task.status.value}")
                return {
                    "task_id": task.id,
                    "task_title": task.title,
                    "status": updated_task.status.value,
                    "message": f"Task ended with status {updated_task.status.value}"
                }

            # 4. Only proceed with validation if task is still RUNNING
            if updated_task.status == TaskStatus.RUNNING:
                await self.project_manager.update_task_phase_async(
                    task.id,
                    TaskPhase.TEST,
                    "Implementation finished; running validation checks.",
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

                if getattr(updated_task, "recipe", None):
                    await self.project_manager.update_task_phase_async(
                        task.id,
                        TaskPhase.USE,
                        "Validation passed; running usage recipe.",
                    )
                    try:
                        resolved_recipe = await self.project_manager.resolve_task_recipe_async(task.id)
                        use_result = await self._execute_use_recipe(resolved_recipe)
                        workflow_result["use"] = use_result
                    except Exception as exc:
                        success = self.project_manager.update_task_status(
                            task.id,
                            TaskStatus.FAILED,
                            f"Usage recipe failed: {exc}",
                        )
                        if not success:
                            logger.error(f"Failed to update task status to FAILED for task {task.id}")
                        return {
                            "task_id": task.id,
                            "task_title": task.title,
                            "status": "use_failed",
                            "final_status": TaskStatus.FAILED.value,
                            "error": str(exc),
                        }

                    if not use_result.get("success"):
                        success = self.project_manager.update_task_status(
                            task.id,
                            TaskStatus.FAILED,
                            "Usage recipe failed.",
                        )
                        if not success:
                            logger.error(f"Failed to update task status to FAILED for task {task.id}")
                        return {
                            "task_id": task.id,
                            "task_title": task.title,
                            "status": "use_failed",
                            "final_status": TaskStatus.FAILED.value,
                            "use_result": use_result,
                        }

                await self.project_manager.update_task_phase_async(
                    task.id,
                    TaskPhase.VERIFY,
                    "Validation passed; verifying completion artifacts.",
                )

                # 6. Create PR for validated task
                self._debug("Creating pull-request for validated task")
                pr_result = await self.git_manager.create_pr_for_task(task, validation_result)
                self._debug(f"PR creation result: {pr_result}")

                await self.project_manager.update_task_phase_async(
                    task.id,
                    TaskPhase.DONE,
                    "Validation succeeded; task is ready for review.",
                )

                # 7. Move the task into review-owned state.
                success = self.project_manager.update_task_status(
                    task.id,
                    TaskStatus.PENDING_REVIEW,
                    "Validation passed; awaiting review or trusted automatic completion.",
                )
                if not success:
                    raise Exception(f"Failed to update task status to PENDING_REVIEW")
                logger.info(
                    "Task '%s' marked as PENDING_REVIEW after validation. PR: %s",
                    task.title,
                    pr_result.get('pr_url'),
                )

                workflow_result['pr_result'] = pr_result
                workflow_result['final_status'] = TaskStatus.PENDING_REVIEW.value
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