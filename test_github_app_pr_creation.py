#!/usr/bin/env python3
"""
Test script to create a real PR using GitHub App authentication.
"""

import asyncio
import tempfile
import subprocess
import logging
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

# Set up logging to see what's happening
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

import sys
sys.path.insert(0, str(Path(__file__).parent))

from penguin.project.manager import ProjectManager
from penguin.project.spec_parser import parse_project_specification_from_markdown
from penguin.project.workflow_orchestrator import WorkflowOrchestrator
from penguin.project.task_executor import ProjectTaskExecutor
from penguin.project.validation_manager import ValidationManager
from penguin.project.git_manager import GitManager
from penguin.project.models import TaskStatus

async def test_github_app_pr_creation():
    """Test creating a PR with GitHub App authentication."""
    
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
        
        # Git user identity will be automatically configured by GitIntegration to match GitHub App
        
        # Create a mock RunMode that simulates creating a feature with timestamp
        mock_run_mode = MagicMock()
        
        timestamp = str(int(time.time()))
        
        async def mock_agent_run(*args, **kwargs):
            # Create a unique feature file
            feature_file = repo_path / f"github_app_feature_{timestamp}.py"
            test_file = repo_path / f"test_github_app_feature_{timestamp}.py"
            
            feature_file.write_text(f"""# GitHub App Authentication Test Feature
# Generated at {timestamp}

def github_app_greeting(name):
    \"\"\"A greeting function created by Penguin using GitHub App authentication.\"\"\"
    return f"Hello from GitHub App, {{name}}! Feature created at {timestamp}"

def get_timestamp():
    \"\"\"Return the creation timestamp.\"\"\"
    return "{timestamp}"

if __name__ == "__main__":
    print(github_app_greeting("World"))
    print(f"Created at: {{get_timestamp()}}")
""")
            
            test_file.write_text(f"""# Tests for GitHub App Authentication Feature
import pytest
from github_app_feature_{timestamp} import github_app_greeting, get_timestamp

def test_github_app_greeting():
    \"\"\"Test the GitHub App greeting function.\"\"\"
    result = github_app_greeting("Test User")
    assert "Hello from GitHub App, Test User!" in result
    assert "{timestamp}" in result

def test_get_timestamp():
    \"\"\"Test the timestamp function.\"\"\"
    assert get_timestamp() == "{timestamp}"

def test_greeting_with_special_characters():
    \"\"\"Test greeting with special characters.\"\"\"
    result = github_app_greeting("Test@User.com")
    assert "Hello from GitHub App, Test@User.com!" in result
""")
            
            logger.info(f"Created GitHub App feature file: {feature_file}")
            logger.info(f"Created GitHub App test file: {test_file}")
            
            return {
                "status": "completed", 
                "message": f"GitHub App feature {timestamp} created successfully with comprehensive tests."
            }
        
        mock_run_mode.start = AsyncMock(side_effect=mock_agent_run)
        
        # Initialize the project system components
        project_manager = ProjectManager(workspace_path=repo_path)
        git_manager = GitManager(
            workspace_path=repo_path,
            project_manager=project_manager,
            repo_owner_and_name="Maximooch/penguin-test-repo"
        )
        
        # Check what authentication method is being used
        logger.info(f"GitHub client type: {type(git_manager.github)}")
        if git_manager.github:
            try:
                user = git_manager.github.get_user()
                logger.info(f"Authenticated as: {user.login}")
            except Exception as e:
                logger.error(f"Failed to get authenticated user: {e}")
        
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
        
        # Create a unique project specification
        project_spec_content = f"""
# GitHub App PR Test Project {timestamp}

## Overview
This project tests GitHub App authentication for PR creation.
Generated at: {timestamp}

## Tasks
- Create a comprehensive GitHub App authentication test feature with greeting functionality and timestamp tracking
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
    print("🐧 Testing GitHub App PR Creation...")
    print("=" * 70)
    
    success = asyncio.run(test_github_app_pr_creation())
    
    print("=" * 70)
    if success:
        print("✅ GitHub App PR creation test PASSED!")
        print("Check https://github.com/Maximooch/penguin-test-repo/pulls for the new PR")
        print("The PR should be created by your GitHub App bot account!")
    else:
        print("❌ GitHub App PR creation test FAILED!")
    
    exit(0 if success else 1)