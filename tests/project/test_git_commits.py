"""Real Git regression tests for staged and selected changes."""

from pathlib import Path

import pytest

from penguin.project.git_integration import GitIntegration
from penguin.project.repository_checkout import RepositoryError, git_command


@pytest.fixture
def git(tmp_path: Path) -> GitIntegration:
    git_command(tmp_path, "init", "-b", "trunk")
    git_command(tmp_path, "config", "user.name", "Penguin Test")
    git_command(tmp_path, "config", "user.email", "test@example.invalid")
    (tmp_path / "a.txt").write_text("initial")
    git_command(tmp_path, "add", ".")
    git_command(tmp_path, "commit", "-m", "initial")
    return GitIntegration(tmp_path)


def test_staged_only(git):
    (git.workspace_path / "a.txt").write_text("staged")
    git.run("add", "a.txt")
    assert git.get_changed_files() == ["a.txt"]
    assert git.commit("staged", add_all=False)
    assert not git.get_changed_files()


def test_deletion_and_rename(git):
    (git.workspace_path / "a.txt").rename(git.workspace_path / "b.txt")
    assert git.get_changed_files() == ["a.txt", "b.txt"]
    assert git.commit("rename")
    (git.workspace_path / "b.txt").unlink()
    assert git.commit("delete", files=["b.txt"])
    assert not git.run("ls-files")


def test_explicit_files_do_not_stage_other_changes(git):
    (git.workspace_path / "a.txt").write_text("leave this")
    (git.workspace_path / "b.txt").write_text("commit this")
    assert git.commit("selected", files=["b.txt"])
    assert git.run("show", "HEAD:a.txt") == "initial"
    assert git.get_changed_files() == ["a.txt"]


def test_unrelated_index_is_preserved(git):
    (git.workspace_path / "a.txt").write_text("already staged")
    git.run("add", "a.txt")
    (git.workspace_path / "b.txt").write_text("new")
    with pytest.raises(RepositoryError, match="Unrelated staged"):
        git.commit("selected", files=["b.txt"])
    assert git.run("diff", "--cached", "--name-only") == "a.txt"


@pytest.mark.parametrize("path", ["../outside", "/tmp/outside", ".git/config", "."])
def test_invalid_paths(git, path):
    with pytest.raises(RepositoryError):
        git.commit("bad", files=[path])


def test_literal_pathspec(git):
    (git.workspace_path / "*.txt").write_text("literal")
    (git.workspace_path / "other.txt").write_text("unselected")
    git.commit("literal", files=["*.txt"])
    assert git.get_changed_files() == ["other.txt"]


def test_clean_commit_is_not_an_error(git):
    assert git.commit("nothing") is None


def test_hosted_push_does_not_use_ambient_auth(git, monkeypatch):
    monkeypatch.setenv("PENGUIN_TOOL_ENVIRONMENT", "hosted")
    with pytest.raises(RepositoryError, match="execution-scoped"):
        git.push_branch("trunk")


def test_index_changes_visible_even_when_worktree_matches_head(git):
    (git.workspace_path / "a.txt").write_text("staged")
    git.run("add", "a.txt")
    (git.workspace_path / "a.txt").write_text("initial")
    assert git.get_changed_files() == ["a.txt"]
    assert git.commit("index", add_all=False)
    assert git.run("show", "HEAD:a.txt") == "staged"
