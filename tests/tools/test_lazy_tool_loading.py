"""A lazily loaded tool is built once, however many threads ask for it first.

Covers SM-60: lazy tool properties checked a flag and then built the tool
with no lock, so two tool calls on worker threads could each build their own
(two notebook executors, two browser managers) and one was silently replaced.
"""

from __future__ import annotations

import threading
import time
from typing import TYPE_CHECKING, Any

from penguin.tools import tool_manager as tool_manager_module
from penguin.tools.tool_manager import ToolManager

if TYPE_CHECKING:
    import pytest


def test_two_threads_get_one_notebook_executor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PENGUIN_YOLO", "1")
    built: list[Any] = []

    class SlowExecutor:
        def __init__(self) -> None:
            time.sleep(0.1)
            built.append(self)

    monkeypatch.setattr(tool_manager_module, "NotebookExecutor", SlowExecutor)
    manager = ToolManager({}, lambda *_args: None, fast_startup=True)
    start = threading.Barrier(2)
    seen: list[Any] = []

    def first_use() -> None:
        start.wait()
        seen.append(manager.notebook_executor)

    threads = [threading.Thread(target=first_use) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(5)

    assert len(built) == 1
    assert seen[0] is seen[1] is built[0]
