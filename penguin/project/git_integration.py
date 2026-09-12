"""Local Git operations at an explicit checkout, using the tool environment."""

from __future__ import annotations

from pathlib import Path, PurePosixPath

from penguin.project.repository_checkout import RepositoryError, git_command
from penguin.system.tool_environment import hosted_tools_enabled

__all__ = ["GitIntegration"]


class GitIntegration:
    """Operate on an existing checkout without silently creating a repository."""

    def __init__(self, workspace_path: str | Path) -> None:
        self.workspace_path = Path(workspace_path).expanduser().resolve()
        root = Path(self.run("rev-parse", "--show-toplevel")).resolve()
        if root != self.workspace_path:
            raise RepositoryError("Expected the repository checkout root.")

    def run(self, *args: str) -> str:
        """Run Git with explicit environment and sanitized failures."""
        return git_command(self.workspace_path, *args)

    def initialize_repo(self) -> None:
        """Verify the existing checkout; initialization is an explicit setup task."""
        self.run("rev-parse", "--git-dir")

    def get_changed_files(self) -> list[str]:
        """Return staged, unstaged, deleted, and untracked paths, without quoting."""
        tracked = self.run("diff", "HEAD", "--name-only", "--no-renames", "-z")
        untracked = self.run("ls-files", "--others", "--exclude-standard", "-z")
        return sorted(set(filter(None, (tracked + "\0" + untracked).split("\0"))))

    def create_branch(self, branch_name: str, start_point: str = "HEAD") -> bool:
        """Create a new branch; never silently switch to an unrelated existing one."""
        self.run("check-ref-format", "--branch", branch_name)
        if self.get_current_branch() != branch_name:
            self.run("checkout", "-b", branch_name, start_point)
        return True

    def commit(
        self,
        message: str,
        add_all: bool = True,
        *,
        files: list[str] | None = None,
    ) -> str | None:
        """Commit selected paths, all changes, or the existing index.

        Explicit selection refuses unrelated staged changes instead of including
        them or discarding the caller's index. Paths are literal and root-relative.
        A clean index returns None so callers can publish a previous commit.
        """
        if files is not None:
            paths = self._validate_paths(files)
            staged = set(
                filter(
                    None,
                    self.run(
                        "diff", "--cached", "--name-only", "--no-renames", "-z"
                    ).split("\0"),
                )
            )
            if staged - set(paths):
                raise RepositoryError(
                    "Unrelated staged changes; commit them separately."
                )
            if paths:
                self.run("--literal-pathspecs", "add", "-A", "--", *paths)
        elif add_all:
            self.run("add", "-A", "--", ".")
        if not self.run("diff", "--cached", "--name-only", "-z"):
            return None
        self.run("commit", "-m", message)
        return self.run("rev-parse", "HEAD")

    def _validate_paths(self, paths: list[str]) -> list[str]:
        result = []
        for path in paths:
            relative = PurePosixPath(path)
            if (
                not path
                or not relative.parts
                or relative.is_absolute()
                or ".." in relative.parts
                or relative.parts[0].lower() == ".git"
                or "\0" in path
                or str(relative) == "."
            ):
                raise RepositoryError("Commit paths must be literal repository files.")
            target = self.workspace_path / path
            # Preserve symlink entries, but reject traversal through symlink parents.
            if not target.parent.resolve().is_relative_to(self.workspace_path):
                raise RepositoryError("Commit path leaves the checkout.")
            if target.is_dir():
                raise RepositoryError("Select individual files, not directories.")
            result.append(str(relative))
        return result

    def push_branch(self, branch_name: str, remote_name: str = "origin") -> bool:
        """Push locally authenticated work; hosted publication requires a broker."""
        if hosted_tools_enabled():
            raise RepositoryError("Hosted push requires execution-scoped operations.")
        self.run("check-ref-format", "--branch", branch_name)
        self.run(
            "push", remote_name, f"refs/heads/{branch_name}:refs/heads/{branch_name}"
        )
        return True

    def get_current_branch(self) -> str:
        """Return the active branch or HEAD for a detached checkout."""
        return self.run("rev-parse", "--abbrev-ref", "HEAD")
