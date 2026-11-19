"""A failed PyDoll start does not leave the manager looking ready (SM-58).

``initialize`` set ``self.browser`` before ``start()``. When the start failed,
the half-made browser stayed, so the next ``initialize`` skipped the setup and
reported success, and every later tool call ran against a browser that never
started.
"""

from __future__ import annotations

import sys
import types
from typing import Any

import pytest

from penguin.tools.pydoll_tools import PyDollBrowserManager


def _fake_pydoll(monkeypatch: pytest.MonkeyPatch, starts: list[bool]) -> list[Any]:
    """Install a fake ``pydoll`` whose browsers start per ``starts``, in order."""
    made: list[Any] = []

    class Options:
        binary_location = ""

        def add_argument(self, _argument: str) -> None:
            return None

    class Chrome:
        def __init__(self, options: Any) -> None:
            self.stopped = False
            made.append(self)

        async def start(self) -> None:
            if not starts.pop(0):
                raise RuntimeError("chrome did not start")

        async def get_page(self) -> object:
            return object()

        async def stop(self) -> None:
            self.stopped = True

    chrome = types.ModuleType("pydoll.browser.chrome")
    chrome.Chrome = Chrome  # type: ignore[attr-defined]
    options = types.ModuleType("pydoll.browser.options")
    options.Options = Options  # type: ignore[attr-defined]
    for name, module in {
        "pydoll": types.ModuleType("pydoll"),
        "pydoll.browser": types.ModuleType("pydoll.browser"),
        "pydoll.browser.chrome": chrome,
        "pydoll.browser.options": options,
    }.items():
        monkeypatch.setitem(sys.modules, name, module)
    return made


@pytest.mark.asyncio
async def test_a_failed_start_is_not_reported_ready_next_time(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    made = _fake_pydoll(monkeypatch, [False, False])
    manager = PyDollBrowserManager()

    assert await manager.initialize() is False
    assert manager.browser is None and manager.initialized is False
    assert made[0].stopped is True

    assert await manager.initialize() is False  # tried again, did not skip
    assert len(made) == 2


@pytest.mark.asyncio
async def test_a_later_start_can_succeed(monkeypatch: pytest.MonkeyPatch) -> None:
    made = _fake_pydoll(monkeypatch, [False, True])
    manager = PyDollBrowserManager()

    assert await manager.initialize() is False
    assert await manager.initialize() is True
    assert manager.browser is made[1] and manager.initialized is True
    await manager.close()
