"""The ledger's size limit frees disk space instead of emptying the ledger.

``PRAGMA incremental_vacuum`` only frees pages as its result rows are read,
and the ledger never read them, so deleted rows left free pages behind and the
file never shrank. Measured by file size, the ledger then stayed over its cap
for good, and every cleanup deleted all but one row (seen in the field: 13
rows in a 1.5 GB file).
"""

from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING

from penguin.system.runtime_event_ledger import (
    RuntimeEventLedger,
    RuntimeEventLedgerPolicy,
)
from penguin.system.runtime_events import (
    build_runtime_event,
    reset_runtime_event_sequences,
)

if TYPE_CHECKING:
    from pathlib import Path


def _events(start: int, count: int) -> list[dict]:
    return [
        build_runtime_event(
            event_type="message.updated",
            payload={"sessionID": "ses_1", "text": f"{index} " + "x" * 2000},
        )
        for index in range(start, start + count)
    ]


def test_size_cleanup_shrinks_the_file_and_keeps_recent_events(
    tmp_path: Path,
) -> None:
    reset_runtime_event_sequences()
    path = tmp_path / "events.db"
    ledger = RuntimeEventLedger(
        path,
        policy=RuntimeEventLedgerPolicy(
            max_events=100_000,
            max_age_seconds=None,
            max_bytes=400_000,
            cleanup_interval_seconds=0,
        ),
    )
    for batch in range(10):
        ledger.extend(_events(batch * 100, 100))

    with sqlite3.connect(path) as conn:
        free_pages = conn.execute("PRAGMA freelist_count").fetchone()[0]
        rows = conn.execute("SELECT COUNT(*) FROM runtime_events").fetchone()[0]

    assert free_pages < 20
    assert path.stat().st_size < 600_000
    assert rows > 50  # roughly the cap's worth of recent events, not one row


def test_a_bloated_file_keeps_its_events(tmp_path: Path) -> None:
    reset_runtime_event_sequences()
    path = tmp_path / "events.db"
    roomy = RuntimeEventLedgerPolicy(
        max_events=100_000,
        max_age_seconds=None,
        max_bytes=None,
        cleanup_interval_seconds=0,
    )
    ledger = RuntimeEventLedger(path, policy=roomy)
    ledger.extend(_events(0, 400))
    with sqlite3.connect(path) as conn:  # leave ~1 MB of free pages behind
        conn.execute("DELETE FROM runtime_events WHERE rowid > 20")
    kept = RuntimeEventLedger(
        path,
        policy=RuntimeEventLedgerPolicy(
            max_events=100_000,
            max_age_seconds=None,
            max_bytes=400_000,
            cleanup_interval_seconds=0,
        ),
    )

    kept.cleanup()

    with sqlite3.connect(path) as conn:
        rows = conn.execute("SELECT COUNT(*) FROM runtime_events").fetchone()[0]
    assert rows == 20
    assert path.stat().st_size < 400_000
