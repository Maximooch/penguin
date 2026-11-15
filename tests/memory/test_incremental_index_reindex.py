"""Re-indexing a file replaces its memory, and the index metadata is never half-written.

Covers SM-61: re-indexing a changed file added a new memory and kept the old
one, so every edit left another copy; and the metadata file was rewritten in
place, so a failed write left it corrupt and the next load re-indexed
everything.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import pytest

from penguin.memory.indexing import metadata as metadata_module
from penguin.memory.indexing.incremental import IncrementalIndexer
from penguin.memory.indexing.metadata import IndexMetadata

if TYPE_CHECKING:
    from pathlib import Path


class _Provider:
    embedding_model = "test-embed"

    def __init__(self) -> None:
        self.memories: dict[str, str] = {}
        self._next = 0

    async def add_memory(
        self,
        content: str,
        metadata: dict[str, Any] | None = None,
        categories: list[str] | None = None,
    ) -> str:
        del metadata, categories
        self._next += 1
        memory_id = f"mem_{self._next}"
        self.memories[memory_id] = content
        return memory_id

    async def delete_memory(self, memory_id: str) -> bool:
        return self.memories.pop(memory_id, None) is not None


@pytest.mark.asyncio
async def test_reindexing_a_changed_file_keeps_one_memory(tmp_path: Path) -> None:
    provider = _Provider()
    indexer = IncrementalIndexer(provider, {"workspace_path": str(tmp_path)})
    note = tmp_path / "notes.md"
    note.write_text("# First version\n\nOriginal text.\n")
    await indexer._process_file(str(note))

    note.write_text("# Second version\n\nChanged text.\n")
    await indexer._process_file(str(note))

    assert len(provider.memories) == 1
    assert "Changed text" in next(iter(provider.memories.values()))


def test_a_failed_metadata_write_keeps_the_previous_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / ".penguin_index.json"
    tracked = tmp_path / "a.txt"
    tracked.write_text("a")
    metadata = IndexMetadata(path)
    metadata.update_file_metadata(str(tracked), "hash_a", "test-embed")
    before = path.read_text()

    def failing_dump(data: Any, handle: Any, **_kwargs: Any) -> None:
        handle.write('{"partial": ')
        raise OSError("disk full")

    monkeypatch.setattr(metadata_module.json, "dump", failing_dump)
    metadata.update_file_metadata(str(tracked), "hash_b", "test-embed")
    monkeypatch.undo()

    assert path.read_text() == before
    assert json.loads(path.read_text())[str(tracked)]["content_hash"] == "hash_a"
