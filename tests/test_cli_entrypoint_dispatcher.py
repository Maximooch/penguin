"""Dispatcher behavior tests for Penguin CLI/TUI entrypoints."""

from __future__ import annotations

from typing import Callable, Sequence

from penguin.cli import entrypoint


def _capture_calls() -> tuple[
    list[tuple[str, list[str]]],
    Callable[[Sequence[str] | None], int],
    Callable[[Sequence[str] | None], int],
]:
    calls: list[tuple[str, list[str]]] = []

    def _cli(argv: Sequence[str] | None = None) -> int:
        calls.append(("cli", list(argv or [])))
        return 12

    def _tui(argv: Sequence[str] | None = None) -> int:
        calls.append(("tui", list(argv or [])))
        return 34

    return calls, _cli, _tui


def test_main_defaults_to_tui(monkeypatch):
    calls, cli_stub, tui_stub = _capture_calls()
    monkeypatch.setattr(entrypoint, "main_cli", cli_stub)
    monkeypatch.setattr(entrypoint, "main_tui", tui_stub)

    code = entrypoint.main([])

    assert code == 34
    assert calls == [("tui", [])]


def test_main_routes_known_headless_command_to_cli(monkeypatch):
    calls, cli_stub, tui_stub = _capture_calls()
    monkeypatch.setattr(entrypoint, "main_cli", cli_stub)
    monkeypatch.setattr(entrypoint, "main_tui", tui_stub)

    code = entrypoint.main(["config", "setup"])

    assert code == 12
    assert calls == [("cli", ["config", "setup"])]


def test_main_routes_known_headless_flag_to_cli(monkeypatch):
    calls, cli_stub, tui_stub = _capture_calls()
    monkeypatch.setattr(entrypoint, "main_cli", cli_stub)
    monkeypatch.setattr(entrypoint, "main_tui", tui_stub)

    code = entrypoint.main(["--prompt", "hello"])

    assert code == 12
    assert calls == [("cli", ["--prompt", "hello"])]


def test_main_routes_tui_only_flag_to_tui(monkeypatch):
    calls, cli_stub, tui_stub = _capture_calls()
    monkeypatch.setattr(entrypoint, "main_cli", cli_stub)
    monkeypatch.setattr(entrypoint, "main_tui", tui_stub)

    code = entrypoint.main(["--url", "http://localhost:8000"])

    assert code == 34
    assert calls == [("tui", ["--url", "http://localhost:8000"])]


def test_main_routes_explicit_tui_alias_and_strips_prefix(monkeypatch):
    calls, cli_stub, tui_stub = _capture_calls()
    monkeypatch.setattr(entrypoint, "main_cli", cli_stub)
    monkeypatch.setattr(entrypoint, "main_tui", tui_stub)

    code = entrypoint.main(["tui", "--url", "http://localhost:8000"])

    assert code == 34
    assert calls == [("tui", ["--url", "http://localhost:8000"])]


def test_main_routes_explicit_cli_alias_and_strips_prefix(monkeypatch):
    calls, cli_stub, tui_stub = _capture_calls()
    monkeypatch.setattr(entrypoint, "main_cli", cli_stub)
    monkeypatch.setattr(entrypoint, "main_tui", tui_stub)

    code = entrypoint.main(["cli", "config", "setup"])

    assert code == 12
    assert calls == [("cli", ["config", "setup"])]


def test_main_routes_project_path_to_tui(monkeypatch):
    calls, cli_stub, tui_stub = _capture_calls()
    monkeypatch.setattr(entrypoint, "main_cli", cli_stub)
    monkeypatch.setattr(entrypoint, "main_tui", tui_stub)

    code = entrypoint.main(["."])

    assert code == 34
    assert calls == [("tui", ["."])]
