"""Full-text search stays in step with the memories table.

Covers SM-92: the FTS5 index is an external-content table keyed by rowid, but
its triggers inserted without the rowid and removed rows with a plain DELETE,
which FTS5 does not support for external content. After an update or delete,
full-text hits pointed at the wrong memory, at none, or at deleted text.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from penguin.memory.providers.sqlite_provider import SQLiteMemoryProvider

if TYPE_CHECKING:
    from pathlib import Path


async def _provider(tmp_path: Path) -> SQLiteMemoryProvider:
    provider = SQLiteMemoryProvider(
        {"storage_path": str(tmp_path), "enable_embeddings": False}
    )
    await provider.initialize()
    return provider


async def _fts(provider: SQLiteMemoryProvider, query: str) -> list[str]:
    results = await provider.search_memory(query, filters={"search_mode": "fts"})
    return sorted(result["content"] for result in results)


@pytest.mark.asyncio
async def test_search_follows_updates_and_deletes(tmp_path: Path) -> None:
    provider = await _provider(tmp_path)
    try:
        first = await provider.add_memory("alpha apples")
        second = await provider.add_memory("bravo bananas")
        await provider.update_memory(first, content="charlie cherries")
        third = await provider.add_memory("delta dates")
        await provider.delete_memory(second)

        assert await _fts(provider, "cherries") == ["charlie cherries"]
        assert await _fts(provider, "apples") == []
        assert await _fts(provider, "bananas") == []
        assert await _fts(provider, "dates") == ["delta dates"]
        assert third
    finally:
        await provider.close()


_OLD_TRIGGERS = (
    """CREATE TRIGGER memories_fts_insert AFTER INSERT ON memories BEGIN
        INSERT INTO memories_fts(id, content, categories)
        VALUES (new.id, new.content, new.categories); END""",
    """CREATE TRIGGER memories_fts_delete AFTER DELETE ON memories BEGIN
        DELETE FROM memories_fts WHERE id = old.id; END""",
    """CREATE TRIGGER memories_fts_update AFTER UPDATE ON memories BEGIN
        DELETE FROM memories_fts WHERE id = old.id;
        INSERT INTO memories_fts(id, content, categories)
        VALUES (new.id, new.content, new.categories); END""",
)


@pytest.mark.asyncio
async def test_a_database_with_the_old_triggers_is_repaired(tmp_path: Path) -> None:
    provider = await _provider(tmp_path)
    connection = provider._connection
    for name in ("insert", "delete", "update"):
        connection.execute(f"DROP TRIGGER memories_fts_{name}")
    for sql in _OLD_TRIGGERS:
        connection.execute(sql)
    first = await provider.add_memory("alpha apples")
    await provider.add_memory("bravo bananas")
    await provider.update_memory(first, content="charlie cherries")
    await provider.add_memory("delta dates")
    await provider.close()

    reopened = await _provider(tmp_path)
    try:
        assert await _fts(reopened, "cherries") == ["charlie cherries"]
        assert await _fts(reopened, "dates") == ["delta dates"]
    finally:
        await reopened.close()
