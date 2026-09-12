"""Repository-level compatibility workflows over one contribution service."""

from __future__ import annotations

import asyncio
import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from penguin.project.contribution_auth import get_contribution_binding
from penguin.project.git_manager import GitManager

__all__ = [
    "RepositoryConfig",
    "RepositoryManager",
    "get_penguin_repository_manager",
    "get_test_repository_manager",
]


@dataclass(frozen=True)
class RepositoryConfig:
    """Explicit checkout and optional base branch for a GitHub repository."""

    name: str
    owner: str
    local_path: Path
    default_branch: str | None = None

    @property
    def full_name(self) -> str:
        return f"{self.owner}/{self.name}"

    @property
    def url(self) -> str:
        return f"https://github.com/{self.full_name}"


class RepositoryManager:
    """Prepare draft PRs without inventing task completion or test results."""

    def __init__(self, config: RepositoryConfig) -> None:
        self.config = config
        self.local_path = config.local_path.resolve()
        self.git_manager = GitManager(
            self.local_path,
            repo_owner_and_name=config.full_name,
            default_branch=config.default_branch,
        )

    async def create_improvement_pr(
        self,
        title: str,
        description: str,
        file_changes: list[str] | None = None,
        branch_prefix: str = "penguin",
        *,
        contribution_id: str | None = None,
    ) -> dict[str, Any]:
        """Publish a draft; branch_prefix is retained for call compatibility only."""
        identity = (
            contribution_id
            or hashlib.sha256(f"{title}\0{description}".encode()).hexdigest()
        )
        body = f"{description}\n\nValidation: not supplied by this repository tool."
        return await asyncio.to_thread(
            self.git_manager.publish,
            identity,
            title,
            body,
            files=file_changes,
        )

    async def create_feature_pr(
        self,
        feature_name: str,
        feature_description: str,
        implementation_notes: str = "",
        files_modified: list[str] | None = None,
        *,
        contribution_id: str | None = None,
    ) -> dict[str, Any]:
        """Publish a feature through the shared draft workflow."""
        return await self.create_improvement_pr(
            f"feat: {feature_name}",
            f"{feature_description}\n\n{implementation_notes}",
            files_modified,
            contribution_id=contribution_id,
        )

    async def create_bugfix_pr(
        self,
        bug_description: str,
        fix_description: str,
        files_fixed: list[str] | None = None,
        *,
        contribution_id: str | None = None,
    ) -> dict[str, Any]:
        """Publish a fix through the shared draft workflow."""
        return await self.create_improvement_pr(
            f"fix: {bug_description}",
            fix_description,
            files_fixed,
            contribution_id=contribution_id,
        )

    def get_repository_status(self) -> dict[str, Any]:
        """Describe checkout state without loading credentials or claiming authority."""
        git = self.git_manager.git_integration
        changed = git.get_changed_files()
        binding = get_contribution_binding(self.config.full_name, self.local_path)
        return {
            "repository": self.config.full_name,
            "local_path": str(self.local_path),
            "current_branch": git.get_current_branch(),
            "changed_files": changed,
            "has_changes": bool(changed),
            "execution_bound": binding is not None,
        }


def get_penguin_repository_manager() -> RepositoryManager:
    """Use the caller's checkout instead of a developer-specific absolute path."""
    return RepositoryManager(RepositoryConfig("penguin", "Maximooch", Path.cwd()))


def get_test_repository_manager() -> RepositoryManager:
    """Use the caller's test checkout; cloning remains an explicit setup step."""
    return RepositoryManager(
        RepositoryConfig("penguin-test-repo", "Maximooch", Path.cwd())
    )
