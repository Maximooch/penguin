"""Task compatibility facade for recoverable repository contributions."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING, Any

from github import GithubException
from requests.exceptions import RequestException

from penguin.config import GITHUB_REPOSITORY
from penguin.project.contribution_auth import (
    ContributionBinding,
    get_contribution_binding,
)
from penguin.project.contributions import publish_contribution
from penguin.project.git_integration import GitIntegration
from penguin.project.github_operations import (
    LocalGitHubOperations,
    github_app_client,
    local_github_client,
)
from penguin.project.repository_checkout import RepositoryError, validate_checkout
from penguin.system.tool_environment import hosted_tools_enabled

if TYPE_CHECKING:
    from github import Github


__all__ = ["GitManager"]

# Compatibility for the existing webhook integration. The called function rejects
# hosted mode before reading a key. Hosted webhooks remain separate Link work.
_get_github_app_client = github_app_client


class GitManager:
    """Keep task workflow compatibility while delegating GitHub publication."""

    def __init__(
        self,
        workspace_path: str | Path,
        project_manager: Any = None,
        repo_owner_and_name: str | None = None,
        default_branch: str | None = None,
    ) -> None:
        self.workspace_path = Path(workspace_path).expanduser().resolve()
        self.project_manager = project_manager
        self.repo_owner_and_name = repo_owner_and_name or GITHUB_REPOSITORY
        self.default_branch = default_branch
        self.git_integration = GitIntegration(self.workspace_path)
        self.github: Github | None = None

    def _binding(self, contribution_id: str) -> ContributionBinding:
        repository = self.repo_owner_and_name
        if not repository:
            raise RepositoryError("Specify a GitHub repository.")
        validate_checkout(self.workspace_path, repository)
        binding = get_contribution_binding(repository, self.workspace_path)
        if binding is not None:
            return binding
        if hosted_tools_enabled():
            raise RepositoryError("Hosted publication requires an execution broker.")
        client = self.github or local_github_client()
        self.github = client
        try:
            base = self.default_branch or client.get_repo(repository).default_branch
        except (GithubException, RequestException):
            raise RepositoryError("Cannot read the repository base branch.") from None
        base_sha = self.git_integration.run("rev-parse", f"refs/remotes/origin/{base}")
        return ContributionBinding(
            "local",
            contribution_id,
            repository,
            self.workspace_path,
            base,
            base_sha,
            LocalGitHubOperations(client),
        )

    def publish(
        self,
        contribution_id: str,
        title: str,
        body: str,
        *,
        files: list[str] | None = None,
    ) -> dict[str, Any]:
        """Publish explicit changes using stable inputs and execution authority."""
        return publish_contribution(
            self._binding(contribution_id), title, body, files=files
        )

    async def create_pr_for_task(
        self, task: Any, validation_results: dict[str, Any]
    ) -> dict[str, Any]:
        """Publish a validated project task while preserving execution context."""
        if not validation_results.get("validated"):
            return {"status": "validation_failed", "message": "Validation failed."}
        body = (
            f"{task.description}\n\nTask ID: {task.id}\n\n"
            "Validation supplied by task runner:\n"
            f"{validation_results.get('summary', '')}\n"
            f"{validation_results.get('details', '')}"
        )
        return await asyncio.to_thread(self.publish, task.id, task.title, body)
