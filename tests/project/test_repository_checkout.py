"""Checkout selection must not depend on the web server working directory."""

from pathlib import Path

import pytest

from penguin.project.repository_checkout import RepositoryError, git_command, validate_checkout
from penguin.tools import repository_tools


@pytest.fixture
def checkout(tmp_path: Path) -> Path:
    root = tmp_path / "checkout"
    root.mkdir()
    git_command(root, "init", "-b", "trunk")
    git_command(root, "remote", "add", "origin", "https://github.com/Maximooch/penguin-test-repo.git")
    return root


def test_explicit_root_beats_server_cwd(checkout, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(repository_tools, "RepositoryManager", lambda config: config)
    config = repository_tools._get_repository_manager("Maximooch", "penguin-test-repo", str(checkout))
    assert config.local_path == checkout
    assert config.default_branch is None


@pytest.mark.parametrize("url", ["https://github.com/other/repo.git", "https://token@github.com/Maximooch/penguin-test-repo.git", "https://github.com.evil.test/Maximooch/penguin-test-repo.git"])
def test_wrong_push_remote_denied(checkout, url):
    git_command(checkout, "remote", "set-url", "--push", "origin", url)
    with pytest.raises(RepositoryError):
        validate_checkout(checkout, "Maximooch/penguin-test-repo")


def test_hosted_requires_explicit_checkout(monkeypatch):
    monkeypatch.setenv("PENGUIN_TOOL_ENVIRONMENT", "hosted")
    with pytest.raises(RepositoryError, match="execution checkout"):
        repository_tools._get_repository_manager("Maximooch", "penguin-test-repo")


def test_never_initializes_missing_repo(tmp_path):
    with pytest.raises(RepositoryError):
        validate_checkout(tmp_path, "Maximooch/penguin-test-repo")
    assert not (tmp_path / ".git").exists()


def test_ambient_git_dir_cannot_redirect(checkout, monkeypatch, tmp_path):
    monkeypatch.setenv("GIT_DIR", str(tmp_path / "foreign.git"))
    assert validate_checkout(checkout, "Maximooch/penguin-test-repo") == checkout
