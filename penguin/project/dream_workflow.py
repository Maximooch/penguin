"""Dream Workflow Implementation for Penguin.

This module orchestrates the complete workflow described in dream.md:
0. Natural language project specification
1. Context prioritization and task breakdown
2. Agent delegation
3. Verifiable rewards through testing
4. Human approval via version control
"""

import asyncio
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from .spec_parser import ProjectSpecificationParser
from .validation_manager import ValidationManager
from .git_manager import GitManager
from .task_executor import ProjectTaskExecutor

logger = logging.getLogger(__name__)


class DreamWorkflow:
    """Orchestrates the complete dream.md workflow from specification to approved completion."""
    
    def __init__(
        self,
        engine,
        project_manager,
        conversation_manager,
        run_mode,
        workspace_path: Union[str, Path]
    ):
        """Initialize the dream workflow.
        
        Args:
            engine: Engine instance for LLM processing
            project_manager: ProjectManager instance
            conversation_manager: ConversationManager instance
            run_mode: RunMode instance for task execution
            workspace_path: Path to workspace root
        """
        self.engine = engine
        self.project_manager = project_manager
        self.conversation_manager = conversation_manager
        self.run_mode = run_mode
        self.workspace_path = Path(workspace_path)
        
        # Initialize workflow components
        self.spec_parser = ProjectSpecificationParser(engine, project_manager)
        self.validation_manager = ValidationManager(workspace_path, engine)
        self.git_manager = GitManager(workspace_path)
        self.task_executor = ProjectTaskExecutor(
            run_mode, project_manager, conversation_manager, self.validation_manager
        )
        
        logger.info("Dream workflow initialized")
    
    async def execute_dream_workflow(
        self,
        specification: str,
        project_name: Optional[str] = None,
        context_files: Optional[List[str]] = None,
        auto_execute: bool = True,
        require_approval: bool = True
    ) -> Dict[str, Any]:
        """Execute the complete dream workflow from specification to completion.
        
        Args:
            specification: Natural language project description
            project_name: Optional project name override
            context_files: Optional context files to include
            auto_execute: Whether to automatically execute tasks
            require_approval: Whether to require human approval
            
        Returns:
            Dictionary with complete workflow results
        """
        workflow_id = f"dream_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        logger.info(f"Starting dream workflow: {workflow_id}")
        
        workflow_result = {
            "workflow_id": workflow_id,
            "status": "started",
            "timestamp": datetime.utcnow().isoformat(),
            "steps": {},
            "project_id": None,
            "tasks_completed": 0,
            "total_tasks": 0
        }
        
        try:
            # Point 0: Parse natural language specification
            logger.info("Step 0: Parsing project specification")
            parse_result = await self.spec_parser.parse_project_specification(
                specification, project_name, context_files
            )
            workflow_result["steps"]["0_specification_parsing"] = parse_result
            
            if parse_result["status"] != "success":
                workflow_result["status"] = "failed"
                workflow_result["error"] = "Failed to parse specification"
                return workflow_result
            
            project_id = parse_result["creation_result"]["project"]["id"]
            workflow_result["project_id"] = project_id
            workflow_result["total_tasks"] = parse_result["creation_result"]["tasks_created"]
            
            # Point 1: Context prioritization (handled by TaskExecutor)
            logger.info("Step 1: Context prioritization ready")
            workflow_result["steps"]["1_context_prioritization"] = {
                "status": "ready",
                "message": "Context manager will prioritize during execution"
            }
            
            if auto_execute:
                # Point 2: Agent delegation and execution
                logger.info("Step 2: Executing tasks with agent delegation")
                execution_result = await self.task_executor.execute_project_tasks(
                    project_id=project_id,
                    max_concurrent=2,
                    stop_on_failure=False
                )
                workflow_result["steps"]["2_agent_delegation"] = execution_result
                workflow_result["tasks_completed"] = execution_result.get("completed_tasks", 0)
                
                # Point 3 & 4: Validation and approval for each completed task
                if require_approval:
                    logger.info("Step 3&4: Validation and approval workflow")
                    approval_results = await self._process_task_approvals(project_id)
                    workflow_result["steps"]["3_4_validation_approval"] = approval_results
                else:
                    workflow_result["steps"]["3_4_validation_approval"] = {
                        "status": "skipped",
                        "message": "Approval not required"
                    }
            else:
                workflow_result["steps"]["2_agent_delegation"] = {
                    "status": "skipped",
                    "message": "Auto-execution disabled"
                }
                workflow_result["steps"]["3_4_validation_approval"] = {
                    "status": "skipped",
                    "message": "Auto-execution disabled"
                }
            
            workflow_result["status"] = "completed"
            logger.info(f"Dream workflow completed: {workflow_id}")
            return workflow_result
            
        except Exception as e:
            logger.error(f"Dream workflow failed: {e}")
            workflow_result["status"] = "error"
            workflow_result["error"] = str(e)
            return workflow_result
    
    async def _process_task_approvals(self, project_id: str) -> Dict[str, Any]:
        """Process validation and approval for all completed tasks in a project."""
        try:
            # Get completed tasks
            from ..models import TaskStatus
            completed_tasks = self.project_manager.list_tasks(
                project_id=project_id,
                status=TaskStatus.COMPLETED
            )
            
            approval_results = {
                "total_tasks": len(completed_tasks),
                "validated_tasks": 0,
                "approved_tasks": 0,
                "rejected_tasks": 0,
                "task_results": []
            }
            
            for task in completed_tasks:
                task_result = await self._process_single_task_approval(task)
                approval_results["task_results"].append(task_result)
                
                if task_result.get("validated"):
                    approval_results["validated_tasks"] += 1
                
                if task_result.get("approval_status") == "approved":
                    approval_results["approved_tasks"] += 1
                elif task_result.get("approval_status") == "rejected":
                    approval_results["rejected_tasks"] += 1
            
            return {
                "status": "completed",
                "results": approval_results
            }
            
        except Exception as e:
            logger.error(f"Error processing task approvals: {e}")
            return {
                "status": "error",
                "message": str(e)
            }
    
    async def _process_single_task_approval(self, task) -> Dict[str, Any]:
        """Process validation and approval workflow for a single task."""
        try:
            logger.info(f"Processing approval for task: {task.title}")
            
            # Point 3: Validate task completion
            validation_context = {
                "task_id": task.id,
                "task_title": task.title,
                "task_description": task.description,
                "acceptance_criteria": task.acceptance_criteria
            }
            
            validation_result = await self.validation_manager.validate_task_completion(
                validation_context
            )
            
            task_result = {
                "task_id": task.id,
                "task_title": task.title,
                "validated": validation_result.get("validated", False),
                "validation_score": validation_result.get("overall_score", 0.0),
                "validation_summary": validation_result.get("summary", "")
            }
            
            # Point 4: Git-based approval workflow
            if validation_result.get("validated", False):
                # Create approval branch
                branch_result = await self.git_manager.create_approval_branch(
                    task.id, task.title
                )
                
                # Commit task completion with validation
                commit_result = await self.git_manager.commit_task_completion(
                    task.id, task.title, validation_result
                )
                
                # Request human approval
                approval_request = await self.git_manager.request_human_approval(
                    task.id, task.title, validation_result
                )
                
                task_result.update({
                    "branch_created": branch_result.get("status") == "created",
                    "branch_name": branch_result.get("branch_name"),
                    "commit_hash": commit_result.get("commit_hash"),
                    "approval_requested": approval_request.get("status") == "requested",
                    "approval_status": "pending",
                    "approval_file": approval_request.get("approval_file")
                })
            else:
                task_result.update({
                    "branch_created": False,
                    "approval_requested": False,
                    "approval_status": "validation_failed",
                    "reason": "Task did not pass validation"
                })
            
            return task_result
            
        except Exception as e:
            logger.error(f"Error processing task approval: {e}")
            return {
                "task_id": task.id,
                "task_title": task.title,
                "error": str(e),
                "approval_status": "error"
            }
    
    async def check_and_finalize_approvals(self, project_id: str) -> Dict[str, Any]:
        """Check approval status and finalize approved tasks.
        
        Args:
            project_id: ID of the project to check
            
        Returns:
            Dictionary with finalization results
        """
        try:
            from ..models import TaskStatus
            completed_tasks = self.project_manager.list_tasks(
                project_id=project_id,
                status=TaskStatus.COMPLETED
            )
            
            finalization_results = {
                "checked_tasks": 0,
                "approved_tasks": 0,
                "rejected_tasks": 0,
                "finalized_tasks": 0,
                "task_statuses": []
            }
            
            for task in completed_tasks:
                finalization_results["checked_tasks"] += 1
                
                # Check approval status
                approval_status = await self.git_manager.check_approval_status(task.id)
                
                task_status = {
                    "task_id": task.id,
                    "task_title": task.title,
                    "approval_status": approval_status.get("status")
                }
                
                if approval_status.get("status") == "approved":
                    finalization_results["approved_tasks"] += 1
                    
                    # Finalize the approved task
                    finalize_result = await self.git_manager.finalize_approved_task(task.id)
                    task_status["finalized"] = finalize_result.get("status") == "finalized"
                    
                    if task_status["finalized"]:
                        finalization_results["finalized_tasks"] += 1
                
                elif approval_status.get("status") == "rejected":
                    finalization_results["rejected_tasks"] += 1
                    task_status["rejection_reason"] = approval_status.get("content", "")
                
                finalization_results["task_statuses"].append(task_status)
            
            return {
                "status": "completed",
                "project_id": project_id,
                "results": finalization_results
            }
            
        except Exception as e:
            logger.error(f"Error checking approvals: {e}")
            return {
                "status": "error",
                "message": str(e)
            }
    
    async def get_workflow_status(self, workflow_id: str) -> Dict[str, Any]:
        """Get the current status of a dream workflow.
        
        Args:
            workflow_id: ID of the workflow to check
            
        Returns:
            Dictionary with workflow status
        """
        # This is a placeholder - in a real implementation, you'd persist
        # workflow state and retrieve it here
        return {
            "workflow_id": workflow_id,
            "status": "not_implemented",
            "message": "Workflow status tracking not yet implemented"
        }


# Convenience function for direct usage
async def execute_dream_workflow(
    specification: str,
    engine,
    project_manager,
    conversation_manager,
    run_mode,
    workspace_path: Union[str, Path],
    project_name: Optional[str] = None,
    context_files: Optional[List[str]] = None,
    auto_execute: bool = True,
    require_approval: bool = True
) -> Dict[str, Any]:
    """Convenience function to execute the dream workflow.
    
    Args:
        specification: Natural language project description
        engine: Engine instance
        project_manager: ProjectManager instance
        conversation_manager: ConversationManager instance
        run_mode: RunMode instance
        workspace_path: Path to workspace root
        project_name: Optional project name override
        context_files: Optional context files to include
        auto_execute: Whether to automatically execute tasks
        require_approval: Whether to require human approval
        
    Returns:
        Dictionary with complete workflow results
    """
    workflow = DreamWorkflow(
        engine, project_manager, conversation_manager, run_mode, workspace_path
    )
    return await workflow.execute_dream_workflow(
        specification, project_name, context_files, auto_execute, require_approval
    ) 