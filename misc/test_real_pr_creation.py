#!/usr/bin/env python3
"""
Real end-to-end test that creates an actual PR using the Penguin project system.
This test will create a real PR on the penguin-test-repo to verify PyGithub integration.
"""

import asyncio
import tempfile
import subprocess
import logging
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

# Set up logging to see what's happening
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

from penguin.project.manager import ProjectManager
from penguin.project.spec_parser import parse_project_specification_from_markdown
from penguin.project.workflow_orchestrator import WorkflowOrchestrator
from penguin.project.task_executor import ProjectTaskExecutor
from penguin.project.validation_manager import ValidationManager
from penguin.project.git_manager import GitManager
from penguin.project.models import TaskStatus

async def create_real_pr_test():
    """Create a real PR using the full Penguin workflow."""
    
    # Create a temporary directory to work in
    with tempfile.TemporaryDirectory() as tmp_dir:
        repo_path = Path(tmp_dir) / "penguin-test-repo"
        
        # Clone the actual test repository
        logger.info(f"Cloning penguin-test-repo to {repo_path}")
        subprocess.run([
            "git", "clone", 
            "https://github.com/Maximooch/penguin-test-repo.git", 
            str(repo_path)
        ], check=True)
        
        # Configure git user
        subprocess.run(["git", "config", "user.name", "Penguin Bot"], cwd=repo_path, check=True)
        subprocess.run(["git", "config", "user.email", "penguin@example.com"], cwd=repo_path, check=True)
        
        # Create a mock RunMode that simulates creating a simple feature
        mock_run_mode = MagicMock()
        
        async def mock_agent_run(*args, **kwargs):
            # Create a simple Python file with current timestamp to make it unique
            import time
            timestamp = str(int(time.time()))
            
            feature_file = repo_path / f"feature_{timestamp}.py"
            test_file = repo_path / f"test_feature_{timestamp}.py"
            
            feature_file.write_text(f"""def greet(name):
    \"\"\"A simple greeting function created by Penguin agent.\"\"\"
    return f"Hello, {{name}}! This is feature {timestamp}"

if __name__ == "__main__":
    print(greet("World"))
""")
            
            test_file.write_text(f"""import pytest
from feature_{timestamp} import greet

def test_greet():
    \"\"\"Test the greet function.\"\"\"
    result = greet("Test")
    assert "Hello, Test!" in result
    assert "{timestamp}" in result

def test_greet_empty():
    \"\"\"Test greet with empty string.\"\"\"
    result = greet("")
    assert "Hello, !" in result
""")
            
            logger.info(f"Created feature file: {feature_file}")
            logger.info(f"Created test file: {test_file}")
            
            return {"status": "completed", "message": f"Created feature {timestamp} successfully."}
        
        mock_run_mode.start = AsyncMock(side_effect=mock_agent_run)
        
        # Initialize the project system components
        project_manager = ProjectManager(workspace_path=repo_path)
        git_manager = GitManager(
            workspace_path=repo_path,
            project_manager=project_manager,
            repo_owner_and_name="Maximooch/penguin-test-repo"
        )
        validation_manager = ValidationManager(workspace_path=repo_path)
        task_executor = ProjectTaskExecutor(
            run_mode=mock_run_mode, 
            project_manager=project_manager, 
            git_integration=git_manager.git_integration
        )
        orchestrator = WorkflowOrchestrator(
            project_manager=project_manager,
            task_executor=task_executor,
            validation_manager=validation_manager,
            git_manager=git_manager,
        )
        
        # Create a project specification
        project_spec_content = """
# PyGithub Integration Test Project

## Overview
This is a test project to verify the PyGithub integration works correctly with real GitHub API calls.

## Tasks
- Create a simple Python feature with a greeting function and comprehensive tests
"""
        
        # Parse the project specification
        logger.info("Parsing project specification...")
        parse_result = await parse_project_specification_from_markdown(
            markdown_content=project_spec_content,
            project_manager=project_manager
        )
        
        if parse_result["status"] != "success":
            logger.error(f"Failed to parse project specification: {parse_result}")
            return False
        
        # Get the created task
        tasks = await project_manager.list_tasks_async()
        logger.info(f"Found {len(tasks)} tasks")
        
        if not tasks:
            logger.error("No tasks were created!")
            return False
        
        task = tasks[0]
        logger.info(f"Running task: {task.title}")
        
        # Run the workflow
        workflow_result = await orchestrator.run_next_task()
        
        if workflow_result is None:
            logger.error("Orchestrator returned None - no task was run")
            return False
        
        logger.info(f"Workflow result: {workflow_result}")
        
        # Check if the task completed successfully
        if workflow_result.get("final_status") != "COMPLETED":
            logger.error(f"Task did not complete successfully: {workflow_result}")
            return False
        
        # Check if PR was created
        pr_result = workflow_result.get("pr_result")
        if not pr_result:
            logger.error("No PR result found in workflow result")
            return False
        
        if pr_result.get("status") != "created":
            logger.error(f"PR was not created: {pr_result}")
            return False
        
        pr_url = pr_result.get("pr_url")
        if not pr_url:
            logger.error("No PR URL found in result")
            return False
        
        logger.info(f"✅ SUCCESS! PR created: {pr_url}")
        
        # Verify the task is marked as completed
        final_task = await project_manager.get_task_async(task.id)
        if final_task.status != TaskStatus.COMPLETED:
            logger.error(f"Task status is {final_task.status}, expected COMPLETED")
            return False
        
        logger.info("✅ Task marked as completed successfully")
        
        return True

if __name__ == "__main__":
    print("🐧 Creating real PR with Penguin project system...")
    print("=" * 60)
    
    success = asyncio.run(create_real_pr_test())
    
    print("=" * 60)
    if success:
        print("✅ Real PR creation test PASSED!")
        print("Check https://github.com/Maximooch/penguin-test-repo/pulls for the new PR")
    else:
        print("❌ Real PR creation test FAILED!")
    
    exit(0 if success else 1)