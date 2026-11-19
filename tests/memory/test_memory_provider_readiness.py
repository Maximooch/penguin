"""The memory provider is either ready or not usable, and every route agrees.

Covers SM-93: a SQLite provider whose initialisation failed after opening its
connection kept that connection, so writes went in without full-text
indexing and each retry opened another connection; the memory routes built
or tested the provider in their own ways, so reading a memory or the stats
failed until a search had happened to create it.
"""

from __future__ import annotations

import sqlite3
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from penguin.memory.providers.base import MemoryProviderError
from penguin.memory.providers.sqlite_provider import SQLiteMemoryProvider
from penguin.web import routes

if TYPE_CHECKING:
    from pathlib import Path


class _NoFTSConnection:
    """A connection whose FTS5 table creation fails, as without FTS5 support."""

    def __init__(self, inner: sqlite3.Connection) -> None:
        self._inner = inner

    def execute(self, sql: str, *args: Any) -> Any:
        if "fts5" in sql:
            raise sqlite3.OperationalError("no such module: fts5")
        return self._inner.execute(sql, *args)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)


@pytest.mark.asyncio
async def test_a_failed_initialise_leaves_no_usable_connection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real_connect = sqlite3.connect
    monkeypatch.setattr(
        sqlite3,
        "connect",
        lambda *a, **k: _NoFTSConnection(real_connect(*a, **k)),
    )
    provider = SQLiteMemoryProvider(
        {"storage_path": str(tmp_path), "enable_embeddings": False}
    )

    with pytest.raises(Exception):
        await provider.initialize()

    assert provider._connection is None
    with pytest.raises(MemoryProviderError):
        await provider.add_memory("unindexed")


def test_reading_a_memory_initialises_the_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PENGUIN_AUTH_ENABLED", "false")

    class _Provider:
        async def get_memory(self, memory_id: str) -> dict[str, Any]:
            return {"id": memory_id, "content": "remembered"}

        async def get_memory_stats(self) -> dict[str, Any]:
            return {"total_memories": 1}

    class _ToolManager:
        _memory_provider = None

        async def ensure_memory_provider(self) -> Any:
            self._memory_provider = _Provider()
            return self._memory_provider

    core = SimpleNamespace(tool_manager=_ToolManager())
    app = FastAPI()
    app.include_router(routes.router)
    app.dependency_overrides[routes.get_core] = lambda: core
    client = TestClient(app)

    assert client.get("/api/v1/memory/m1").status_code == 200
    stats = client.get("/api/v1/memory/stats")
    assert stats.status_code == 200
    # Declared after /memory/{memory_id}, the stats route was never reached.
    assert "total_memories" in str(stats.json())
