"""Opt-in real GitHub publication smoke, independent of model response wording.

Requires a disposable, clean clone of Maximooch/penguin-test-repo, working Git
transport authentication, and PENGUIN_TEST_GITHUB_TOKEN for API authentication.
This local smoke is not the production hosted broker integration.
"""

from __future__ import annotations

import os
import uuid
from pathlib import Path

import pytest

from penguin.project.git_manager import GitManager
from penguin.project.repository_checkout import validate_checkout

pytestmark = [pytest.mark.live, pytest.mark.e2e]


def test_create_verified_draft_pr() -> None:
    if os.getenv("PENGUIN_RUN_GITHUB_SMOKE") != "1":
        pytest.skip("Explicit GitHub smoke activation is required")
    if os.getenv("PENGUIN_TOOL_ENVIRONMENT") == "hosted":
        pytest.skip("Hosted live publication awaits the external broker integration")
    from github import Auth, Github

    directory = os.environ["PENGUIN_TEST_GITHUB_CHECKOUT"]
    repository = "Maximooch/penguin-test-repo"
    root = validate_checkout(Path(directory), repository)
    manager = GitManager(root, repo_owner_and_name=repository)
    git = manager.git_integration
    assert not git.get_changed_files(), "The smoke requires a clean disposable clone"
    client = Github(auth=Auth.Token(os.environ["PENGUIN_TEST_GITHUB_TOKEN"]), retry=0)
    manager.github = client
    repo = client.get_repo(repository)
    base = repo.default_branch
    assert git.run("rev-parse", "HEAD") == git.run(
        "rev-parse", f"refs/remotes/origin/{base}"
    )
    identity = f"penguin-github-contributions-test-{uuid.uuid4().hex}"
    filename = f"{identity}.md"
    (root / filename).write_text("Penguin GitHub contribution smoke test.\n")
    title = f"test: {identity}"
    result = manager.publish(
        identity, title, "Explicit Penguin contribution smoke test.", files=[filename]
    )
    pr = repo.get_pull(result["pr_number"])
    assert pr.draft
    assert pr.head.sha == result["commit_sha"]
    assert repo.get_branch(result["branch"]).commit.sha == result["commit_sha"]
    assert pr.base.ref == base
    replay = manager.publish(
        identity, title, "Explicit Penguin contribution smoke test.", files=[filename]
    )
    assert replay["pr_number"] == result["pr_number"]
    assert replay["status"] == "already_exists"
