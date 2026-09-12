"""Deterministic external operation fake backed by a local bare Git repository."""

from pathlib import Path

from penguin.project.contribution_auth import PullRequest
from penguin.project.repository_checkout import RepositoryError, git_command


class FakeBroker:
    """Emulate external policy and remote effects without any real credentials."""

    def __init__(self, remote: Path):
        self.remote = remote
        self.pr = None
        self.pushes = 0
        self.creates = 0
        self.revoked = False
        self.fail_push = False
        self.fail_create = False
        self.fail_lookup = False
        self.hide_pr = False

    def check(self, binding):
        if self.revoked or binding.execution_id != "execution-a":
            raise RepositoryError("Execution authority denied.")

    def branch_sha(self, binding, branch):
        self.check(binding)
        return (
            git_command(
                self.remote,
                "for-each-ref",
                "--format=%(objectname)",
                f"refs/heads/{branch}",
            )
            or None
        )

    def push(self, binding, branch, sha):
        self.check(binding)
        self.pushes += 1
        git_command(
            binding.checkout, "push", str(self.remote), f"{sha}:refs/heads/{branch}"
        )
        if self.fail_push:
            raise RepositoryError("Lost push acknowledgement")

    def find_pr(self, binding, branch):
        self.check(binding)
        if self.fail_lookup:
            raise RepositoryError("Lookup unavailable")
        return None if self.hide_pr else self.pr

    def create_pr(self, binding, branch, title, body):
        self.check(binding)
        self.creates += 1
        self.pr = PullRequest(
            7,
            f"https://github.com/{binding.repository}/pull/7",
            binding.repository,
            branch,
            binding.base_branch,
            self.branch_sha(binding, branch),
            "open",
        )
        if self.fail_create:
            raise RepositoryError("Lost create acknowledgement")
        return self.pr
