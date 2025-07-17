#!/usr/bin/env python3
"""
Test script to verify idempotency protection against duplicate PRs.
"""

import asyncio
import tempfile
import subprocess
import logging
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

# Set up logging
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

async def test_idempotency_protection():
    """Test that the system prevents duplicate PRs for the same task."""
    
    with tempfile.TemporaryDirectory() as tmp_dir:
        repo_path = Path(tmp_dir) / "penguin-test-repo"
        
        # Clone the repository
        logger.info(f"Cloning penguin-test-repo to {repo_path}")
        subprocess.run([
            "git", "clone", 
            "https://github.com/Maximooch/penguin-test-repo.git", 
            str(repo_path)
        ], check=True)
        
        # Create a mock RunMode
        mock_run_mode = MagicMock()
        timestamp = str(int(time.time()))
        
        async def mock_agent_run(*args, **kwargs):
            feature_file = repo_path / f"idempotency_test_{timestamp}.py"
            test_file = repo_path / f"test_idempotency_{timestamp}.py"
            
            feature_file.write_text(f"""def idempotency_test():
    \"\"\"Test feature for idempotency protection.\"\"\"
    return "This is test {timestamp}"
""")
            
            test_file.write_text(f"""def test_idempotency():
    from idempotency_test_{timestamp} import idempotency_test
    assert idempotency_test() == "This is test {timestamp}"
""")
            
            return {"status": "completed", "message": f"Idempotency test {timestamp} created."}
        
        mock_run_mode.start = AsyncMock(side_effect=mock_agent_run)
        
        # Initialize components
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
        
        # Create project and task
        project_spec = f"""
# Idempotency Test Project {timestamp}

## Tasks
- Create an idempotency test feature with comprehensive validation
"""
        
        parse_result = await parse_project_specification_from_markdown(
            markdown_content=project_spec,
            project_manager=project_manager
        )
        
        if parse_result["status"] != "success":
            logger.error(f"Failed to parse project: {parse_result}")
            return False
        
        tasks = await project_manager.list_tasks_async()
        if not tasks:
            logger.error("No tasks created")
            return False
        
        task = tasks[0]
        logger.info(f"Testing idempotency for task: {task.title}")
        
        # Run the workflow first time
        logger.info("=== FIRST RUN ===")
        result1 = await orchestrator.run_next_task()
        
        if not result1 or result1.get("final_status") != "COMPLETED":
            logger.error(f"First run failed: {result1}")
            return False
        
        pr_result1 = result1.get("pr_result")
        if not pr_result1 or pr_result1.get("status") != "created":
            logger.error(f"First PR creation failed: {pr_result1}")
            return False
        
        first_pr_url = pr_result1.get("pr_url")
        logger.info(f"First PR created successfully: {first_pr_url}")
        
        # Simulate trying to create PR again for the same task
        logger.info("=== SECOND RUN (Should detect existing PR) ===")
        
        # Create validation results similar to first run
        validation_results = {
            "validated": True,
            "summary": "Tests passed",
            "details": "All tests successful"
        }
        
        # Try to create PR again
        result2 = await git_manager.create_pr_for_task(task, validation_results)
        
        # Check that it detected the existing PR
        if result2.get("status") != "already_exists":
            logger.error(f"Expected 'already_exists' status, got: {result2}")
            return False
        
        second_pr_url = result2.get("pr_url")
        if second_pr_url != first_pr_url:
            logger.error(f"PR URLs don't match: {first_pr_url} vs {second_pr_url}")
            return False
        
        logger.info(f"✅ Idempotency check successful! Found existing PR: {second_pr_url}")
        logger.info(f"Found by: {result2.get('found_by')}")
        
        # Test with different branch name but same task ID
        logger.info("=== THIRD RUN (Different branch, same task ID) ===")
        
        # Manually create a different branch name
        different_branch = f"feature/different-branch-{timestamp}"
        result3 = await git_manager._create_pr_with_api(task, different_branch, validation_results)
        
        if result3.get("status") != "already_exists":
            logger.error(f"Expected to find existing PR by task ID, got: {result3}")
            return False
        
        logger.info(f"✅ Task ID check successful! Found existing PR: {result3.get('pr_url')}")
        logger.info(f"Found by: {result3.get('found_by')}")
        
        return True

if __name__ == "__main__":
    print("🐧 Testing Idempotency Protection...")
    print("=" * 60)
    
    success = asyncio.run(test_idempotency_protection())
    
    print("=" * 60)
    if success:
        print("✅ Idempotency protection test PASSED!")
        print("The system successfully prevents duplicate PRs.")
    else:
        print("❌ Idempotency protection test FAILED!")
    
    exit(0 if success else 1)