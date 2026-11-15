"""A failed task PR flow returns the repository to the branch it started on.

Covers SM-62: create_pr_for_task created and checked out a feature branch,
then committed, pushed and opened the PR; when a later step failed, the
repository stayed on the feature branch and the next task branched from it.
Uses a real temporary repository with no remote, so the push fails.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import TYPE_CHECKING

import pytest

git = pytest.importorskip("git")

from penguin.project.git_manager import GitManager  # noqa: E402

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.asyncio
async def test_a_failed_push_returns_to_the_starting_branch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    repo = git.Repo.init(tmp_path, initial_branch="main")
    with repo.config_writer() as config:
        config.set_value("user", "name", "Test")
        config.set_value("user", "email", "test@example.invalid")
    (tmp_path / "file.txt").write_text("one\n")
    repo.index.add(["file.txt"])
    repo.index.commit("initial")
    (tmp_path / "file.txt").write_text("two\n")

    manager = GitManager(tmp_path, project_manager=None, repo_owner_and_name="o/r")
    task = SimpleNamespace(id="task123456", title="Change file", description="")

    result = await manager.create_pr_for_task(
        task, {"validated": True, "summary": "ok"}
    )

    assert result["status"] == "error"
    assert repo.active_branch.name == "main"
