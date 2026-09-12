"""Validate the explicit checkout used by repository tools."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from urllib.parse import urlsplit

from penguin.system.tool_environment import build_tool_environment
from penguin.utils.errors import PenguinError

__all__ = ["RepositoryError", "git_command", "validate_checkout"]


class RepositoryError(PenguinError):
    """A repository operation failed without exposing command output or secrets."""

    def __init__(self, message: str, code: str = "REPOSITORY_ERROR") -> None:
        super().__init__(message, code=code, suggested_action="inspect_repository")


def git_command(directory: Path, *args: str) -> str:
    """Run Git at an explicit root using the tool environment policy.

    Command errors intentionally omit stderr, command arguments, and environment
    values because Git can echo authenticated URLs and helper diagnostics.
    """
    environment = build_tool_environment()
    # An ambient GIT_DIR or worktree override must not redirect this checkout.
    for key in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR"):
        environment.pop(key, None)
    environment["GIT_TERMINAL_PROMPT"] = "0"
    try:
        result = subprocess.run(
            ["git", "-C", str(directory), *args],
            env=environment,
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        raise RepositoryError("Git could not complete the operation.") from None
    if result.returncode:
        raise RepositoryError("Git rejected the operation; inspect the checkout.")
    return result.stdout.rstrip("\n")


def _repository_from_url(url: str) -> str:
    if url.startswith("git@github.com:"):
        path = url[len("git@github.com:"):]
    else:
        parsed = urlsplit(url)
        if (
            parsed.scheme != "https"
            or parsed.netloc.lower() != "github.com"
            or parsed.query
            or parsed.fragment
        ):
            raise RepositoryError("Expected a credential-free GitHub origin URL.")
        path = parsed.path.lstrip("/")
    path = path.removesuffix(".git")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", path):
        raise RepositoryError("Invalid GitHub repository path.")
    return path.lower()


def validate_checkout(directory: Path, repository: str) -> Path:
    """Require an existing checkout root and matching fetch and push origins."""
    root = directory.expanduser().resolve()
    if Path(git_command(root, "rev-parse", "--show-toplevel")).resolve() != root:
        raise RepositoryError("Repository tools require the checkout root.")
    expected = _repository_from_url(f"https://github.com/{repository}")
    for flags in (("--all",), ("--push", "--all")):
        urls = git_command(root, "remote", "get-url", *flags, "origin").splitlines()
        if len(urls) != 1 or _repository_from_url(urls[0]) != expected:
            raise RepositoryError("Origin does not match the requested repository.")
    return root
