"""High-level Git and GitHub workflow management.

This module uses GitIntegration for low-level Git operations and handles
the application-specific logic for creating branches and pull requests
based on task status.
"""

import logging
import subprocess
import asyncio
import json
from pathlib import Path
from typing import Any, Dict, Optional, Union

import requests
from penguin.config import GITHUB_REPOSITORY, GITHUB_TOKEN

from .git_integration import GitIntegration
from .manager import ProjectManager
from .models import Task, TaskStatus

logger = logging.getLogger(__name__)


class GitManager:
    """Orchestrates Git workflows for project tasks."""
    
    def __init__(
        self,
        workspace_path: Union[str, Path],
        project_manager: ProjectManager,
        repo_owner_and_name: Optional[str] = None,
    ):
        """
        Initialize the Git manager.
        
        Args:
            workspace_path: Path to the workspace root (Git repository).
            project_manager: The project manager instance.
            repo_owner_and_name: The owner and name of the repo (e.g., "my-org/my-repo").
                                 If None, it will be loaded from config.
        """
        self.workspace_path = Path(workspace_path)
        self.project_manager = project_manager
        self.repo_owner_and_name = repo_owner_and_name or GITHUB_REPOSITORY
        try:
            self.git_integration = GitIntegration(workspace_path)
        except Exception as e:
            logger.error(f"GitManager could not initialize GitIntegration: {e}")
            self.git_integration = None

    async def create_pr_for_task(self, task: Task, validation_results: Dict[str, Any]) -> Dict[str, Any]:
        """
        Creates a pull request for a completed and validated task.
        
        Args:
            task: The task object that has been completed.
            validation_results: The results from the ValidationManager.
            
        Returns:
            A dictionary with the result of the PR creation process.
        """
        if not self.git_integration:
            return {"status": "error", "message": "GitIntegration not available."}
            
        if not validation_results.get("validated", False):
            return {"status": "validation_failed", "message": "Validation failed. No PR created."}

        loop = asyncio.get_event_loop()

        changed_files = await loop.run_in_executor(None, self.git_integration.get_changed_files)
        if not changed_files:
            return {"status": "no_changes", "message": "No file changes to create a PR."}

        # 1. Create a new branch
        branch_name = self._create_branch_name(task)
        branch_created = await loop.run_in_executor(None, self.git_integration.create_branch, branch_name)
        if not branch_created:
            return {"status": "error", "message": f"Failed to create branch {branch_name}."}

        # 2. Commit the changes
        commit_message = self._create_commit_message(task, validation_results)
        commit_hash = await loop.run_in_executor(None, self.git_integration.commit, commit_message)
        if not commit_hash:
            return {"status": "error", "message": "Failed to commit changes."}
            
        # 3. Push the branch
        pushed = await loop.run_in_executor(None, self.git_integration.push_branch, branch_name)
        if not pushed:
            return {"status": "error", "message": f"Failed to push branch {branch_name}."}
            
        # 4. Create the Pull Request using the GitHub API
        pr_result = await self._create_pr_with_api(task, branch_name, validation_results)
            
        return pr_result

    def _create_branch_name(self, task: Task) -> str:
        """Creates a sanitized, unique branch name for a task."""
        sanitized_title = "".join(c for c in task.title.lower() if c.isalnum() or c in " ").replace(" ", "-")
        return f"feature/task-{task.id[:6]}-{sanitized_title[:40]}"

    def _create_commit_message(self, task: Task, validation_results: Dict[str, Any]) -> str:
        """Creates a conventional commit message for a task."""
        return f"feat(task): {task.title}\n\nTask-ID: {task.id}\nValidation: {validation_results.get('summary', 'N/A')}"

    def _create_pr_body(self, task: Task, validation_results: Dict[str, Any]) -> str:
        """Creates a formatted body for the pull request."""
        body = f"### ✅ Task Complete: {task.title}\n\n"
        body += f"**Description:**\n{task.description}\n\n"
        body += f"**Task ID:** `{task.id}`\n\n"
        body += f"### 🤖 Validation Results\n\n"
        body += f"**Summary:** {validation_results.get('summary', 'N/A')}\n\n"
        body += f"```\n{validation_results.get('details', 'No details available.')}\n```\n"
        return body

    async def _create_pr_with_api(self, task: Task, branch: str, validation_results: Dict[str, Any]) -> Dict[str, Any]:
        """Creates a pull request using the GitHub REST API."""
        if not self.repo_owner_and_name:
            return {"status": "error", "message": "GitHub repository (owner/repo) not configured."}
        if not GITHUB_TOKEN:
            return {"status": "error", "message": "GITHUB_TOKEN not set in environment."}

        url = f"https://api.github.com/repos/{self.repo_owner_and_name}/pulls"
        headers = {
            "Authorization": f"token {GITHUB_TOKEN}",
            "Accept": "application/vnd.github.v3+json",
        }
        data = {
            "title": f"feat(task): {task.title}",
            "body": self._create_pr_body(task, validation_results),
            "head": branch,
            "base": "main",  # Or make this configurable
        }

        loop = asyncio.get_event_loop()
        try:
            response = await loop.run_in_executor(
                None,
                lambda: requests.post(url, headers=headers, data=json.dumps(data), timeout=30)
            )
            response.raise_for_status()
            pr_data = response.json()
            pr_url = pr_data.get("html_url")
            return {
                "status": "created",
                "message": f"Pull request created: {pr_url}",
                "pr_url": pr_url
            }
        except requests.exceptions.RequestException as e:
            error_message = f"GitHub API request failed: {e}"
            if e.response is not None:
                error_message += f" | Response: {e.response.text}"
            logger.error(error_message)
            return {"status": "error", "message": error_message}
        except Exception as e:
            logger.error(f"An unexpected error occurred creating PR: {e}")
            return {"status": "error", "message": f"An unexpected error creating PR: {e}"} 