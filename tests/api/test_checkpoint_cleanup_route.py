"""Checkpoint cleanup HTTP contract tests."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi import HTTPException

from penguin.web import routes


class _CleanupCore:
    """Minimal checkpoint cleanup facade for route contract tests."""

    def __init__(self, result: dict[str, Any] | BaseException) -> None:
        self.result = result
        self.calls: list[dict[str, Any]] = []

    async def cleanup_old_checkpoints(
        self,
        *,
        execute: bool,
        confirmation: str | None,
    ) -> dict[str, Any]:
        """Record one call and return or raise the configured result."""

        self.calls.append({"execute": execute, "confirmation": confirmation})
        if isinstance(self.result, BaseException):
            raise self.result
        return dict(self.result)


@pytest.mark.asyncio
async def test_cleanup_route_defaults_to_read_only_plan() -> None:
    """Calling cleanup without flags cannot mutate checkpoint storage."""

    core = _CleanupCore(
        {
            "status": "dry_run",
            "cleaned_count": 0,
            "plan": {"candidate_count": 2},
        }
    )

    result = await routes.cleanup_old_checkpoints(core=core)

    assert core.calls == [{"execute": False, "confirmation": None}]
    assert result["status"] == "dry_run"
    assert result["plan"]["candidate_count"] == 2
    assert "no checkpoints were changed" in result["message"]


@pytest.mark.asyncio
async def test_cleanup_route_surfaces_missing_confirmation_as_conflict() -> None:
    """Explicit execution without exact workspace confirmation fails closed."""

    core = _CleanupCore(PermissionError("exact workspace confirmation required"))

    with pytest.raises(HTTPException) as raised:
        await routes.cleanup_old_checkpoints(execute=True, core=core)

    assert raised.value.status_code == 409
    assert "confirmation" in str(raised.value.detail)
    assert core.calls == [{"execute": True, "confirmation": None}]
