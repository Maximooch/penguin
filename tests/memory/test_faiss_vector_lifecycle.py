"""FAISS memory keeps one vector per live memory.

Covers SM-91: an update appended a new vector and a delete removed only the
metadata, so the index filled with orphan vectors. Search mapped result
positions back to memories and dropped orphans, so a memory that existed
stopped being found once its own old vectors outranked it.
"""

from __future__ import annotations

import hashlib
import sys
from types import ModuleType
from typing import TYPE_CHECKING

import pytest

np = pytest.importorskip("numpy")
pytest.importorskip("faiss")

from penguin.memory.providers.faiss_provider import FAISSMemoryProvider  # noqa: E402

if TYPE_CHECKING:
    from pathlib import Path

DIMENSION = 16


class _Encoder:
    """Deterministic unit vectors: the same text always gets the same vector."""

    def __init__(self, *_args: object, **_kwargs: object) -> None:
        pass

    def encode(self, texts: list[str]) -> np.ndarray:
        rows = []
        for text in texts:
            seed = int(hashlib.sha256(text.encode()).hexdigest()[:8], 16)
            row = np.random.default_rng(seed).standard_normal(DIMENSION)
            rows.append(row / np.linalg.norm(row))
        return np.asarray(rows, dtype="float32")


@pytest.fixture
def provider_factory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    fake = ModuleType("sentence_transformers")
    fake.SentenceTransformer = _Encoder
    monkeypatch.setitem(sys.modules, "sentence_transformers", fake)

    async def make() -> FAISSMemoryProvider:
        provider = FAISSMemoryProvider(
            {"storage_path": str(tmp_path), "dimension": DIMENSION}
        )
        await provider.initialize()
        return provider

    return make


@pytest.mark.asyncio
async def test_updated_and_deleted_memories_leave_no_vectors(provider_factory) -> None:
    provider = await provider_factory()
    kept = await provider.add_memory("charlie")
    gone = await provider.add_memory("bravo")
    for content in ("delta", "charlie", "delta", "charlie"):
        await provider.update_memory(kept, content=content)
    await provider.delete_memory(gone)

    results = await provider.search_memory("charlie", max_results=1)

    assert [result["id"] for result in results] == [kept]
    assert provider._index.ntotal == 1
    deleted = await provider.search_memory("bravo", max_results=5)
    assert gone not in {result["id"] for result in deleted}


@pytest.mark.asyncio
async def test_the_index_survives_a_restart(provider_factory) -> None:
    first = await provider_factory()
    memory = await first.add_memory("echo")
    await first.update_memory(memory, content="foxtrot")

    second = await provider_factory()

    assert second._index.ntotal == 1
    results = await second.search_memory("foxtrot", max_results=1)
    assert [result["id"] for result in results] == [memory]


@pytest.mark.asyncio
async def test_an_index_saved_with_orphans_is_rebuilt(
    provider_factory,
) -> None:
    import json

    import faiss

    provider = await provider_factory()
    memory = await provider.add_memory("golf")
    storage = provider.storage_dir
    # The earlier format: a plain flat index with an orphan, found by position.
    flat = faiss.IndexFlatIP(DIMENSION)
    flat.add(_Encoder().encode(["golf", "hotel"]))
    faiss.write_index(flat, str(storage / "faiss.index"))
    metadata = json.loads((storage / "metadata.json").read_text())
    metadata[memory].pop("vector_id")
    metadata[memory]["index_position"] = 0
    (storage / "metadata.json").write_text(json.dumps(metadata))

    reopened = await provider_factory()

    assert reopened._index.ntotal == 1
    results = await reopened.search_memory("golf", max_results=1)
    assert [result["id"] for result in results] == [memory]
