"""
Prototype app to exercise Penguin TUI visuals without any LLM/API calls.

Run:
  python -m penguin.penguin.cli.tui_prototype_mock
or
  python penguin/penguin/cli/tui_prototype_mock.py

Keys:
  d  - inject a demo assistant message
  s  - simulate a streaming assistant reply
  a  - simulate an Action (request + result)
  t  - simulate a Tool (call + result)
  e  - simulate an error card
  Ctrl+Q/Ctrl+C - quit (inherited)

You can also use:
  /theme list | /theme set <ocean|nord|dracula>
  /layout set <flat|boxed>
  /view set <compact|detailed>
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict

import sys
from pathlib import Path

from textual.widgets import Static, Input  # type: ignore
from textual.containers import VerticalScroll  # type: ignore
from rich.panel import Panel  # type: ignore

# Ensure the package root is on sys.path when running this file directly
_PKG_PARENT = Path(__file__).resolve().parents[2]  # .../Penguin/penguin
if str(_PKG_PARENT) not in sys.path:
    sys.path.insert(0, str(_PKG_PARENT))

from penguin.cli.tui import PenguinTextualApp
from penguin.cli.command_registry import CommandRegistry


class PrototypePenguinApp(PenguinTextualApp):
    """Subclass of the real app that skips Core init and offers demo actions."""

    BINDINGS = PenguinTextualApp.BINDINGS + [
        ("d", "demo_message", "Demo msg"),
        ("s", "stream_sample", "Stream"),
        ("a", "action_sample", "Action"),
        ("t", "tool_sample", "Tool"),
        ("e", "error_sample", "Error"),
    ]

    async def on_mount(self) -> None:  # type: ignore[override]
        # Do NOT initialize PenguinCore; this is a mocked environment
        self.query_one("#status-bar", Static).update("Prototype mode: no LLM calls.")
        self.query_one(Input).focus()

        # Prepare command registry so /theme, /layout, /view work locally
        self.command_registry = CommandRegistry()

        # Seed micro-status bar with mock data updater
        async def _mock_status():
            # Pretend model name and tokens change
            cur = 0
            while True:
                try:
                    cur = (cur + 37) % 500
                    self._view_mode = getattr(self, "_view_mode", "compact")
                    if self._view_mode == "detailed":
                        self.query_one("#micro-status", Static).update(
                            f"mock-model  |  tokens: {cur}/200000 (0.0%)  |  ⏱ demo"
                        )
                    else:
                        self.query_one("#micro-status", Static).update("")
                except Exception:
                    pass
                await asyncio.sleep(1.0)

        asyncio.create_task(_mock_status())

        welcome_panel = Panel(
            "🐧 Prototype TUI (no LLM)\n\n"
            "Keys: D demo msg, S stream, A action, T tool, E error.\n"
            "Commands: /theme, /layout, /view.",
            title="Welcome",
            border_style="cyan",
        )
        self.query_one("#message-area", VerticalScroll).mount(Static(welcome_panel))
        # Show sidebar in detailed view for the prototype
        self._status_visible = True

    # ------------- Demo actions -------------
    async def action_demo_message(self) -> None:
        await self.handle_core_event(
            "message",
            {
                "role": "assistant",
                "content": (
                    "Here is a short demo reply.\n\n"
                    "```python\nprint('hello from Penguin prototype')\n```\n"
                ),
                "category": "DIALOG",
            },
        )

    async def action_stream_sample(self) -> None:
        long_md = (
            "Here is a longer, streaming markdown demo.\n\n"
            "### Bullet list\n- One\n- Two\n- Three\n\n"
            "### Code\n```python\nfor i in range(5):\n    print(i)\n```\n\n"
            "### Table\n| A | B |\n|---|---|\n| 1 | 2 |\n| 3 | 4 |\n\n"
            "### Paragraphs\n"
            + ("Lorem ipsum dolor sit amet, consectetur adipiscing elit. " * 12)
            + "\n\nEnd.\n"
        )
        chunks = [long_md[i:i+160] for i in range(0, len(long_md), 160)]
        for i, ch in enumerate(chunks, 1):
            await self.handle_core_event(
                "stream_chunk",
                {
                    "chunk": ch,
                    "is_final": i == len(chunks),
                    "stream_id": "demo",
                    "message_type": "assistant",
                },
            )
            await asyncio.sleep(0.05)
        # Belt-and-suspenders: force a final flush to render any trailing markdown
        await self.handle_core_event(
            "stream_chunk",
            {"chunk": "", "is_final": True, "stream_id": "demo", "message_type": "assistant"},
        )

    async def action_action_sample(self) -> None:
        # Action request
        await self.handle_core_event(
            "action",
            {
                "type": "execute",
                "params": "print('checking file…')",
                "id": "a1",
            },
        )
        # Result
        await self.handle_core_event(
            "action_result",
            {"result": "cwd=/tmp\nexists: False", "status": "completed", "id": "a1"},
        )

    async def action_tool_sample(self) -> None:
        # Tool call
        await self.handle_core_event(
            "tool_call",
            {"name": "workspace_search", "arguments": {"query": "auth flow", "max": 3}, "id": "t1"},
        )
        # Tool result
        await self.handle_core_event(
            "tool_result",
            {
                "action_name": "workspace_search",
                "result": "- auth.py:42 authenticate(user)\n- login.py:10 auth()",
                "status": "completed",
                "id": "t1",
            },
        )

    async def action_error_sample(self) -> None:
        await self.handle_core_event(
            "error",
            {"message": "Sample error while parsing", "context": "prototype"},
        )


def main() -> None:
    app = PrototypePenguinApp()
    app.run()


if __name__ == "__main__":
    main()


