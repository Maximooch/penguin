"""Prepare and publish one recoverable draft PR for an execution."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from typing import TYPE_CHECKING, Any

from penguin.project.contribution_store import ContributionStore
from penguin.project.git_integration import GitIntegration
from penguin.project.repository_checkout import RepositoryError, validate_checkout

if TYPE_CHECKING:
    from penguin.project.contribution_auth import ContributionBinding, PullRequest


__all__ = ["publish_contribution"]


def publish_contribution(
    binding: ContributionBinding,
    title: str,
    body: str,
    *,
    files: list[str] | None = None,
) -> dict[str, Any]:
    """Publish once or reconcile an interrupted attempt without blind retries.

    The binding and request remain stable across retries. Once a write has an
    uncertain outcome, authoritative matching remote evidence is required to
    advance. Absence after an uncertain write is not permission to repeat it.
    """
    validate_checkout(binding.checkout, binding.repository)
    git = GitIntegration(binding.checkout)
    git.run("check-ref-format", "--branch", binding.base_branch)
    if (
        git.run("rev-parse", "--verify", f"{binding.base_sha}^{{commit}}")
        != binding.base_sha
    ):
        raise RepositoryError("Expected an immutable base commit SHA.")
    key = hashlib.sha256(
        f"{binding.repository.lower()}\0{binding.execution_id}\0{binding.contribution_id}".encode()
    ).hexdigest()[:24]
    branch = f"penguin/contribution-{key}"
    request = {
        "repository": binding.repository.lower(),
        "execution": binding.execution_id,
        "contribution": binding.contribution_id,
        "base": binding.base_branch,
        "base_sha": binding.base_sha,
        "title": title,
        "body": body,
        "files": sorted(set(files)) if files is not None else None,
    }
    fingerprint = hashlib.sha256(
        json.dumps(request, sort_keys=True).encode()
    ).hexdigest()
    store = ContributionStore(git, key)
    with store.lock():
        state = store.read()
        if state is None:
            # Check authority/availability before mutating the checkout.
            if binding.operations.branch_sha(binding, branch) is not None:
                raise RepositoryError(
                    "Remote contribution exists without a local receipt."
                )
            state = {
                "fingerprint": fingerprint,
                "initial_head": git.run("rev-parse", "HEAD"),
            }
            store.write(state)
        elif state.get("fingerprint") != fingerprint:
            raise RepositoryError(
                "Contribution identity reused with different inputs.",
                "CONTRIBUTION_CONFLICT",
            )
        # Recheck authority on retries before any remaining local mutation.
        binding.operations.branch_sha(binding, branch)
        sha = _prepare(git, binding, branch, title, files, state, store, key)
        if sha is None:
            return {
                "status": "no_changes",
                "message": "No changes relative to the base.",
            }
        if state.get("pr_pending"):
            terminal_pr = binding.operations.find_pr(binding, branch)
            if terminal_pr is not None and terminal_pr.state in {"closed", "merged"}:
                _verify_pr(terminal_pr, binding, branch, sha)
                state["pr"] = asdict(terminal_pr)
                store.write(state)
                return _result(binding, terminal_pr, sha, existed=True)
        remote_sha = binding.operations.branch_sha(binding, branch)
        if remote_sha != sha:
            if remote_sha is not None:
                raise RepositoryError("Remote branch differs from the prepared commit.")
            if state.get("push_pending"):
                raise RepositoryError(
                    "Push outcome is unknown; reconcile before retrying.",
                    "CONTRIBUTION_UNKNOWN",
                )
            state["push_pending"] = True
            store.write(state)
            binding.operations.push(binding, branch, sha)
            if binding.operations.branch_sha(binding, branch) != sha:
                raise RepositoryError(
                    "Push is not yet confirmed.", "CONTRIBUTION_UNKNOWN"
                )
        state["pushed"] = True
        store.write(state)
        pr = binding.operations.find_pr(binding, branch)
        existed = pr is not None
        if pr is None:
            if state.get("pr_pending"):
                raise RepositoryError(
                    "PR outcome is unknown; reconcile before retrying.",
                    "CONTRIBUTION_UNKNOWN",
                )
            state["pr_pending"] = True
            store.write(state)
            binding.operations.create_pr(binding, branch, title, body)
            # Do not trust a successful response without independently reading it.
            pr = binding.operations.find_pr(binding, branch)
            if pr is None:
                raise RepositoryError(
                    "PR creation is not yet confirmed.", "CONTRIBUTION_UNKNOWN"
                )
        _verify_pr(pr, binding, branch, sha)
        state["pr"] = asdict(pr)
        store.write(state)
        return _result(binding, pr, sha, existed=existed)


def _result(
    binding: ContributionBinding, pr: PullRequest, sha: str, *, existed: bool
) -> dict[str, Any]:
    return {
        "status": "already_exists" if existed else "created",
        "repository": binding.repository,
        "branch": pr.branch,
        "commit_sha": sha,
        "base_sha": binding.base_sha,
        "pr_url": pr.url,
        "pr_number": pr.number,
        "pr_state": pr.state,
        "contribution_id": binding.contribution_id,
    }


def _prepare(
    git: GitIntegration,
    binding: ContributionBinding,
    branch: str,
    title: str,
    files: list[str] | None,
    state: dict[str, Any],
    store: ContributionStore,
    key: str,
) -> str | None:
    if state.get("commit_sha"):
        sha = state["commit_sha"]
        if git.run("rev-parse", f"refs/heads/{branch}") != sha:
            raise RepositoryError(
                "Prepared branch changed; use a new contribution identity."
            )
        return sha
    current = git.get_current_branch()
    head = git.run("rev-parse", "HEAD")
    if current != branch:
        if head != state["initial_head"]:
            raise RepositoryError("Checkout changed since contribution preparation.")
        git.create_branch(branch)
    marker = f"Penguin-Contribution: {key}"
    # Recover a commit that succeeded before its receipt could be written.
    if head != state["initial_head"]:
        if git.run("show", "-s", "--format=%B", "HEAD").splitlines()[-1:] != [marker]:
            raise RepositoryError(
                "Cannot identify the interrupted contribution commit."
            )
        if git.run("rev-parse", "HEAD^") != state["initial_head"]:
            raise RepositoryError("Interrupted contribution has unexpected ancestry.")
    else:
        git.commit(f"{title}\n\n{marker}", files=files)
    sha = git.run("rev-parse", "HEAD")
    git.run("merge-base", "--is-ancestor", binding.base_sha, sha)
    if not git.run("diff", "--name-only", binding.base_sha, sha):
        return None
    state["commit_sha"] = sha
    store.write(state)
    return sha


def _verify_pr(
    pr: PullRequest, binding: ContributionBinding, branch: str, sha: str
) -> None:
    expected_url = f"https://github.com/{binding.repository}/pull/{pr.number}"
    if (
        pr.repository.lower() != binding.repository.lower()
        or pr.branch != branch
        or pr.base != binding.base_branch
        or pr.head_sha != sha
        or pr.number < 1
        or pr.url.lower() != expected_url.lower()
        or pr.state not in {"open", "closed", "merged"}
    ):
        raise RepositoryError("Remote PR does not match the prepared contribution.")
