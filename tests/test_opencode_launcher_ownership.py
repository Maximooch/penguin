"""The launcher only uses a Penguin server, and stops its own on SIGTERM.

Covers SM-48: any server answering 200 at the health path counted as Penguin,
including one that took the port after the launcher's own server failed to
start; and the launcher relied on atexit to stop its server, which does not
run when the launcher is terminated with SIGTERM.
"""

from __future__ import annotations

import json
import signal
import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

import pytest

from penguin.cli import opencode_launcher
from tests.test_opencode_launcher import _FakeProcess

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

PENGUIN_HEALTH = {"status": "healthy", "agent_capacity": {"available": 1}}


@contextmanager
def _health_server(body: dict[str, Any]) -> Iterator[str]:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            payload = json.dumps(body).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *_args: Any) -> None:
            return None

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()


def test_another_service_answering_the_health_path_is_not_penguin() -> None:
    with _health_server({"status": "ok"}) as base_url:
        assert opencode_launcher._is_server_running(base_url) is False


def test_a_penguin_health_response_is_recognised() -> None:
    with _health_server(PENGUIN_HEALTH) as base_url:
        assert opencode_launcher._is_server_running(base_url) is True


def test_a_server_is_not_ours_once_our_child_has_exited() -> None:
    with _health_server(PENGUIN_HEALTH) as base_url:
        exited = _FakeProcess(running=False)
        assert opencode_launcher._wait_for_server(base_url, exited, 1) is False


def test_sigterm_exits_the_launcher_normally_while_it_runs(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    seen: dict[str, Any] = {}
    previous = signal.getsignal(signal.SIGTERM)

    monkeypatch.setattr(opencode_launcher.atexit, "register", lambda *_a, **_k: None)
    monkeypatch.setattr(opencode_launcher, "_is_server_running", lambda *_a, **_k: True)
    monkeypatch.setattr(
        opencode_launcher,
        "_build_opencode_command",
        lambda *_a, **_k: (["opencode", str(project_dir)], None),
    )

    def run(*_args: Any, **_kwargs: Any) -> SimpleNamespace:
        seen["handler"] = signal.getsignal(signal.SIGTERM)
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(opencode_launcher.subprocess, "run", run)

    assert opencode_launcher.main([str(project_dir)]) == 0

    handler = seen["handler"]
    assert callable(handler)
    with pytest.raises(SystemExit) as exited:
        handler(signal.SIGTERM, None)
    assert exited.value.code == 128 + signal.SIGTERM
    assert signal.getsignal(signal.SIGTERM) == previous
