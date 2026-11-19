"""The VCS watcher polls only what a client watches, and backs off when idle.

The watcher ran up to seven ``git`` commands every two seconds for the server's
directory and for every directory any session had ever used, whether or not a
client was connected, for the life of the server. Each spawn also prints a
MallocStackLogging line on macOS, so an idle server flooded its log.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

import pytest

from penguin.web import sse_events
from penguin.web.services import system_status
from tests.api.test_sse_ledger_batching import _make_core

if TYPE_CHECKING:
    from pathlib import Path


def _core(directory: Path, sessions: dict[str, str] | None = None) -> Any:
    runtime = SimpleNamespace(active_root=str(directory), project_root=str(directory))
    return SimpleNamespace(
        runtime_config=runtime,
        _opencode_session_directories=dict(sessions or {}),
        event_bus=SimpleNamespace(emit=lambda *_a, **_k: asyncio.sleep(0)),
    )


async def _run_watcher(
    core: Any, monkeypatch: pytest.MonkeyPatch, *, changes: bool = False
) -> list[str]:
    polled: list[str] = []

    def fake_vcs_info(_core: Any, *, directory: str, emit_events: bool) -> dict:
        polled.append(directory)
        return {
            "vcs": "git",
            "worktree": directory,
            "branch": f"b{len(polled)}" if changes else "main",
            "head": "abc",
            "detached": False,
        }

    monkeypatch.setattr(system_status, "get_vcs_info", fake_vcs_info)
    monkeypatch.setattr(system_status, "VCS_POLL_MAX_INTERVAL_SECONDS", 0.16)
    task = asyncio.create_task(system_status._vcs_watch_loop(core, 0.02))
    await asyncio.sleep(0.5)
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
    return polled


@pytest.mark.asyncio
async def test_nothing_is_polled_without_a_watching_client(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    core = _core(tmp_path, {"old_session": str(tmp_path)})

    assert await _run_watcher(core, monkeypatch) == []


@pytest.mark.asyncio
async def test_an_unchanged_directory_backs_off(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    core = _core(tmp_path)
    key = system_status.watch_vcs_directory(core, str(tmp_path))

    idle = await _run_watcher(core, monkeypatch)
    busy = await _run_watcher(core, monkeypatch, changes=True)
    system_status.unwatch_vcs_directory(core, key)

    assert idle and set(idle) == {key}
    # 0.5 s at a 20 ms base interval: ~25 polls when every poll changes,
    # far fewer once an unchanged directory backs off toward 160 ms.
    assert len(idle) < len(busy) / 2


@pytest.mark.asyncio
async def test_an_sse_client_watches_its_directory_while_connected(
    tmp_path: Path,
) -> None:
    core, _bus = _make_core(tmp_path)
    response = await sse_events.events_sse(
        session_id=None,
        conversation_id=None,
        agent_id=None,
        directory=str(tmp_path),
        last_event_id=None,
        last_event_id_header=None,
    )
    stream = response.body_iterator
    await stream.__anext__()

    watched = dict(getattr(core, system_status.VCS_WATCHED_ATTR))
    await stream.aclose()

    assert watched == {str(tmp_path.resolve()): 1}
    assert not getattr(core, system_status.VCS_WATCHED_ATTR)
