"""Model-facing repository tools bound to the effective execution checkout."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from penguin.project.repository_checkout import RepositoryError, validate_checkout
from penguin.project.repository_manager import RepositoryConfig, RepositoryManager
from penguin.system.execution_context import get_current_execution_context_dict
from penguin.system.tool_environment import hosted_tools_enabled

__all__ = [
    "REPOSITORY_TOOLS",
    "commit_and_push_changes",
    "create_and_switch_branch",
    "create_bugfix_pr",
    "create_feature_pr",
    "create_improvement_pr",
    "get_repository_status",
]


def _get_repository_manager(
    repo_owner: str, repo_name: str, directory: str | None = None
) -> RepositoryManager:
    context = get_current_execution_context_dict()
    selected = directory or context.get("directory") or context.get("project_root")
    if not selected and hosted_tools_enabled():
        raise RepositoryError("Hosted repository tools require an execution checkout.")
    local_path = validate_checkout(
        Path(selected or Path.cwd()), f"{repo_owner}/{repo_name}"
    )
    return RepositoryManager(RepositoryConfig(repo_name, repo_owner, local_path))


def _files(value: str | None) -> list[str] | None:
    return (
        [item.strip() for item in value.split(",") if item.strip()] if value else None
    )


def create_improvement_pr(
    repo_owner: str,
    repo_name: str,
    title: str,
    description: str,
    files_changed: str | None = None,
    *,
    directory: str | None = None,
    contribution_id: str | None = None,
) -> str:
    """Create or reconcile a draft PR and return verified remote evidence."""
    manager = _get_repository_manager(repo_owner, repo_name, directory)
    return json.dumps(
        asyncio.run(
            manager.create_improvement_pr(
                title,
                description,
                _files(files_changed),
                contribution_id=contribution_id,
            )
        )
    )


def create_feature_pr(
    repo_owner: str,
    repo_name: str,
    feature_name: str,
    description: str,
    implementation_notes: str = "",
    files_modified: str | None = None,
    *,
    directory: str | None = None,
    contribution_id: str | None = None,
) -> str:
    """Publish a feature using the same recoverable draft workflow."""
    return create_improvement_pr(
        repo_owner,
        repo_name,
        f"feat: {feature_name}",
        f"{description}\n\n{implementation_notes}",
        files_modified,
        directory=directory,
        contribution_id=contribution_id,
    )


def create_bugfix_pr(
    repo_owner: str,
    repo_name: str,
    bug_description: str,
    fix_description: str,
    files_fixed: str | None = None,
    *,
    directory: str | None = None,
    contribution_id: str | None = None,
) -> str:
    """Publish a fix using the same recoverable draft workflow."""
    return create_improvement_pr(
        repo_owner,
        repo_name,
        f"fix: {bug_description}",
        fix_description,
        files_fixed,
        directory=directory,
        contribution_id=contribution_id,
    )


def get_repository_status(
    repo_owner: str,
    repo_name: str,
    *,
    directory: str | None = None,
) -> str:
    """Return checkout status without loading authentication."""
    return json.dumps(
        _get_repository_manager(
            repo_owner, repo_name, directory
        ).get_repository_status()
    )


def commit_and_push_changes(
    repo_owner: str,
    repo_name: str,
    commit_message: str,
    files_to_add: str | None = None,
    *,
    directory: str | None = None,
) -> str:
    """Commit/push local work; hosted calls must use the bound draft workflow."""
    if hosted_tools_enabled():
        raise RepositoryError("Use the execution-bound PR workflow for hosted pushes.")
    git = _get_repository_manager(
        repo_owner, repo_name, directory
    ).git_manager.git_integration
    sha = git.commit(commit_message, files=_files(files_to_add)) or git.run(
        "rev-parse", "HEAD"
    )
    branch = git.get_current_branch()
    git.push_branch(branch)
    return json.dumps({"status": "pushed", "commit_sha": sha, "branch": branch})


def create_and_switch_branch(
    repo_owner: str,
    repo_name: str,
    branch_name: str,
    *,
    directory: str | None = None,
) -> str:
    """Create a local branch at the execution checkout."""
    git = _get_repository_manager(
        repo_owner, repo_name, directory
    ).git_manager.git_integration
    git.create_branch(branch_name)
    return json.dumps({"status": "created", "branch": branch_name})


REPOSITORY_TOOLS = [
    {
        "name": "create_improvement_pr",
        "description": "Create a pull request for improvements to a GitHub repository",
        "function": create_improvement_pr,
        "parameters": {
            "repo_owner": "GitHub repository owner",
            "repo_name": "GitHub repository name",
            "title": "Title of the improvement PR",
            "description": "Detailed description of the improvements",
            "contribution_id": "Stable change identity; reuse on retries",
            "files_changed": "Optional literal file paths, comma-separated",
        },
    },
    {
        "name": "create_feature_pr",
        "description": "Create a pull request for a new feature in a GitHub repository",
        "function": create_feature_pr,
        "parameters": {
            "repo_owner": "GitHub repository owner",
            "repo_name": "GitHub repository name",
            "feature_name": "Name of the new feature",
            "description": "Description of what the feature does",
            "implementation_notes": "Additional implementation details (optional)",
            "contribution_id": "Stable change identity; reuse on retries",
            "files_modified": "Optional literal file paths, comma-separated",
        },
    },
    {
        "name": "create_bugfix_pr",
        "description": "Create a pull request for a bug fix in a GitHub repository",
        "function": create_bugfix_pr,
        "parameters": {
            "repo_owner": "GitHub repository owner",
            "repo_name": "GitHub repository name",
            "bug_description": "Description of the bug that was fixed",
            "fix_description": "Description of how the bug was fixed",
            "contribution_id": "Stable change identity; reuse on retries",
            "files_fixed": "Comma-separated list of files that were fixed (optional)",
        },
    },
    {
        "name": "get_repository_status",
        "description": "Get the current status of a GitHub repository",
        "function": get_repository_status,
        "parameters": {
            "repo_owner": "GitHub repository owner",
            "repo_name": "GitHub repository name",
        },
    },
    {
        "name": "commit_and_push_changes",
        "description": "Commit and push changes to the current branch of a repository",
        "function": commit_and_push_changes,
        "parameters": {
            "repo_owner": "GitHub repository owner",
            "repo_name": "GitHub repository name",
            "commit_message": "Commit message",
            "files_to_add": "Optional literal paths; omitted means all changes",
        },
    },
    {
        "name": "create_and_switch_branch",
        "description": "Create a new branch and switch to it in a repository",
        "function": create_and_switch_branch,
        "parameters": {
            "repo_owner": "GitHub repository owner",
            "repo_name": "GitHub repository name",
            "branch_name": "Name of the new branch to create",
        },
    },
]
