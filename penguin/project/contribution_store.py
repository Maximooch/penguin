"""Crash-safe local publication receipts; these are not authorization records."""

from __future__ import annotations

import json
import os
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Any

from penguin.project.repository_checkout import RepositoryError

if TYPE_CHECKING:
    from collections.abc import Iterator

    from penguin.project.git_integration import GitIntegration


__all__ = ["ContributionStore"]


class ContributionStore:
    """Serialize publication within one checkout and atomically persist progress."""

    def __init__(self, git: GitIntegration, key: str) -> None:
        self.directory = (
            Path(git.run("rev-parse", "--absolute-git-dir")) / "penguin-contributions"
        )
        self.directory.mkdir(exist_ok=True)
        self.path = self.directory / f"{key}.json"

    @contextmanager
    def lock(self) -> Iterator[None]:
        """Fail visibly on concurrent publication; OS releases locks after crashes."""
        try:
            import fcntl
        except ImportError:
            raise RepositoryError(
                "Contribution locking requires Linux or macOS."
            ) from None
        with (self.directory / "checkout.lock").open("a") as handle:
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise RepositoryError(
                    "Another contribution is using this checkout."
                ) from None
            try:
                yield
            finally:
                fcntl.flock(handle, fcntl.LOCK_UN)

    def read(self) -> dict[str, Any] | None:
        """Read a receipt or fail closed if existing progress is unreadable."""
        try:
            value = json.loads(self.path.read_text())
        except FileNotFoundError:
            return None
        except (OSError, ValueError):
            raise RepositoryError(
                "Contribution receipt requires reconciliation."
            ) from None
        if not isinstance(value, dict):
            raise RepositoryError("Invalid contribution receipt.")
        return value

    def write(self, state: dict[str, Any]) -> None:
        """Persist before side effects; flush data and directory metadata."""
        filename = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", dir=self.directory, delete=False
            ) as handle:
                filename = handle.name
                json.dump(state, handle, sort_keys=True)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(filename, self.path)
            fd = os.open(self.directory, os.O_RDONLY)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
        except OSError:
            raise RepositoryError("Cannot persist contribution progress.") from None
        finally:
            if filename:
                Path(filename).unlink(missing_ok=True)
