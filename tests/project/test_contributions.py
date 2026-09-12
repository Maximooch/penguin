"""Offline fault injection against real commits and a local bare remote."""

import json
from dataclasses import replace
from pathlib import Path

import pytest

from penguin.project.contribution_auth import (
    ContributionBinding,
    contribution_scope,
)
from penguin.project.contribution_store import ContributionStore
from penguin.project.contributions import publish_contribution
from penguin.project.git_integration import GitIntegration
from penguin.project.repository_checkout import RepositoryError, git_command
from penguin.system.tool_environment import tool_environment_scope
from penguin.tools.repository_tools import create_improvement_pr
from tests.project.fake_broker import FakeBroker


@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.setenv("PENGUIN_TOOL_ENVIRONMENT", "hosted")
    remote = tmp_path / "remote.git"
    remote.mkdir()
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    with tool_environment_scope(
        {
            "HOME": str(tmp_path),
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": "/dev/null",
            "GIT_AUTHOR_NAME": "Penguin Test",
            "GIT_AUTHOR_EMAIL": "test@example.invalid",
            "GIT_COMMITTER_NAME": "Penguin Test",
            "GIT_COMMITTER_EMAIL": "test@example.invalid",
        }
    ):
        git_command(remote, "init", "--bare")
        git_command(checkout, "init", "-b", "trunk")
        git_command(
            checkout,
            "remote",
            "add",
            "origin",
            "https://github.com/Maximooch/penguin-test-repo.git",
        )
        (checkout / "file.txt").write_text("base")
        git = GitIntegration(checkout)
        git.commit("base")
        base_sha = git.run("rev-parse", "HEAD")
        (checkout / "file.txt").write_text("change")
        broker = FakeBroker(remote)
        binding = ContributionBinding(
            "execution-a",
            "change-a",
            "Maximooch/penguin-test-repo",
            checkout,
            "trunk",
            base_sha,
            broker,
        )
        yield binding, broker, git


def publish(binding):
    return publish_contribution(binding, "fix: test", "Tests: fake broker and real Git")


def test_success_and_replay(setup):
    binding, broker, git = setup
    result = publish(binding)
    assert result["status"] == "created"
    assert result["commit_sha"] == broker.branch_sha(binding, result["branch"])
    assert broker.pr.base == "trunk"
    assert publish(binding)["status"] == "already_exists"
    assert broker.pushes == broker.creates == 1
    assert not git.get_changed_files()


@pytest.mark.parametrize("failure", ["fail_push", "fail_create"])
def test_lost_ack_reconciles_without_repeating(setup, failure):
    binding, broker, git = setup
    setattr(broker, failure, True)
    with pytest.raises(RepositoryError):
        publish(binding)
    sha = git.run("rev-parse", "HEAD")
    result = publish(binding)
    assert result["commit_sha"] == sha
    assert broker.pushes == broker.creates == 1


def test_absence_after_uncertain_create_does_not_retry(setup):
    binding, broker, _ = setup
    broker.fail_create = True
    with pytest.raises(RepositoryError):
        publish(binding)
    broker.hide_pr = True
    with pytest.raises(RepositoryError, match="PR outcome is unknown"):
        publish(binding)
    assert broker.creates == 1


def test_lookup_error_is_not_absence(setup):
    binding, broker, _ = setup
    broker.fail_lookup = True
    with pytest.raises(RepositoryError, match="Lookup unavailable"):
        publish(binding)
    assert broker.creates == 0
    broker.fail_lookup = False
    assert publish(binding)["status"] == "created"
    assert broker.pushes == 1


def test_recover_commit_after_receipt_write_failure(setup, monkeypatch):
    binding, broker, git = setup
    original = ContributionStore.write

    def fail_once(store, state):
        if state.get("commit_sha"):
            raise RepositoryError("Disk unavailable")
        original(store, state)

    monkeypatch.setattr(ContributionStore, "write", fail_once)
    with pytest.raises(RepositoryError, match="Disk unavailable"):
        publish(binding)
    sha = git.run("rev-parse", "HEAD")
    monkeypatch.setattr(ContributionStore, "write", original)
    assert publish(binding)["commit_sha"] == sha
    assert broker.pushes == broker.creates == 1


def test_clean_but_ahead_can_publish(setup):
    binding, _broker, git = setup
    sha = git.commit("pre-existing change")
    assert not git.get_changed_files()
    assert publish(binding)["commit_sha"] == sha


def test_changed_input_conflicts_before_new_side_effect(setup):
    binding, broker, _ = setup
    publish(binding)
    with pytest.raises(RepositoryError, match="different inputs"):
        publish_contribution(binding, "different", "body")
    assert broker.creates == broker.pushes == 1


