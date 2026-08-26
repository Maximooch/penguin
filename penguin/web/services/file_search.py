"""Fast, workspace-scoped filename search for web clients."""

from __future__ import annotations

import asyncio
import heapq
import itertools
import logging
import os
import time
from collections import OrderedDict
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from threading import Lock
from typing import TYPE_CHECKING, Literal

from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer

if TYPE_CHECKING:
    from watchdog.observers.api import ObservedWatch

logger = logging.getLogger(__name__)

__all__ = ["FileSearchService", "get_file_search_service"]

SearchKind = Literal["all", "file", "directory"]
Scanner = Callable[[str], tuple[list[str], list[str]]]

_SKIP_DIR_NAMES = {
    ".git",
    ".hg",
    ".svn",
    "node_modules",
    "dist",
    "build",
    "target",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".venv",
    "venv",
}


@dataclass(frozen=True, slots=True)
class SearchEntry:
    """Precomputed searchable fields for one relative path."""

    path: str
    normalized: str
    basename: str
    is_directory: bool
    is_hidden: bool


@dataclass(frozen=True, slots=True)
class IndexSnapshot:
    """Immutable view of a workspace filename index."""

    generation: int
    built_at: float
    entries: tuple[SearchEntry, ...]
    files: tuple[SearchEntry, ...]
    directories: tuple[SearchEntry, ...]


@dataclass(slots=True)
class WorkspaceIndex:
    """Mutable coordination state around immutable snapshots."""

    root: str
    snapshot: IndexSnapshot | None = None
    build_task: asyncio.Task[IndexSnapshot] | None = None
    dirty: bool = False
    change_generation: int = 0
    last_access: float = field(default_factory=time.monotonic)
    cache: OrderedDict[tuple[int, SearchKind, str, int], tuple[str, ...]] = field(
        default_factory=OrderedDict
    )
    watch: ObservedWatch | None = None


class _ChangeHandler(FileSystemEventHandler):
    """Invalidate a workspace index when searchable paths change."""

    def __init__(self, service: FileSearchService, root: str) -> None:
        self._service = service
        self._root = root

    def on_created(self, event: FileSystemEvent) -> None:
        self._invalidate(event)

    def on_deleted(self, event: FileSystemEvent) -> None:
        self._invalidate(event)

    def on_moved(self, event: FileSystemEvent) -> None:
        self._invalidate(event)

    def _invalidate(self, event: FileSystemEvent) -> None:
        paths = [event.src_path]
        destination = getattr(event, "dest_path", None)
        if isinstance(destination, str) and destination:
            paths.append(destination)
        if any(self._service.is_searchable_change(self._root, path) for path in paths):
            self._service.invalidate(self._root)


