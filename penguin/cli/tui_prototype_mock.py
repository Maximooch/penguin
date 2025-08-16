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
import os
import argparse

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
        ("h", "stress_stream_heavy", "Stress stream"),
        ("j", "stress_scroll_while_streaming", "Scroll test"),
        ("r", "stress_tools_heavy", "Stress tools"),
        ("b", "jump_bottom", "Bottom"),
        ("A", "toggle_autoscroll", "Autoscroll"),
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
        # Demo message with inline ActionTag, then emit a separate tool call/result
        # to mirror the typical duplication sequence seen in real runs.
        content = (
            "Here is a short demo reply.\n\n"
            # Small inline code block
            "```python\nprint('hello from Penguin prototype')\n```\n\n"
            # Large ActionTag block (to trigger auto-collapse preview in compact)
            "```actionxml\n<execute>\nimport os\nfrom pathlib import Path\n\nbase = Path('demo.txt')\nif not base.exists():\n    base.write_text('demo\n', encoding='utf-8')\nprint('exists?', base.exists())\nfor i in range(10):\n    print('line', i)\nprint('done')\n</execute>\n```\n\n"
            # Diff block should remain fully expanded
            "```diff\n--- a/demo.txt\n+++ b/demo.txt\n@@ -1,1 +1,3 @@\n-demo\n+demo\n+added-1\n+added-2\n```\n"
        )
        await self.handle_core_event(
            "message",
            {"role": "assistant", "content": content, "category": "DIALOG"},
        )
        # Emit the same tool call + result the engine would send afterwards
        await self.handle_core_event(
            "tool_call",
            {"name": "workspace_search", "arguments": {"query": "auth flow", "max": 3}, "id": "dup1"},
        )
        # Produce a long result list to exercise preview/expander on tool results
        long_listing = "\n".join(
            [f"- src/module_{i:02d}.py:{i} func_{i}()" for i in range(1, 36)]
        )
        await self.handle_core_event(
            "tool_result",
            {
                "action_name": "workspace_search",
                "result": long_listing,
                "status": "completed",
                "id": "dup1",
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

    async def action_stress_stream_heavy(self) -> None:
        """Spam a large number of streaming chunks to stress throughput and scroll debouncing."""
        # Build a long text with mixed markdown/code
        base = (
            "### Stress paragraph\n" + ("lorem ipsum dolor sit amet "+"consectetur adipiscing elit ")*8 + "\n\n"
            + "```python\nfor i in range(20):\n    print(i)\n```\n\n"
        )
        payload = base * 40  # ~40 blocks
        chunks = [payload[i:i+192] for i in range(0, len(payload), 192)]
        start = asyncio.get_event_loop().time()
        total = len(chunks)
        for idx, ch in enumerate(chunks, 1):
            await self.handle_core_event(
                "stream_chunk",
                {
                    "chunk": ch,
                    "is_final": False,
                    "stream_id": "stress",
                    "message_type": "assistant",
                },
            )
            if (idx % 25) == 0:
                # Simulate user interaction while streaming: occasional scroll up/down
                try:
                    area = self.query_one("#message-area", VerticalScroll)
                    if (idx // 25) % 2 == 0:
                        area.scroll_home(animate=False)
                    else:
                        area.scroll_end(animate=False)
                except Exception:
                    pass
            await asyncio.sleep(0.005)
        # finalize
        await self.handle_core_event(
            "stream_chunk",
            {"chunk": "", "is_final": True, "stream_id": "stress", "message_type": "assistant"},
        )
        dur = asyncio.get_event_loop().time() - start
        try:
            self.query_one("#status-bar", Static).update(f"Stress stream: {total} chunks in {dur:.2f}s (~{total/dur:.1f} cps)")
        except Exception:
            pass

    async def action_stress_scroll_while_streaming(self) -> None:
        """Start a streaming response while continuously toggling scroll to emulate user behavior."""
        # Fire and forget a scroller
        async def _scroller():
            for _ in range(50):
                try:
                    area = self.query_one("#message-area", VerticalScroll)
                    area.scroll_home(animate=False)
                    await asyncio.sleep(0.03)
                    area.scroll_end(animate=False)
                except Exception:
                    pass
                await asyncio.sleep(0.03)
        asyncio.create_task(_scroller())

        # Stream medium-size content concurrently
        text = ("Streaming under scroll test. " * 40) + "\n" + ("data "+"* ")*200
        chunks = [text[i:i+160] for i in range(0, len(text), 160)]
        for i, ch in enumerate(chunks, 1):
            await self.handle_core_event(
                "stream_chunk",
                {
                    "chunk": ch,
                    "is_final": i == len(chunks),
                    "stream_id": "scrolltest",
                    "message_type": "assistant",
                },
            )
            await asyncio.sleep(0.01)

    async def action_stress_tools_heavy(self) -> None:
        """Emit many tool results with large outputs to exercise collapsibles and lazy mounting."""
        for i in range(1, 16):
            # tool call
            await self.handle_core_event(
                "tool_call",
                {"name": "workspace_search", "arguments": {"query": f"stress-{i}", "max": 5}, "id": f"tool{i}"},
            )
            # large result body
            big = "\n".join([f"{i:02d}:{j:04d} result line for stress test" for j in range(0, 600)])
            await self.handle_core_event(
                "tool_result",
                {
                    "action_name": "workspace_search",
                    "result": big,
                    "status": "completed",
                    "id": f"tool{i}",
                },
            )
        try:
            self.query_one("#status-bar", Static).update("Stress tools: emitted 15 large tool results")
        except Exception:
            pass

    def action_jump_bottom(self) -> None:
        """Jump to bottom and (re)enable autoscroll."""
        try:
            self._autoscroll = True
            self._scroll_to_bottom()
            self.query_one("#status-bar", Static).update("Autoscroll ON; jumped to bottom")
        except Exception:
            pass

    def action_toggle_autoscroll(self) -> None:
        """Toggle autoscroll flag to validate behavior while streaming."""
        try:
            self._autoscroll = not getattr(self, "_autoscroll", True)
            state = "ON" if self._autoscroll else "OFF"
            self.query_one("#status-bar", Static).update(f"Autoscroll {state}")
        except Exception:
            pass

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
        long_listing = "\n".join(
            [f"- pkg/file_{i:02d}.py:{i} call_{i}()" for i in range(1, 28)]
        )
        await self.handle_core_event(
            "tool_result",
            {
                "action_name": "workspace_search",
                "result": long_listing,
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
    parser = argparse.ArgumentParser(description="Run Penguin TUI prototype")
    parser.add_argument("--profile", action="store_true", help="Enable pyinstrument HTML profiling")
    parser.add_argument(
        "--profile-out",
        default=str(Path(__file__).resolve().with_name("tui_profile.html")),
        help="HTML profile output path (used with --profile)",
    )
    parser.add_argument("--speedscope", action="store_true", help="Write Speedscope JSON profile")
    parser.add_argument(
        "--speedscope-out",
        default=str(Path(__file__).resolve().with_name("tui_profile.speedscope")),
        help="Speedscope JSON output path (used with --speedscope)",
    )
    args = parser.parse_args()

    # Ensure output directory exists if profiling
    if args.profile or args.speedscope:
        out_path = Path(args.profile_out).expanduser()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        ss_out_path = Path(args.speedscope_out).expanduser()
        ss_out_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            from pyinstrument import Profiler  # type: ignore
        except Exception:
            print("[Profiler] pyinstrument not installed. Install with: uv pip install pyinstrument", file=sys.stderr)
            # Fallback to normal run
            app = PrototypePenguinApp()
            app.run()
            return
        profiler = Profiler()
        profiler.start()
        try:
            app = PrototypePenguinApp()
            app.run()
        finally:
            profiler.stop()
            try:
                if args.profile:
                    profiler.write_html(out_path)
                    print(f"[Profiler] Wrote HTML profile to: {out_path}")
                if args.speedscope:
                    try:
                        from pyinstrument.renderers.speedscope import SpeedscopeRenderer  # type: ignore
                        rendered = SpeedscopeRenderer().render(profiler.last_session)
                        with open(ss_out_path, "w", encoding="utf-8") as f:
                            f.write(rendered)
                        print(f"[Profiler] Wrote Speedscope profile to: {ss_out_path}")
                    except Exception as e:
                        print(f"[Profiler] Failed to write Speedscope profile: {e}", file=sys.stderr)
            except Exception as e:
                print(f"[Profiler] Failed to write profile: {e}", file=sys.stderr)
    else:
        app = PrototypePenguinApp()
        app.run()


if __name__ == "__main__":
    main()


