"""Each isolated runtime keeps its own permission audit logger.

Covers SM-96: configuring the audit logger rebound one module-global logger,
so under isolated ACP sessions the first tool call in each new root replaced
the logger of every earlier runtime: their in-memory entries were dropped and
they all logged under the last runtime's workspace.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from penguin.core_runtime.isolation import RuntimeServices
from penguin.security import audit

if TYPE_CHECKING:
    from pathlib import Path

    import pytest


def test_each_runtime_configures_its_own_audit_logger(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(audit, "_audit_logger", None)
    first, second = RuntimeServices(), RuntimeServices()

    with first.activate():
        configured = audit.configure_audit_logger(workspace_root=str(tmp_path / "a"))
    with second.activate():
        audit.configure_audit_logger(workspace_root=str(tmp_path / "b"))

    with first.activate():
        assert audit.get_audit_logger() is configured
    assert audit._audit_logger is None  # the process-wide logger is untouched
