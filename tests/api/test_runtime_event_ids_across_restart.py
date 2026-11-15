"""Event ids stay unique, and sequences increase, across a restart.

Covers SM-78: each stream's sequence counted from 1 in every process, but the
ledger outlives the process and ignores an event whose id it already holds.
After a restart, new events reused old ids: the ledger dropped them, and a
client reconnecting with one of those ids was replayed the previous run's
events instead of the new ones.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from penguin.system import runtime_event_ledger
from penguin.system.runtime_events import (
    build_runtime_event,
    reset_runtime_event_sequences,
)

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path


def _message(text: str) -> dict:
    return build_runtime_event(
        event_type="message.updated",
        payload={"sessionID": "ses_1", "text": text},
        stream_id="session:ses_1",
    )


@pytest.fixture
def ledger_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    path = tmp_path / "runtime_events.db"
    monkeypatch.setenv("PENGUIN_RUNTIME_EVENT_LEDGER_PATH", str(path))
    monkeypatch.setattr(runtime_event_ledger, "_PROCESS_LEDGER", None)
    reset_runtime_event_sequences()
    yield path
    reset_runtime_event_sequences()


def _restart(
    monkeypatch: pytest.MonkeyPatch,
) -> runtime_event_ledger.RuntimeEventLedger:
    """Forget everything a process keeps in memory, then open the ledger again."""
    reset_runtime_event_sequences()
    monkeypatch.setattr(runtime_event_ledger, "_PROCESS_LEDGER", None)
    return runtime_event_ledger.get_runtime_event_ledger()


def test_events_after_a_restart_get_new_ids(
    ledger_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ledger = runtime_event_ledger.get_runtime_event_ledger()
    first_run = [_message(f"run 1, event {index}") for index in range(3)]
    assert ledger.extend(first_run) == 3

    ledger = _restart(monkeypatch)
    second_run = _message("run 2, event 0")

    assert second_run["sequence"] == 4
    assert ledger.append(second_run) is True
    replay = ledger.replay_after(first_run[-1]["id"])
    assert [event["id"] for event in replay.events] == [second_run["id"]]


def test_the_web_app_opens_the_ledger_before_building_its_core(
    ledger_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from penguin.web import app as web_app

    ledger = runtime_event_ledger.get_runtime_event_ledger()
    assert ledger.extend([_message(f"run 1, event {index}") for index in range(3)])
    reset_runtime_event_sequences()
    monkeypatch.setattr(runtime_event_ledger, "_PROCESS_LEDGER", None)
    started: list[dict] = []
    monkeypatch.setattr(web_app, "_core_instance", None)
    monkeypatch.setattr(
        web_app, "_create_core", lambda: started.append(_message("core start"))
    )

    web_app.get_or_create_core()

    assert started[0]["sequence"] == 4
