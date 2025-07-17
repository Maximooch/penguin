import asyncio
import pytest
import subprocess
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock
import logging

logger = logging.getLogger(__name__)

# Adjust imports based on your project structure
from penguin.project.manager import ProjectManager
from penguin.project.spec_parser import parse_project_specification_from_markdown
from penguin.project.workflow_orchestrator import WorkflowOrchestrator
from penguin.project.task_executor import ProjectTaskExecutor
from penguin.project.validation_manager import ValidationManager
from penguin.project.git_manager import GitManager
from penguin.project.models import TaskStatus

# Marks all tests in this file as asyncio tests
pytestmark = pytest.mark.asyncio

@pytest.fixture
def temp_workspace(tmp_path: Path) -> Path:
    """Create a temporary workspace and initialize it as a Git repository."""
    repo_path = tmp_path / "test_repo"
    repo_path.mkdir()
    subprocess.run(["git", "init"], cwd=repo_path, check=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=repo_path, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo_path, check=True)
    # Add a dummy remote URL so `git push` has a destination.
    subprocess.run(["git", "remote", "add", "origin", "https://github.com/test-org/test-repo.git"], cwd=repo_path, check=True)
    # Create an initial commit so we can create branches
    (repo_path / "README.md").write_text("Initial commit")
    subprocess.run(["git", "add", "README.md"], cwd=repo_path, check=True)
    subprocess.run(["git", "commit", "-m", "Initial commit"], cwd=repo_path, check=True)
    return repo_path

async def test_full_mvp_workflow(temp_workspace: Path, monkeypatch):
    """
    Tests the full MVP workflow from spec parsing to PR creation.
    """
    # 1. --- SETUP ---
    # Mock external dependencies
    mock_run_mode = MagicMock()
    
    # This is the function that simulates the agent's work
    async def mock_agent_run(*args, **kwargs):
        # Create a new file in the workspace to simulate agent work
        (temp_workspace / "new_feature.py").write_text("print('hello world')")
        # Create a test file for the new feature
        (temp_workspace / "test_new_feature.py").write_text(
            "def test_hello():\n    assert 'hello' == 'hello'"
        )
        return {"status": "completed", "message": "Agent finished successfully."}

    mock_run_mode.start = AsyncMock(side_effect=mock_agent_run)

    # Mock the `gh` CLI call in GitManager
    def mock_gh_pr_create(*args, **kwargs):
        pr_url = "https://github.com/test-org/test-repo/pull/1"
        logger.info(f"Mocked gh pr create, returning: {pr_url}")
        return {"status": "created", "pr_url": pr_url}

    # Mock the git push operation
    def mock_git_push(*args, **kwargs):
        logger.info("Mocked git push, returning True")
        return True

    # We need to find the right object to patch.
    # It will be the `_create_pr_with_gh_cli` method in the GitManager instance.
    monkeypatch.setattr(
        "penguin.project.git_manager.GitManager._create_pr_with_gh_cli",
        mock_gh_pr_create
    )
    monkeypatch.setattr(
        "penguin.project.git_integration.GitIntegration.push_branch",
        mock_git_push
    )
    
    # Initialize all managers
    project_manager = ProjectManager(workspace_path=temp_workspace)
    # The GitManager needs the repo owner and name for the gh command
    # We are mocking the gh command, but it's good practice to set it.
    git_manager = GitManager(
        workspace_path=temp_workspace,
        project_manager=project_manager,
        repo_owner_and_name="test-org/test-repo"
    )
    validation_manager = ValidationManager(workspace_path=temp_workspace)
    task_executor = ProjectTaskExecutor(
        run_mode=mock_run_mode, project_manager=project_manager
    )
    orchestrator = WorkflowOrchestrator(
        project_manager=project_manager,
        task_executor=task_executor,
        validation_manager=validation_manager,
        git_manager=git_manager,
    )

    # 2. --- ACT ---
    # Step 2a: Parse a project spec to create a task
    project_spec_content = """
# New Feature Project
## Tasks
- Create a new feature and a test for it.
"""
    parse_result = await parse_project_specification_from_markdown(
        markdown_content=project_spec_content,
        project_manager=project_manager
    )
    assert parse_result["status"] == "success"
    tasks = await project_manager.list_tasks_async()
    assert len(tasks) == 1
    original_task_id = tasks[0].id

    # Step 2b: Run the full workflow for the next available task
    workflow_result = await orchestrator.run_next_task()

    # 3. --- ASSERT ---
    assert workflow_result is not None, "Orchestrator should have found and run a task."
    assert workflow_result["final_status"] == "COMPLETED"
    assert "pull_request" in workflow_result
    assert workflow_result["pull_request"]["status"] == "created"
    assert "https://github.com" in workflow_result["pull_request"]["pr_url"]

    # Verify the task status in the database
    final_task = await project_manager.get_task_async(original_task_id)
    assert final_task.status == TaskStatus.COMPLETED
    assert "Workflow successful" in final_task.transition_history[-1].reason

    # Verify that the agent's work (the files) exist
    assert (temp_workspace / "new_feature.py").exists()
    assert (temp_workspace / "test_new_feature.py").exists()

    # Verify that the git branch was created and has the commits
    current_branch = git_manager.git_integration.get_current_branch()
    assert current_branch != "main" # The PR should be on a feature branch
    
    log_output = subprocess.run(
        ["git", "log", "-1", "--pretty=%B"], 
        cwd=temp_workspace, 
        capture_output=True, 
        text=True
    ).stdout
    assert "feat(task)" in log_output
    assert tasks[0].title in log_output 