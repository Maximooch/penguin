"""Internal execution binding for hosted repository operations.

This is a Python integration contract, not a Link HTTP API or a credential vault.
Implementations must enforce current authority outside the agent runtime.
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from penguin.project.repository_checkout import RepositoryError

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path


__all__ = [
    "ContributionBinding",
    "ContributionOperations",
    "PullRequest",
    "contribution_scope",
    "get_contribution_binding",
]


@dataclass(frozen=True)
class PullRequest:
    """Verified remote contribution identity, including its current head."""

    number: int
    url: str
    repository: str
    branch: str
    base: str
    head_sha: str
    state: str


class ContributionOperations(Protocol):
    """Broker contract; each call rechecks execution and repository authority.

    Reads return None only for authoritative absence. Failures raise
    RepositoryError. Push/create failures may be ambiguous; never retry those
    writes inside the adapter. No raw credentials appear in arguments or results.
    """

    def branch_sha(self, binding: ContributionBinding, branch: str) -> str | None:
        """Look up the selected repository's exact branch."""
        ...

    def push(self, binding: ContributionBinding, branch: str, sha: str) -> None:
        """Publish the exact local commit using externally authorized transport."""
        ...

    def find_pr(self, binding: ContributionBinding, branch: str) -> PullRequest | None:
        """Find the head/base pair including closed and merged PRs."""
        ...

    def create_pr(
        self, binding: ContributionBinding, branch: str, title: str, body: str
    ) -> PullRequest:
        """Create one draft PR; the caller reconciles uncertain outcomes."""
        ...


@dataclass(frozen=True)
class ContributionBinding:
    """Stable references supplied by trusted launch code, never model arguments."""

    execution_id: str
    contribution_id: str
    repository: str
    checkout: Path
    base_branch: str
    base_sha: str
    operations: ContributionOperations


_BINDING: ContextVar[ContributionBinding | None] = ContextVar(
    "penguin_contribution_binding", default=None
)


@contextmanager
def contribution_scope(binding: ContributionBinding) -> Iterator[None]:
    """Install an execution binding without mutating global credentials.

    Launch integration owns the scope lifetime, cancellation, external authority,
    and bot commit identity through tool_environment_scope. This local context is
    not an authorization boundary against code executing inside the Sprite.
    """
    if not all(
        (
            binding.execution_id,
            binding.contribution_id,
            binding.repository,
            binding.base_branch,
            binding.base_sha,
        )
    ):
        raise RepositoryError("Incomplete contribution binding.")
    token = _BINDING.set(binding)
    try:
        yield
    finally:
        _BINDING.reset(token)


def get_contribution_binding(
    repository: str, checkout: Path
) -> ContributionBinding | None:
    """Resolve a trusted binding and reject cross-checkout or cross-repository use."""
    binding = _BINDING.get()
    if binding and (
        binding.repository.lower() != repository.lower()
        or binding.checkout.resolve() != checkout.resolve()
    ):
        raise RepositoryError("Contribution binding does not match this checkout.")
    return binding
