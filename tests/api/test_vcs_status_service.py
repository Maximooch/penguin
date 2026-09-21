"""Tests for VCS status service behavior and edge cases."""

from __future__ import annotations

import subprocess
from pathlib import Path
from types import SimpleNamespace

from penguin.web.services.system_status import get_vcs_info


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=str(repo),
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "git command failed")
    return result.stdout.strip()


def _commit(repo: Path, message: str) -> None:
    _git(repo, "add", "-A")
    _git(
        repo,
        "-c",
        "user.name=Penguin Test",
        "-c",
        "user.email=penguin-test@example.com",
        "commit",
        "-m",
        message,
    )


def _core(root: Path):
    runtime = SimpleNamespace(
        workspace_root=str(root),
        project_root=str(root),
        active_root=str(root),
    )

    class EventBus:
        async def emit(self, *_args, **_kwargs):
            return None

    return SimpleNamespace(
        runtime_config=runtime,
        event_bus=EventBus(),
        _opencode_session_directories={},
    )


def test_vcs_non_git_directory_returns_none(tmp_path: Path):
    core = _core(tmp_path)
    data = get_vcs_info(core, directory=str(tmp_path), emit_events=False)
    assert data["vcs"] == "none"
    assert data["branch"] == ""
    assert data["dirty"] is False


def test_vcs_git_branch_and_dirty_status(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    (repo / "file.txt").write_text("hello\n", encoding="utf-8")
    _commit(repo, "init")

    core = _core(repo)
    clean = get_vcs_info(core, directory=str(repo), emit_events=False)
    assert clean["vcs"] == "git"
    assert clean["branch"] == "main"
    assert clean["detached"] is False
    assert clean["dirty"] is False

    (repo / "file.txt").write_text("changed\n", encoding="utf-8")
    dirty = get_vcs_info(core, directory=str(repo), emit_events=False)
    assert dirty["dirty"] is True


def test_vcs_no_upstream_defaults_to_zero_ahead_behind(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "local")
    (repo / "file.txt").write_text("hello\n", encoding="utf-8")
    _commit(repo, "init")

    core = _core(repo)
    data = get_vcs_info(core, directory=str(repo), emit_events=False)
    assert data["upstream"] == ""
    assert data["ahead"] == 0
    assert data["behind"] == 0


def test_vcs_detached_head_reports_head_and_no_branch(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    (repo / "file.txt").write_text("one\n", encoding="utf-8")
    _commit(repo, "first")
    (repo / "file.txt").write_text("two\n", encoding="utf-8")
    _commit(repo, "second")
    _git(repo, "checkout", "--detach", "HEAD~1")

    core = _core(repo)
    data = get_vcs_info(core, directory=str(repo), emit_events=False)
    assert data["detached"] is True
    assert data["branch"] == ""
    assert data["head"] != ""


def test_vcs_linked_worktree_reports_shared_root(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    (repo / "file.txt").write_text("hello\n", encoding="utf-8")
    _commit(repo, "init")

    worktree = tmp_path / "wt"
    _git(repo, "worktree", "add", str(worktree), "-b", "wt-test")

    core = _core(repo)
    data = get_vcs_info(core, directory=str(worktree), emit_events=False)
    assert data["vcs"] == "git"
    assert Path(data["worktree"]).resolve() == worktree.resolve()
    assert Path(data["root"]).resolve() == repo.resolve()
    assert data["branch"] == "wt-test"


async def test_watcher_polls_once_per_directory_and_preserves_scopes(
    monkeypatch, tmp_path
):
    import asyncio

    from penguin.web.services import system_status as service

    core = _core(tmp_path)
    other = tmp_path / "other"
    other.mkdir()
    core._opencode_session_directories = {
        **{f"s{i}": str(tmp_path) for i in range(10)},
        "other": str(other),
    }
    monkeypatch.setattr(service, "_LAST_BRANCH_KEYS", {})
    calls, events = [], []
    loop = asyncio.get_running_loop()

    def git(args, cwd):
        calls.append((tuple(args), cwd))
        if args == ["rev-parse", "--show-toplevel"]:
            return cwd
        if args == ["symbolic-ref", "--short", "HEAD"]:
            return "main"
        if args == ["rev-parse", "--short", "HEAD"]:
            return "abc123"
        return ""

    async def emit(name, event):
        assert asyncio.get_running_loop() is loop
        events.append(event)

    passes = 0

    async def pause(_):
        nonlocal passes
        passes += 1
        if passes == 2:
            raise asyncio.CancelledError

    monkeypatch.setattr(service, "_run_git", git)
    monkeypatch.setattr(core.event_bus, "emit", emit)
    monkeypatch.setattr(service.asyncio, "sleep", pause)
    try:
        await service._vcs_watch_loop(core, 2.0)
    except asyncio.CancelledError:
        pass
    # Let the existing event scheduling complete without using patched sleep.
    done = loop.create_future()
    loop.call_soon(done.set_result, None)
    await done
    # Two directories, two passes, at most eight commands per snapshot.
    assert len(calls) <= 2 * 2 * 8
    # Default scope + eleven sessions; unchanged pass is silent.
    assert len(events) == 12
    properties = [event["properties"] for event in events]
    assert {p["sessionID"] for p in properties} == {
        None,
        *core._opencode_session_directories,
    }
    assert all(
        p["directory"] == (str(other) if p["sessionID"] == "other" else str(tmp_path))
        for p in properties
    )


async def test_watcher_slow_git_does_not_block_loop_and_cancels(monkeypatch, tmp_path):
    import asyncio
    import threading

    from penguin.web.services import system_status as service

    loop = asyncio.get_running_loop()
    entered = asyncio.Event()
    release = threading.Event()
    finished = threading.Event()
    calls = []

    def slow_snapshot(*args, **kwargs):
        calls.append(kwargs)
        loop.call_soon_threadsafe(entered.set)
        try:
            assert release.wait(2), "Git blocked the event loop"
            return {"vcs": "none"}
        finally:
            finished.set()

    monkeypatch.setattr(service, "get_vcs_info", slow_snapshot)
    task = asyncio.create_task(service._vcs_watch_loop(_core(tmp_path), 0))
    try:
        await asyncio.wait_for(entered.wait(), 1)
        assert not finished.is_set()
        task.cancel()
        try:
            await asyncio.wait_for(task, 1)
        except asyncio.CancelledError:
            pass
        assert task.cancelled()
        assert len(calls) == 1
    finally:
        release.set()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        await asyncio.to_thread(finished.wait, 2)
