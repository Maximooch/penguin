import asyncio
import pytest
import subprocess
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock
import logging
import os
import shutil
import time
import sys

# Add the project root to the path to allow imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from penguin.config import GITHUB_REPOSITORY, GITHUB_TOKEN, WORKSPACE_PATH
from penguin.project.manager import ProjectManager
from penguin.project.spec_parser import parse_project_specification_from_markdown
from penguin.project.workflow_orchestrator import WorkflowOrchestrator
from penguin.project.task_executor import ProjectTaskExecutor
from penguin.project.validation_manager import ValidationManager
from penguin.project.git_manager import GitManager
from penguin.run_mode import RunMode
from penguin.project.models import TaskStatus

logger = logging.getLogger(__name__)
pytestmark = pytest.mark.asyncio

# --- Fixtures ---

@pytest.fixture(scope="module")
def event_loop():
    """Create an instance of the default event loop for each test module."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()

@pytest.fixture(scope="module")
def test_repo_path(tmp_path_factory):
    """Clones the test repo into a temporary directory for the test module."""
    if not GITHUB_REPOSITORY or not GITHUB_TOKEN:
        pytest.fail("GITHUB_REPOSITORY and GITHUB_TOKEN must be set in your .env file for this test.")

    repo_url = f"https://{GITHUB_TOKEN}@github.com/{GITHUB_REPOSITORY}.git"
    temp_dir = tmp_path_factory.mktemp("real_git_test")
    
    try:
        subprocess.run(
            ["git", "clone", repo_url, str(temp_dir)],
            check=True,
            capture_output=True,
            text=True
        )
        # Configure git user for the test repo
        subprocess.run(["git", "config", "user.name", "Penguin Test Bot"], cwd=temp_dir, check=True)
        subprocess.run(["git", "config", "user.email", "bot@penguin.ai"], cwd=temp_dir, check=True)
        # Create an initial commit so we can create branches
        (temp_dir / "README.md").write_text("Initial commit")
        subprocess.run(["git", "add", "README.md"], cwd=temp_dir, check=True)
        subprocess.run(["git", "commit", "-m", "Initial commit"], cwd=temp_dir, check=True)
    except subprocess.CalledProcessError as e:
        pytest.fail(f"Failed to clone test repository. Ensure token has repo access. Error: {e.stderr}")
        
    return temp_dir

# --- Test ---

async def test_end_to_end_pr_creation(test_repo_path: Path):
    """
    Tests the full, production-ready workflow:
    - Parses a spec file.
    - Runs a (mocked) agent that creates a real file.
    - Validates the work.
    - Commits the file to a new branch.
    - Pushes the branch.
    - Creates a real pull request on the test repository.
    """
    # 1. --- SETUP ---
    # Define a unique filename for this test run to avoid conflicts
    unique_filename = f"feature_{int(time.time())}.py"
    spec_content = f"""
# Test Feature
## Tasks
- Create the file `{unique_filename}`.
"""
    
    # Mock the agent's execution to create a specific file
    mock_run_mode = MagicMock(spec=RunMode)
    async def mock_agent_run(*args, **kwargs):
        (test_repo_path / unique_filename).write_text("print('This is a new feature!')")
        return {"status": "completed", "message": "Agent created a new file."}
    mock_run_mode.start = AsyncMock(side_effect=mock_agent_run)

    # Initialize all real managers
    project_manager = ProjectManager(workspace_path=test_repo_path)
    git_manager = GitManager(
        workspace_path=test_repo_path,
        project_manager=project_manager,
        repo_owner_and_name=GITHUB_REPOSITORY
    )
    validation_manager = ValidationManager(workspace_path=test_repo_path)
    task_executor = ProjectTaskExecutor(
        run_mode=mock_run_mode, 
        project_manager=project_manager,
        git_integration=git_manager.git_integration # Use the same GitIntegration instance
    )
    orchestrator = WorkflowOrchestrator(
        project_manager=project_manager,
        task_executor=task_executor,
        validation_manager=validation_manager,
        git_manager=git_manager,
    )

    # 2. --- ACT ---
    # Parse the spec to create the task
    parse_result = await parse_project_specification_from_markdown(
        markdown_content=spec_content,
        project_manager=project_manager
    )
    assert parse_result["status"] == "success"

    # Run the orchestrator to execute the workflow
    workflow_result = await orchestrator.run_next_task()

    # 3. --- ASSERT ---
    assert workflow_result is not None, "Orchestrator should have returned a result"
    assert workflow_result.get("final_status") == "COMPLETED"
    
    pr_result = workflow_result.get("pr_result", {})
    assert pr_result.get("status") == "created"
    pr_url = pr_result.get("pr_url")
    assert pr_url is not None and GITHUB_REPOSITORY.lower() in pr_url.lower()

    print(f"✅ Successfully created Pull Request: {pr_url}")

    # --- Cleanup ---
    # Optional: You might want to locally delete the branch created during the test.
    # The PR will need to be closed manually on GitHub for now.
    try:
        branch_name = git_manager._create_branch_name(await project_manager.get_task_async(workflow_result['task_id']))
        subprocess.run(["git", "checkout", "main"], cwd=test_repo_path, check=True)
        subprocess.run(["git", "branch", "-D", branch_name], cwd=test_repo_path)
        print(f"🧹 Cleaned up local branch: {branch_name}")
    except Exception as e:
        print(f"⚠️  Could not clean up local branch: {e}") 