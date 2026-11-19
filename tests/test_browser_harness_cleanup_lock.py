"""Browser-harness cleanup waits for any helper call in progress.

Covers SM-59: cleanup reloaded the harness modules and rewrote ``BU_NAME``
without the helpers lock that every other harness call holds, so it could
repoint an in-flight call at a different daemon. No browser is started: the
harness modules are replaced with fakes.
"""

from __future__ import annotations

import threading
import time
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

from penguin.tools import browser_harness_tools
from penguin.tools.browser_harness_ownership import BrowserHarnessOwnershipStore
from penguin.tools.browser_harness_tools import BrowserHarnessAdapter

if TYPE_CHECKING:
    from pathlib import Path


def test_cleanup_waits_for_a_helper_call_in_progress(
    tmp_path: Path, monkeypatch: Any
) -> None:
    ownership_path = tmp_path / "ownership.json"
    BrowserHarnessOwnershipStore(str(ownership_path)).record_started(
        {"bu_name": "penguin-a", "started_by_penguin": True}
    )
    adapter = BrowserHarnessAdapter(
        config={"name": "penguin-a", "ownership_path": str(ownership_path)},
        execution_context={},
    )
    restarted_at: list[float] = []
    admin = SimpleNamespace(
        restart_daemon=lambda _name: restarted_at.append(time.monotonic())
    )
    monkeypatch.setattr(adapter, "_load_modules", lambda env=None: (admin, None))

    released_at: list[float] = []
    holding = threading.Event()

    def helper_call_in_progress() -> None:
        with browser_harness_tools._HELPERS_LOCK:
            holding.set()
            time.sleep(0.3)
            released_at.append(time.monotonic())

    worker = threading.Thread(target=helper_call_in_progress)
    worker.start()
    assert holding.wait(2)

    result = adapter.cleanup()
    worker.join(2)

    assert "error" not in result
    assert restarted_at and released_at
    assert restarted_at[0] >= released_at[0]
