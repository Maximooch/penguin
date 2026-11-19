"""``/exit`` in the headless REPL ends the chat loop.

Covers SM-69: the ``/exit`` command marked the interface inactive and
returned ``status: exit``, but the REPL checked neither and prompted again.
"""

from __future__ import annotations

import io
from types import SimpleNamespace
from typing import Any

import pytest
from rich.console import Console

from penguin.cli import cli as cli_module
from penguin.cli.cli import PenguinCLI
from penguin.cli.streaming_manager import StreamingManager


@pytest.mark.asyncio
async def test_slash_exit_ends_the_chat_loop(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli_module, "setup_logger", lambda *_a, **_k: None)
    monkeypatch.setattr(cli_module, "_print_ascii_banner", lambda *_a, **_k: None)
    prompts: list[str] = []
    inputs = iter(["/exit", "exit"])

    async def prompt_async(*_args: Any, **_kwargs: Any) -> str:
        value = next(inputs)
        prompts.append(value)
        return value

    async def handle_command(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        return {"status": "exit", "message": "Goodbye!"}

    cli = PenguinCLI.__new__(PenguinCLI)
    cli.console = Console(file=io.StringIO())
    cli.session = SimpleNamespace(prompt_async=prompt_async)
    cli.message_count = 0
    cli.interface = SimpleNamespace(handle_command=handle_command)
    cli.display_manager = SimpleNamespace(display_message=lambda *_a, **_k: None)
    cli.streaming_manager = StreamingManager(SimpleNamespace(is_active=False))
    cli._ensure_progress_cleared = lambda: None
    cli.core = None
    cli.current_conversation_turn = 0
    cli.last_completed_message = ""
    cli.last_completed_message_normalized = ""
    cli.processed_messages = set()
    cli.message_turn_map = {}

    await cli.chat_loop()

    assert prompts == ["/exit"]
