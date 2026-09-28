"""Tests for the backend file-search index service."""

from __future__ import annotations

import asyncio
import heapq
import time
from threading import Event, Lock
from typing import TYPE_CHECKING

import pytest

from penguin.web.services.file_search import FileSearchService

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.asyncio
async def test_concurrent_cold_searches_share_one_index_build(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "README.md").write_text("hello", encoding="utf-8")
    calls = 0
    calls_lock = Lock()

    def scan(root: str):
        nonlocal calls
        with calls_lock:
            calls += 1
        time.sleep(0.05)
        return FileSearchService.scan_directory(root)

    service = FileSearchService(scanner=scan, watch=False)

    results = await asyncio.gather(
        *(
            service.search(str(repo), "readme", kind="all", limit=10)
            for _ in range(8)
        )
    )

    assert calls == 1
    assert all(result == ["README.md"] for result in results)


@pytest.mark.asyncio
async def test_cold_index_build_does_not_block_event_loop(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "README.md").write_text("hello", encoding="utf-8")
    scan_started = Event()
    release_scan = Event()

    def scan(root: str):
        scan_started.set()
        release_scan.wait(timeout=2)
        return FileSearchService.scan_directory(root)

    service = FileSearchService(scanner=scan, watch=False)
    search = asyncio.create_task(
        service.search(str(repo), "readme", kind="all", limit=10)
    )

    assert await asyncio.to_thread(scan_started.wait, 1)
    await asyncio.wait_for(asyncio.sleep(0), timeout=0.1)
    release_scan.set()

    assert await search == ["README.md"]


@pytest.mark.asyncio
async def test_warm_search_reuses_precomputed_snapshot(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "README.md").write_text("hello", encoding="utf-8")
    calls = 0

    def scan(root: str):
        nonlocal calls
        calls += 1
        return FileSearchService.scan_directory(root)

    service = FileSearchService(scanner=scan, watch=False)

    assert await service.search(str(repo), "read", kind="all", limit=10) == [
        "README.md"
    ]
    assert await service.search(str(repo), "readm", kind="all", limit=10) == [
        "README.md"
    ]
    assert calls == 1


@pytest.mark.asyncio
async def test_invalidation_serves_stale_snapshot_while_rebuilding(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "old.txt").write_text("old", encoding="utf-8")
    release_refresh = Event()
    calls = 0

    def scan(root: str):
        nonlocal calls
        calls += 1
        if calls > 1:
            release_refresh.wait(timeout=2)
        return FileSearchService.scan_directory(root)

    service = FileSearchService(scanner=scan, watch=False, refresh_delay=0)
    assert await service.search(str(repo), "old", kind="all", limit=10) == [
        "old.txt"
    ]

    (repo / "new.txt").write_text("new", encoding="utf-8")
    service.invalidate(str(repo))

    stale = await asyncio.wait_for(
        service.search(str(repo), "old", kind="all", limit=10), timeout=0.2
    )
    assert stale == ["old.txt"]

    release_refresh.set()
    await service.wait_for_idle()
    assert await service.search(str(repo), "new", kind="all", limit=10) == [
        "new.txt"
    ]


@pytest.mark.asyncio
async def test_change_during_rebuild_triggers_follow_up_refresh(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "old.txt").write_text("old", encoding="utf-8")
    refresh_started = Event()
    release_refresh = Event()
    calls = 0

    def scan(root: str):
        nonlocal calls
        calls += 1
        result = FileSearchService.scan_directory(root)
        if calls == 2:
            refresh_started.set()
            release_refresh.wait(timeout=2)
        return result

    service = FileSearchService(scanner=scan, watch=False, refresh_delay=0)
    assert await service.search(str(repo), "old", kind="all", limit=10)

    (repo / "during.txt").write_text("during", encoding="utf-8")
    service.invalidate(str(repo))
    await asyncio.to_thread(refresh_started.wait, 1)
    (repo / "after.txt").write_text("after", encoding="utf-8")
    service.invalidate(str(repo))
    release_refresh.set()

    await service.wait_for_idle()
    assert calls == 3
    assert await service.search(str(repo), "after", kind="all", limit=10) == [
        "after.txt"
    ]


@pytest.mark.asyncio
async def test_watcher_refreshes_index_after_file_creation(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    service = FileSearchService(refresh_delay=0.02)
    await service.start()
    try:
        assert await service.search(str(repo), "new", kind="all", limit=10) == []
        (repo / "new.txt").write_text("new", encoding="utf-8")

        deadline = time.monotonic() + 2
        result: list[str] = []
        while time.monotonic() < deadline:
            await service.wait_for_idle()
            result = await service.search(str(repo), "new", kind="all", limit=10)
            if result:
                break
            await asyncio.sleep(0.02)

        assert result == ["new.txt"]
    finally:
        await service.stop()


@pytest.mark.asyncio
async def test_search_preserves_type_hidden_and_skip_rules(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "visible").mkdir()
    (repo / ".hidden").mkdir()
    (repo / ".hidden" / "secret.txt").write_text("x", encoding="utf-8")
    (repo / "node_modules").mkdir()
    (repo / "node_modules" / "ignored.js").write_text("x", encoding="utf-8")

    service = FileSearchService(watch=False)

    assert await service.search(str(repo), "", kind="directory", limit=10) == [
        "visible/",
        ".hidden/",
    ]
    hidden = await service.search(str(repo), ".hid", kind="all", limit=10)
    assert hidden[:1] == [".hidden/"]
    assert await service.search(str(repo), "ignored", kind="all", limit=10) == []


@pytest.mark.parametrize(
    "query",
    ["src", "main", "rdm", "nested/file", ".hidden", "missing"],
)
def test_staged_search_matches_full_score_ranking(query: str) -> None:
    service = FileSearchService(watch=False)
    entries = tuple(
        service._entry(path, path.endswith("/"))
        for path in (
            "README.md",
            "src/",
            "src/main.py",
            "src/nested/file-search.ts",
            "docs/readme-guide.md",
            ".hidden/",
            ".hidden/main.txt",
        )
    )
    targets_hidden = query.startswith(".") or "/." in query
    ranked = (
        (score, entry.path)
        for entry in entries
        if (score := service._score(query, entry, targets_hidden)) is not None
    )
    expected = [path for _, path in heapq.nsmallest(10, ranked)]

    assert service._search_entries(entries, query, 10) == expected


def test_watcher_ignores_changes_inside_skipped_directories(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    ignored = repo / "node_modules" / "package" / "index.js"
    searchable = repo / "src" / "main.py"

    assert not FileSearchService.is_searchable_change(str(repo), str(ignored))
    assert FileSearchService.is_searchable_change(str(repo), str(searchable))
