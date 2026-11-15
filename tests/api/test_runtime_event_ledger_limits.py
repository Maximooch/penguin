"""A zero or "off" event-count limit keeps events, like the other ledger limits.

Covers SM-94: ``PENGUIN_RUNTIME_EVENT_LEDGER_MAX_EVENTS=0`` emptied the ledger
on every cleanup, while ``0``/``off`` disables the size limit and a zero age
limit disables age cleanup, so every reconnect got a replay gap.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from penguin.system.runtime_event_ledger import RuntimeEventLedger, policy_from_env
from penguin.system.runtime_events import (
    build_runtime_event,
    reset_runtime_event_sequences,
)

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.parametrize("value", ["0", "off", "none", "disabled"])
def test_a_disabled_count_limit_keeps_events(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    monkeypatch.setenv("PENGUIN_RUNTIME_EVENT_LEDGER_MAX_EVENTS", value)
    reset_runtime_event_sequences()
    ledger = RuntimeEventLedger(tmp_path / "events.db", policy=policy_from_env())
    events = [
        build_runtime_event(
            event_type="message.updated",
            payload={"sessionID": "ses_1", "text": str(index)},
        )
        for index in range(3)
    ]

    ledger.extend(events)

    assert all(ledger.contains(event["id"]) for event in events)
