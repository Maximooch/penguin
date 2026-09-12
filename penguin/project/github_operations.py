"""Local GitHub operations. Hosted execution must supply a separate broker."""

from __future__ import annotations

from typing import Any

from github import Auth, Github, GithubException
from requests.exceptions import RequestException

from penguin.config import get_api_key
from penguin.project.contribution_auth import ContributionBinding, PullRequest
from penguin.project.git_integration import GitIntegration
from penguin.project.repository_checkout import RepositoryError, validate_checkout
from penguin.system.tool_environment import hosted_tools_enabled

__all__ = ["LocalGitHubOperations", "github_app_client", "local_github_client"]


def github_app_client(app_id: str, key_path: str, installation_id: str) -> Github:
    """Create a local App client; never open its key in hosted mode."""
    if hosted_tools_enabled():
        raise RepositoryError("Hosted GitHub operations require an execution broker.")
    try:
        with open(key_path, encoding="utf-8") as key_file:
            auth = Auth.AppAuth(app_id, key_file.read())
        return Github(auth=auth.get_installation_auth(int(installation_id)), retry=0)
    except (OSError, ValueError):
        raise RepositoryError("GitHub App authentication is unavailable.") from None


def local_github_client() -> Github:
    """Load explicit local authentication with no fallback from broken App config."""
    if hosted_tools_enabled():
        raise RepositoryError("Hosted GitHub operations require an execution broker.")
    app = [
        get_api_key(name)
        for name in (
            "GITHUB_APP_ID",
            "GITHUB_APP_PRIVATE_KEY_PATH",
            "GITHUB_APP_INSTALLATION_ID",
        )
    ]
    if any(app):
        if not all(app):
            raise RepositoryError("Incomplete GitHub App configuration.")
        return github_app_client(*app)
    token = get_api_key("GITHUB_TOKEN")
    if not token:
        raise RepositoryError("GitHub authentication is not configured.")
    return Github(auth=Auth.Token(token), retry=0)


class LocalGitHubOperations:
    """Adapt PyGithub and local Git credentials for trusted desktop workflows."""

    def __init__(self, client: Github) -> None:
        self.client = client

    def _repo(self, binding: ContributionBinding) -> Any:
        if hosted_tools_enabled():
            raise RepositoryError("Local authentication is disabled in hosted mode.")
        validate_checkout(binding.checkout, binding.repository)
        return self.client.get_repo(binding.repository)

    @staticmethod
    def _result(pr: Any) -> PullRequest:
        if (
            pr.head.repo is None
            or pr.head.repo.full_name.lower() != pr.base.repo.full_name.lower()
        ):
            raise RepositoryError("Fork contributions require separate authorization.")
        return PullRequest(
            number=pr.number,
            url=pr.html_url,
            repository=pr.base.repo.full_name,
            branch=pr.head.ref,
            base=pr.base.ref,
            head_sha=pr.head.sha,
            state="merged" if pr.merged else pr.state,
        )

    def branch_sha(self, binding: ContributionBinding, branch: str) -> str | None:
        """Look up a branch; transport/auth failures are not absence."""
        try:
            repo = self._repo(binding)
            # Listing avoids treating a repository-level 404 as a missing branch.
            for item in repo.get_branches():
                if item.name == branch:
                    return item.commit.sha
            return None
        except (GithubException, RequestException):
            raise RepositoryError("GitHub branch lookup is unavailable.") from None

    def push(self, binding: ContributionBinding, branch: str, sha: str) -> None:
        """Push an immutable object to a branch; no force or implicit retry."""
        self._repo(binding)
        git = GitIntegration(binding.checkout)
        git.run("check-ref-format", "--branch", branch)
        git.run("push", "origin", f"{sha}:refs/heads/{branch}")

    def find_pr(self, binding: ContributionBinding, branch: str) -> PullRequest | None:
        """Find the precise head/base pair in all PR states."""
        try:
            repo = self._repo(binding)
            owner = binding.repository.split("/")[0]
            matches = list(
                repo.get_pulls(
                    state="all", head=f"{owner}:{branch}", base=binding.base_branch
                )
            )
            if len(matches) > 1:
                raise RepositoryError("Multiple PRs require manual reconciliation.")
            return self._result(matches[0]) if matches else None
        except (GithubException, RequestException):
            raise RepositoryError("GitHub PR lookup is unavailable.") from None

    def create_pr(
        self, binding: ContributionBinding, branch: str, title: str, body: str
    ) -> PullRequest:
        """Create a draft once; uncertain outcomes propagate to the workflow."""
        try:
            pr = self._repo(binding).create_pull(
                title=title,
                body=body,
                head=branch,
                base=binding.base_branch,
                draft=True,
            )
            return self._result(pr)
        except (GithubException, RequestException):
            raise RepositoryError(
                "GitHub PR creation outcome requires reconciliation."
            ) from None