def test_revoked_execution_cannot_replay(setup):
    binding, broker, _ = setup
    publish(binding)
    broker.revoked = True
    with pytest.raises(RepositoryError, match="denied"):
        publish(binding)


def test_closed_pr_is_returned_without_reopening(setup):
    binding, broker, _ = setup
    publish(binding)
    broker.pr = replace(broker.pr, state="closed")
    assert publish(binding)["pr_state"] == "closed"
    assert broker.creates == 1


def test_wrong_remote_pr_rejected(setup):
    binding, broker, _ = setup
    publish(binding)
    broker.pr = replace(broker.pr, head_sha="0" * 40)
    with pytest.raises(RepositoryError, match="does not match"):
        publish(binding)


def test_tool_uses_bound_broker_through_thread(setup, monkeypatch, tmp_path):
    binding, _broker, _ = setup
    monkeypatch.chdir(tmp_path)
    with contribution_scope(binding):
        result = json.loads(
            create_improvement_pr(
                "Maximooch",
                "penguin-test-repo",
                "title",
                "description",
                directory=str(binding.checkout),
                contribution_id="model-cannot-change-binding",
            )
        )
    assert result["contribution_id"] == "change-a"
    assert result["pr_number"] == 7


def test_missing_broker_fails_before_commit(setup):
    binding, broker, git = setup
    with pytest.raises(RepositoryError, match="execution broker"):
        create_improvement_pr(
            "Maximooch",
            "penguin-test-repo",
            "title",
            "body",
            directory=str(binding.checkout),
        )
    assert git.run("rev-parse", "HEAD") == binding.base_sha
    assert broker.pushes == 0


def test_concurrent_publication_refused(setup):
    binding, _, git = setup
    store = ContributionStore(git, "test")
    with store.lock():
        with pytest.raises(RepositoryError, match="Another contribution"):
            publish(binding)


def test_receipt_contains_no_broker_secret_or_object(setup):
    binding, broker, git = setup
    broker.secret = "synthetic-do-not-persist"
    publish(binding)
    records = Path(git.run("rev-parse", "--absolute-git-dir")) / "penguin-contributions"
    assert broker.secret not in "".join(p.read_text() for p in records.glob("*.json"))


def test_revocation_after_push_denies_pr_creation(setup, monkeypatch):
    binding, broker, _ = setup
    original = broker.push

    def revoke_after_push(*args):
        original(*args)
        broker.revoked = True

    monkeypatch.setattr(broker, "push", revoke_after_push)
    with pytest.raises(RepositoryError, match="denied"):
        publish(binding)
    assert broker.creates == 0


def test_unknown_push_without_remote_evidence_never_repeats(setup, monkeypatch):
    binding, broker, _ = setup

    def unknown_push(*args):
        broker.pushes += 1
        raise RepositoryError("Transport lost")

    monkeypatch.setattr(broker, "push", unknown_push)
    with pytest.raises(RepositoryError):
        publish(binding)
    with pytest.raises(RepositoryError, match="Push outcome is unknown"):
        publish(binding)
    assert broker.pushes == 1


def test_preexisting_branch_collision_does_not_checkout_foreign_work(setup):
    binding, _broker, git = setup
    publish(binding)
    initial = git.run("rev-parse", "HEAD")
    # Another scope cannot take over this contribution branch via an API parameter.
    with contribution_scope(replace(binding, repository="foreign/repo")):
        with pytest.raises(RepositoryError, match="does not match"):
            create_improvement_pr(
                "Maximooch",
                "penguin-test-repo",
                "title",
                "body",
                directory=str(binding.checkout),
            )
    assert git.run("rev-parse", "HEAD") == initial


@pytest.mark.asyncio
async def test_public_tool_manager_dispatch_preserves_binding(
    setup, monkeypatch, tmp_path
):
    from penguin.tools.tool_manager import ToolManager

    binding, broker, _ = setup
    monkeypatch.chdir(tmp_path)
    manager = ToolManager({"diagnostics": {"enabled": False}}, lambda *_: None)
    with contribution_scope(binding):
        raw = await manager.execute_tool_async(
            "create_improvement_pr",
            {
                "repo_owner": "Maximooch",
                "repo_name": "penguin-test-repo",
                "title": "dispatch test",
                "description": "fake broker",
            },
            context={"directory": str(binding.checkout)},
        )
    result = json.loads(raw) if isinstance(raw, str) else raw
    assert result["pr_number"] == 7
    assert broker.creates == 1


@pytest.mark.parametrize("state", ["closed", "merged"])
def test_terminal_pr_survives_remote_branch_deletion(setup, state):
    binding, broker, _ = setup
    result = publish(binding)
    broker.pr = replace(broker.pr, state=state)
    git_command(broker.remote, "update-ref", "-d", f"refs/heads/{result['branch']}")
    assert publish(binding)["pr_state"] == state
    assert broker.pushes == broker.creates == 1
