"""Two processes saving the session index do not lose each other's entries.

Covers SM-95: the index was read, merged and written under a lock that only
covered one process, so when the web server and the CLI saved at the same
time, the later writer replaced the file from a stale read and dropped the
other's new session, which neither process wrote again.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from typing import TYPE_CHECKING

import pytest

from penguin.system.session_manager import SessionManager

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.skipif(os.name == "nt", reason="uses fcntl in the peer")

# A peer process: take the index lock, read the index, wait (while the test
# saves), then write the read index plus its own entry.
_PEER = """
import fcntl, json, sys, time
from pathlib import Path
index = Path(sys.argv[1])
with open(str(index) + ".lock", "a+b") as handle:
    fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
    Path(sys.argv[2]).write_text("locked")
    entries = json.loads(index.read_text()) if index.exists() else {}
    time.sleep(1.0)
    entries["peer_session"] = {"title": "from the peer"}
    index.write_text(json.dumps(entries))
"""


def test_a_concurrent_peer_save_keeps_both_entries(tmp_path: Path) -> None:
    manager = SessionManager(base_path=str(tmp_path))
    index = tmp_path / "session_index.json"
    ready = tmp_path / "peer_ready"
    peer = subprocess.Popen(
        [sys.executable, "-c", _PEER, str(index), str(ready)],
    )
    try:
        for _ in range(500):
            if ready.exists():
                break
            time.sleep(0.01)
        assert ready.exists()

        session = manager.create_session()  # saves the index while the peer waits
        peer.wait(timeout=10)
    finally:
        peer.kill()

    entries = json.loads(index.read_text())
    assert session.id in entries
    assert "peer_session" in entries
