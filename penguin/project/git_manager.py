"""High-level Git and GitHub workflow management.

This module uses GitIntegration for low-level Git operations and handles
the application-specific logic for creating branches and pull requests
based on task status.
"""

import logging
import subprocess
import asyncio
import time
import jwt
from pathlib import Path
from typing import Any, Dict, Optional, Union

from github import Github, GithubException
from penguin.config import (
    GITHUB_REPOSITORY, 
    GITHUB_TOKEN, 
    GITHUB_APP_ID, 
    GITHUB_APP_PRIVATE_KEY_PATH, 
    GITHUB_APP_INSTALLATION_ID
)

from .git_integration import GitIntegration
from .manager import ProjectManager
from .models import Task, TaskStatus
from .resilience import resilient_operation, RetryStrategy, CircuitBreaker, safe_operation

logger = logging.getLogger(__name__)


def _get_github_app_client(app_id: str, private_key_path: str, installation_id: str) -> Optional[Github]:
    """
    Create a GitHub client using GitHub App authentication.
    
    Args:
        app_id: The GitHub App ID
        private_key_path: Path to the private key file
        installation_id: The installation ID
        
    Returns:
        Github client instance or None if authentication fails
    """
    try:
        # Read the private key
        with open(private_key_path, 'r') as key_file:
            private_key = key_file.read()
        
        # Use the newer PyGithub authentication API
        from github import Auth
        
        # Create AppAuth instance
        auth = Auth.AppAuth(app_id, private_key)
        
        # Create GitHub client with app authentication
        github_client = Github(auth=auth)
        
        # Get the installation and create an installation auth
        installation = github_client.get_app().get_installation(int(installation_id))
        installation_auth = auth.get_installation_auth(installation.id)
        
        # Return client with installation auth
        return Github(auth=installation_auth)
        
    except Exception as e:
        logger.error(f"Failed to create GitHub App client: {e}")
        return None


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
        
        # Initialize GitHub client with priority: GitHub App > Personal Access Token
        self.github = self._initialize_github_client()
        
        try:
            self.git_integration = GitIntegration(workspace_path)
        except Exception as e:
            logger.error(f"GitManager could not initialize GitIntegration: {e}")
            self.git_integration = None
    
    def _initialize_github_client(self) -> Optional[Github]:
        """
        Initialize GitHub client using GitHub App authentication or fallback to PAT.
        
        Returns:
            Github client instance or None if authentication fails
        """
        # Try GitHub App authentication first
        if all([GITHUB_APP_ID, GITHUB_APP_PRIVATE_KEY_PATH, GITHUB_APP_INSTALLATION_ID]):
            logger.info("Attempting GitHub App authentication...")
            github_client = _get_github_app_client(
                GITHUB_APP_ID, 
                GITHUB_APP_PRIVATE_KEY_PATH, 
                GITHUB_APP_INSTALLATION_ID
            )
            if github_client:
                logger.info("Successfully authenticated with GitHub App")
                return github_client
            else:
                logger.warning("GitHub App authentication failed, falling back to PAT")
        
        # Fallback to Personal Access Token
        if GITHUB_TOKEN:
            logger.info("Using GitHub Personal Access Token authentication")
            return Github(GITHUB_TOKEN)
        
        logger.warning("No GitHub authentication configured. GitHub integration will be disabled.")
        return None

    async def create_pr_for_task(self, task: Task, validation_results: Dict[str, Any]) -> Dict[str, Any]:
        """
        Creates a pull request for a completed and validated task with idempotency.
        
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

        # Check for existing PR first (early idempotency check)
        branch_name = self._create_branch_name(task)
        existing_pr = self._check_existing_pr(branch_name, task.id)
        if existing_pr:
            logger.info(f"PR already exists for task {task.id}, skipping creation")
            return {
                "status": "already_exists",
                "message": f"Pull request already exists: {existing_pr['pr_url']}",
                "pr_url": existing_pr["pr_url"],
                "pr_number": existing_pr["pr_number"],
                "found_by": existing_pr["found_by"]
            }

        changed_files = await loop.run_in_executor(None, self.git_integration.get_changed_files)
        if not changed_files:
            return {"status": "no_changes", "message": "No file changes to create a PR."}

        # 1. Create a new branch
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
            
        # 4. Create the Pull Request using the GitHub API (with idempotency check)
        pr_result = await self._create_pr_with_api(task, branch_name, validation_results)
            
        return pr_result

    def _create_branch_name(self, task: Task) -> str:
        """Creates a sanitized, unique branch name for a task."""
        import time
        
        # Use first 6 characters of task ID for uniqueness
        task_short_id = task.id[:6] if task.id else "unknown"
        
        # Sanitize title for branch name
        sanitized_title = "".join(c for c in task.title.lower() if c.isalnum() or c in " ").replace(" ", "-")
        sanitized_title = sanitized_title[:30]  # Limit length
        
        # Add timestamp for extra uniqueness (helps prevent conflicts)
        timestamp = int(time.time())
        
        return f"feature/task-{task_short_id}-{sanitized_title}-{timestamp}"

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
    
    def _check_existing_pr(self, branch: str, task_id: str) -> Optional[Dict[str, Any]]:
        """
        Check if a PR already exists for this branch or task.
        
        Args:
            branch: Branch name to check
            task_id: Task ID to check in PR bodies
            
        Returns:
            Dict with PR info if found, None otherwise
        """
        if not self.github or not self.repo_owner_and_name:
            return None
        
        try:
            repo = self.github.get_repo(self.repo_owner_and_name)
            
            # First check for PRs with the same branch
            pulls = repo.get_pulls(state='open', head=f"{repo.owner.login}:{branch}")
            
            for pr in pulls:
                if pr.head.ref == branch:
                    logger.info(f"Found existing PR for branch {branch}: {pr.html_url}")
                    return {
                        "pr_url": pr.html_url,
                        "pr_number": pr.number,
                        "found_by": "branch_name"
                    }
            
            # Also check for PRs with the same task ID in the body
            all_open_prs = repo.get_pulls(state='open')
            for pr in all_open_prs:
                if pr.body and f"**Task ID:** `{task_id}`" in pr.body:
                    logger.info(f"Found existing PR for task {task_id}: {pr.html_url}")
                    return {
                        "pr_url": pr.html_url,
                        "pr_number": pr.number,
                        "found_by": "task_id"
                    }
            
            return None
            
        except Exception as e:
            logger.warning(f"Error checking for existing PR: {e}")
            return None

    async def _create_pr_with_api(self, task: Task, branch: str, validation_results: Dict[str, Any]) -> Dict[str, Any]:
        """Creates a pull request using the PyGithub library with idempotency check."""
        if not self.github or not self.repo_owner_and_name:
            return {"status": "error", "message": "GitHub integration not configured."}

        # Check if PR already exists (idempotency check)
        existing_pr = self._check_existing_pr(branch, task.id)
        if existing_pr:
            logger.info(f"PR already exists for task {task.id}, returning existing PR")
            return {
                "status": "already_exists",
                "message": f"Pull request already exists: {existing_pr['pr_url']}",
                "pr_url": existing_pr["pr_url"],
                "pr_number": existing_pr["pr_number"],
                "found_by": existing_pr["found_by"]
            }

        try:
            repo = self.github.get_repo(self.repo_owner_and_name)
            pull_request = repo.create_pull(
                title=f"feat(task): {task.title}",
                body=self._create_pr_body(task, validation_results),
                head=branch,
                base="main",  # Or make this configurable
            )
            
            logger.info(f"Successfully created new PR for task {task.id}: {pull_request.html_url}")
            return {
                "status": "created",
                "message": f"Pull request created: {pull_request.html_url}",
                "pr_url": pull_request.html_url,
                "pr_number": pull_request.number
            }
            
        except GithubException as e:
            logger.error(f"GitHub API error creating pull request: {e}")
            
            # Check if this is a "already exists" error and handle gracefully
            if hasattr(e, 'data') and isinstance(e.data, dict):
                error_message = e.data.get('message', '').lower()
                if 'already exists' in error_message or 'pull request already exists' in error_message:
                    # Double-check by looking for the PR again
                    existing_pr = self._check_existing_pr(branch, task.id)
                    if existing_pr:
                        return {
                            "status": "already_exists",
                            "message": f"Pull request already exists: {existing_pr['pr_url']}",
                            "pr_url": existing_pr["pr_url"],
                            "pr_number": existing_pr["pr_number"],
                            "found_by": "github_error_recovery"
                        }
            
            return {
                "status": "error", 
                "message": f"GitHub API error: {e.data if hasattr(e, 'data') else str(e)}",
                "error_type": "github_api_error"
            }
            
        except Exception as e:
            logger.error(f"Unexpected error creating PR: {e}")
            return {
                "status": "error", 
                "message": f"Unexpected error creating PR: {str(e)}",
                "error_type": "unexpected_error"
            } 