class FileSearchService:
    """Own workspace indexes and serve low-latency filename queries."""

    def __init__(
        self,
        *,
        scanner: Scanner | None = None,
        max_workspaces: int = 16,
        max_query_cache: int = 128,
        watch: bool = True,
        refresh_delay: float = 0.075,
    ) -> None:
        self._scanner = scanner or self.scan_directory
        self._max_workspaces = max_workspaces
        self._max_query_cache = max_query_cache
        self._watch_enabled = watch
        self._refresh_delay = refresh_delay
        self._indexes: OrderedDict[str, WorkspaceIndex] = OrderedDict()
        self._lock = Lock()
        self._observer: Observer | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._refresh_handles: dict[str, asyncio.TimerHandle] = {}

    async def start(self) -> None:
        """Start the shared filesystem observer."""
        self._loop = asyncio.get_running_loop()
        if not self._watch_enabled or self._observer is not None:
            return
        observer = Observer()
        observer.start()
        self._observer = observer

    async def stop(self) -> None:
        """Stop filesystem observation and pending index builds."""
        with self._lock:
            tasks = [state.build_task for state in self._indexes.values()]
            handles = list(self._refresh_handles.values())
            self._refresh_handles.clear()
            self._indexes.clear()
        for handle in handles:
            handle.cancel()
        for task in tasks:
            if task is not None and not task.done():
                task.cancel()
        observer = self._observer
        self._observer = None
        if observer is not None:
            observer.stop()
            await asyncio.to_thread(observer.join, 2)
        self._loop = None

    async def search(
        self,
        directory: str,
        query: str,
        *,
        kind: SearchKind = "all",
        limit: int = 10,
    ) -> list[str]:
        """Search a workspace snapshot, building it once when cold."""
        root = self._normalize_root(directory)
        if root is None:
            return []
        self._remember_loop()
        state = self._get_or_create_state(root)
        snapshot = await self._snapshot(state)
        normalized_query = query.strip().lower()
        key = (snapshot.generation, kind, normalized_query, limit)

        with self._lock:
            cached = state.cache.get(key)
            if cached is not None:
                state.cache.move_to_end(key)
                return list(cached)

        entries = self._entries(snapshot, kind, normalized_query)
        if len(entries) >= 20_000:
            result = await asyncio.to_thread(
                self._search_entries, entries, normalized_query, limit
            )
        else:
            result = self._search_entries(entries, normalized_query, limit)
        with self._lock:
            if state.snapshot is snapshot:
                state.cache[key] = tuple(result)
                state.cache.move_to_end(key)
                while len(state.cache) > self._max_query_cache:
                    state.cache.popitem(last=False)
        return result

    def prewarm(self, directory: str) -> None:
        """Schedule a deduplicated index build without waiting for it."""
        root = self._normalize_root(directory)
        if root is None:
            return
        self._remember_loop()
        state = self._get_or_create_state(root)
        self._ensure_build(state)

    def invalidate(self, directory: str) -> None:
        """Mark a workspace dirty and debounce a background refresh."""
        root = self._normalize_root(directory)
        if root is None:
            return
        with self._lock:
            state = self._indexes.get(root)
            if state is None:
                return
            state.dirty = True
            state.change_generation += 1
        loop = self._loop
        if loop is None or loop.is_closed():
            return
        loop.call_soon_threadsafe(self._schedule_refresh, root)

    async def wait_for_idle(self) -> None:
        """Wait until scheduled refreshes and active builds complete."""
        if self._refresh_delay:
            await asyncio.sleep(self._refresh_delay + 0.02)
        while True:
            with self._lock:
                tasks = [
                    state.build_task
                    for state in self._indexes.values()
                    if state.build_task is not None and not state.build_task.done()
                ]
            if not tasks:
                return
            await asyncio.gather(*tasks, return_exceptions=True)

    def clear(self) -> None:
        """Clear cached workspace state; intended for tests and explicit reset."""
        with self._lock:
            states = list(self._indexes.values())
            self._indexes.clear()
            handles = list(self._refresh_handles.values())
            self._refresh_handles.clear()
        for handle in handles:
            handle.cancel()
        observer = self._observer
        if observer is not None:
            for state in states:
                if state.watch is not None:
                    observer.unschedule(state.watch)

    @staticmethod
    def is_searchable_change(root: str, changed_path: str) -> bool:
        """Return whether a watcher event can affect the searchable index."""
        try:
            relative = Path(changed_path).resolve().relative_to(Path(root).resolve())
        except (OSError, ValueError):
            return False
        return not any(part in _SKIP_DIR_NAMES for part in relative.parts)

    @staticmethod
    def scan_directory(directory: str) -> tuple[list[str], list[str]]:
        """Enumerate searchable paths while preserving existing route semantics."""
        root = Path(directory).expanduser().resolve()
        if not root.is_dir():
            return [], []
        files: list[str] = []
        directories: list[str] = []
        pending = [("", str(root))]
        while pending:
            relative, current = pending.pop()
            children: list[tuple[str, str]] = []
            try:
                with os.scandir(current) as entries:
                    for entry in entries:
                        name = entry.name
                        path = f"{relative}/{name}" if relative else name
                        try:
                            is_directory = entry.is_dir(follow_symlinks=True)
                            if is_directory:
                                if name in _SKIP_DIR_NAMES or name in {".", ".."}:
                                    continue
                                directories.append(f"{path}/")
                                if not entry.is_symlink():
                                    children.append((path, entry.path))
                            else:
                                files.append(path)
                        except OSError:
                            continue
            except OSError:
                continue
            pending.extend(reversed(children))
        files.sort()
        directories.sort()
        return files, directories

    def _remember_loop(self) -> None:
        loop = asyncio.get_running_loop()
        if self._observer is None or self._loop is None or self._loop.is_closed():
            self._loop = loop

    @staticmethod
    def _normalize_root(directory: str) -> str | None:
        if not directory:
            return None
        root = Path(directory).expanduser().resolve()
        if not root.is_dir():
            return None
        return str(root)

    def _get_or_create_state(self, root: str) -> WorkspaceIndex:
        evicted: WorkspaceIndex | None = None
        with self._lock:
            state = self._indexes.get(root)
            if state is None:
                state = WorkspaceIndex(root=root)
                self._indexes[root] = state
            state.last_access = time.monotonic()
            self._indexes.move_to_end(root)
            if len(self._indexes) > self._max_workspaces:
                _, evicted = self._indexes.popitem(last=False)
        if evicted is not None:
            self._unschedule(evicted)
        self._schedule_watch(state)
        return state

    async def _snapshot(self, state: WorkspaceIndex) -> IndexSnapshot:
        with self._lock:
            snapshot = state.snapshot
            dirty = state.dirty
        if snapshot is not None:
            if dirty:
                self._ensure_build(state)
            return snapshot
        return await asyncio.shield(self._ensure_build(state))

    def _ensure_build(self, state: WorkspaceIndex) -> asyncio.Task[IndexSnapshot]:
        with self._lock:
            task = state.build_task
            if task is not None and not task.done():
                return task
            task = asyncio.create_task(self._build(state))
            state.build_task = task
            return task

    async def _build(self, state: WorkspaceIndex) -> IndexSnapshot:
        started = time.perf_counter()
        with self._lock:
            change_generation = state.change_generation
        files, directories = await asyncio.to_thread(self._scanner, state.root)
        with self._lock:
            generation = (state.snapshot.generation if state.snapshot else 0) + 1
        file_entries = tuple(self._entry(path, False) for path in files)
        directory_entries = tuple(self._entry(path, True) for path in directories)
        snapshot = IndexSnapshot(
            generation=generation,
            built_at=time.monotonic(),
            entries=(*file_entries, *directory_entries),
            files=file_entries,
            directories=directory_entries,
        )
        with self._lock:
            state.snapshot = snapshot
            state.dirty = state.change_generation != change_generation
            needs_follow_up = state.dirty
            state.cache.clear()
        logger.debug(
            "Built file-search index root=%s entries=%s duration_ms=%.1f generation=%s",
            state.root,
            len(snapshot.entries),
            (time.perf_counter() - started) * 1000,
            generation,
        )
        if needs_follow_up:
            self._schedule_refresh(state.root)
        return snapshot

    @staticmethod
    def _entry(path: str, is_directory: bool) -> SearchEntry:
        normalized = path.lower()
        basename = normalized.rstrip("/").rsplit("/", 1)[-1]
        hidden = any(
            part.startswith(".") and len(part) > 1
            for part in normalized.rstrip("/").split("/")
        )
        return SearchEntry(path, normalized, basename, is_directory, hidden)

    @staticmethod
    def _entries(
        snapshot: IndexSnapshot, kind: SearchKind, query: str
    ) -> Sequence[SearchEntry]:
        if not query and kind != "file":
            return snapshot.directories
        if kind == "file":
            return snapshot.files
        if kind == "directory":
            return snapshot.directories
        return snapshot.entries

    @classmethod
    def _search_entries(
        cls, entries: Sequence[SearchEntry], query: str, limit: int
    ) -> list[str]:
        targets_hidden = query.startswith(".") or "/." in query
        if not query:
            visible = (entry.path for entry in entries if not entry.is_hidden)
            hidden = (entry.path for entry in entries if entry.is_hidden)
            return list(itertools.islice(itertools.chain(visible, hidden), limit))

        groups: tuple[Sequence[SearchEntry], ...]
        if targets_hidden:
            groups = (entries,)
        else:
            groups = (
                tuple(entry for entry in entries if not entry.is_hidden),
                tuple(entry for entry in entries if entry.is_hidden),
            )

        result: list[str] = []
        for group in groups:
            remaining = limit - len(result)
            if remaining <= 0:
                return result
            cheap, unmatched = cls._rank_cheap_matches(group, query, remaining)
            result.extend(cheap)
            remaining = limit - len(result)
            if remaining <= 0:
                return result
            result.extend(cls._rank_subsequence_matches(unmatched, query, remaining))
        return result

    @staticmethod
    def _rank_cheap_matches(
        entries: Sequence[SearchEntry], query: str, limit: int
    ) -> tuple[list[str], list[SearchEntry]]:
        """Rank exact, prefix, and substring matches in one corpus pass."""
        stages: list[list[tuple[tuple[int, int, str], str]]] = [
            [] for _ in range(5)
        ]
        unmatched: list[SearchEntry] = []
        for entry in entries:
            candidate = entry.normalized
            basename = entry.basename
            detail: int
            if candidate == query or basename == query:
                stage, detail = 0, 0
            elif basename.startswith(query):
                stage, detail = 1, 0
            elif candidate.startswith(query):
                stage, detail = 2, 0
            elif (index := basename.find(query)) >= 0:
                stage, detail = 3, index
            elif (index := candidate.find(query)) >= 0:
                stage, detail = 4, index
            else:
                unmatched.append(entry)
                continue
            stages[stage].append(((detail, len(entry.path), candidate), entry.path))

        result: list[str] = []
        for ranked in stages:
            remaining = limit - len(result)
            if remaining <= 0:
                break
            result.extend(path for _, path in heapq.nsmallest(remaining, ranked))
        return result, unmatched

    @staticmethod
    def _rank_subsequence_matches(
        entries: Sequence[SearchEntry], query: str, limit: int
    ) -> list[str]:
        """Rank fuzzy subsequences only when cheap matching cannot fill top-K."""
        basename_matches: list[tuple[tuple[int, int, str], str]] = []
        path_matches: list[tuple[tuple[int, int, str], str]] = []
        for entry in entries:
            gap = FileSearchService._subsequence_gap(query, entry.basename)
            if gap is not None:
                basename_matches.append(
                    ((gap, len(entry.path), entry.normalized), entry.path)
                )
                continue
            gap = FileSearchService._subsequence_gap(query, entry.normalized)
            if gap is not None:
                path_matches.append(
                    ((gap, len(entry.path), entry.normalized), entry.path)
                )

        result = [
            path for _, path in heapq.nsmallest(limit, basename_matches)
        ]
        remaining = limit - len(result)
        if remaining > 0:
            result.extend(
                path for _, path in heapq.nsmallest(remaining, path_matches)
            )
        return result

    @staticmethod
    def _score(
        query: str, entry: SearchEntry, targets_hidden: bool
    ) -> tuple[int, int, int, int, str] | None:
        match = FileSearchService._match(query, entry)
        if match is None:
            return None
        stage, detail = match
        hidden = 0 if targets_hidden or not entry.is_hidden else 1
        return (hidden, stage, detail, len(entry.path), entry.normalized)

    @staticmethod
    def _match(query: str, entry: SearchEntry) -> tuple[int, int] | None:
        """Return the first matching relevance stage and its detail score."""
        for stage in range(7):
            detail = FileSearchService._stage_detail(query, entry, stage)
            if detail is not None:
                return (stage, detail)
        return None

    @staticmethod
    def _stage_detail(query: str, entry: SearchEntry, stage: int) -> int | None:
        """Return detail score when an entry's first match is at ``stage``."""
        candidate = entry.normalized
        basename = entry.basename
        if stage == 0:
            return 0 if candidate == query or basename == query else None
        if stage == 1:
            return 0 if basename.startswith(query) else None
        if stage == 2:
            return 0 if candidate.startswith(query) else None
        if stage == 3:
            return basename.find(query) if query in basename else None
        if stage == 4:
            return candidate.find(query) if query in candidate else None
        if stage == 5:
            return FileSearchService._subsequence_gap(query, basename)
        return FileSearchService._subsequence_gap(query, candidate)

    @staticmethod
    def _subsequence_gap(query: str, candidate: str) -> int | None:
        cursor = 0
        last = -1
        gap = 0
        for char in query:
            found = candidate.find(char, cursor)
            if found < 0:
                return None
            if last >= 0:
                gap += max(found - last - 1, 0)
            last = found
            cursor = found + 1
        return gap

    def _schedule_refresh(self, root: str) -> None:
        with self._lock:
            prior = self._refresh_handles.pop(root, None)
        if prior is not None:
            prior.cancel()
        loop = asyncio.get_running_loop()
        handle = loop.call_later(self._refresh_delay, self._refresh, root)
        with self._lock:
            self._refresh_handles[root] = handle

    def _refresh(self, root: str) -> None:
        with self._lock:
            self._refresh_handles.pop(root, None)
            state = self._indexes.get(root)
        if state is not None:
            self._ensure_build(state)

    def _schedule_watch(self, state: WorkspaceIndex) -> None:
        observer = self._observer
        if observer is None or state.watch is not None:
            return
        try:
            state.watch = observer.schedule(
                _ChangeHandler(self, state.root), state.root, recursive=True
            )
        except OSError:
            logger.warning(
                "Unable to watch file-search root %s", state.root, exc_info=True
            )

    def _unschedule(self, state: WorkspaceIndex) -> None:
        observer = self._observer
        if observer is not None and state.watch is not None:
            observer.unschedule(state.watch)


_FILE_SEARCH_SERVICE = FileSearchService()


def get_file_search_service() -> FileSearchService:
    """Return the process-wide file-search service."""
    return _FILE_SEARCH_SERVICE
