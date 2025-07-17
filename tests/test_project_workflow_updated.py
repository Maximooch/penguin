import asyncio
import pytest
import subprocess
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, PropertyMock
import logging

from github import GithubException

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
    # Use the actual test repo URL for clarity, though it's mocked.
    subprocess.run(["git", "remote", "add", "origin", "https://github.com/Maximooch/penguin-test-repo.git"], cwd=repo_path, check=True)
    (repo_path / "README.md").write_text("Initial commit")
    subprocess.run(["git", "add", "README.md"], cwd=repo_path, check=True)
    subprocess.run(["git", "commit", "-m", "Initial commit"], cwd=repo_path, check=True)
    return repo_path

async def test_full_mvp_workflow_updated(temp_workspace: Path, monkeypatch):
    """
    Tests the full MVP workflow from spec parsing to PR creation using PyGithub.
    """
    # 1. --- SETUP ---
    mock_run_mode = MagicMock()
    
    async def mock_agent_run(*args, **kwargs):
        (temp_workspace / "new_feature.py").write_text("print('hello world')")
        (temp_workspace / "test_new_feature.py").write_text(
            "def test_hello():\n    assert 'hello' == 'hello'"
        )
        return {"status": "completed", "message": "Agent finished successfully."}

    mock_run_mode.start = AsyncMock(side_effect=mock_agent_run)

    # Mock the PyGithub interaction
    mock_github_instance = MagicMock()
    mock_repo = MagicMock()
    mock_pull_request = MagicMock()
    mock_pull_request.html_url = "https://github.com/Maximooch/penguin-test-repo/pull/1"

    mock_repo.create_pull.return_value = mock_pull_request
    mock_github_instance.get_repo.return_value = mock_repo

    # Patch the Github class in the git_manager module.
    # When GitManager calls `Github(GITHUB_TOKEN)`, it will now return our mock instance.
    monkeypatch.setattr(
        "penguin.project.git_manager.Github",
        lambda token: mock_github_instance
    )

    def mock_git_push(*args, **kwargs):
        logger.info("Mocked git push, returning True")
        return True

    monkeypatch.setattr(
        "penguin.project.git_integration.GitIntegration.push_branch",
        mock_git_push
    )
    
    project_manager = ProjectManager(workspace_path=temp_workspace)
    git_manager = GitManager(
        workspace_path=temp_workspace,
        project_manager=project_manager,
        repo_owner_and_name="Maximooch/penguin-test-repo"
    )
    validation_manager = ValidationManager(workspace_path=temp_workspace)
    task_executor = ProjectTaskExecutor(
        run_mode=mock_run_mode, project_manager=project_manager, git_integration=git_manager.git_integration
    )
    orchestrator = WorkflowOrchestrator(
        project_manager=project_manager,
        task_executor=task_executor,
        validation_manager=validation_manager,
        git_manager=git_manager,
    )

    # 2. --- ACT ---
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

    workflow_result = await orchestrator.run_next_task()

    # 3. --- ASSERT ---
    assert workflow_result is not None, "Orchestrator should have found and run a task."
    assert workflow_result["final_status"] == "COMPLETED"
    assert "pr_result" in workflow_result
    assert workflow_result["pr_result"]["status"] == "created"
    assert "https://github.com" in workflow_result["pr_result"]["pr_url"]

    final_task = await project_manager.get_task_async(original_task_id)
    assert final_task.status == TaskStatus.COMPLETED

    assert (temp_workspace / "new_feature.py").exists()
    assert (temp_workspace / "test_new_feature.py").exists()

    current_branch = git_manager.git_integration.get_current_branch()
    assert current_branch != "main"
    
    log_output = subprocess.run(
        ["git", "log", "-1", "--pretty=%B"], 
        cwd=temp_workspace, 
        capture_output=True, 
        text=True
    ).stdout
    assert "feat(task)" in log_output
    assert tasks[0].title in log_output
