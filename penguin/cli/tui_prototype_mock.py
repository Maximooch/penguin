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
  g  - response-thread demo (Final + expandable steps/tools)
  k  - 4-message response-thread demo (reasoning, code/tool, notes, final)
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
import json
import logging

from textual.widgets import Static, Input  # type: ignore
from textual.containers import VerticalScroll  # type: ignore
from rich.panel import Panel  # type: ignore

# Ensure the package root is on sys.path when running this file directly
_PKG_PARENT = Path(__file__).resolve().parents[2]  # .../Penguin/penguin
if str(_PKG_PARENT) not in sys.path:
    sys.path.insert(0, str(_PKG_PARENT))

from penguin.cli.tui import PenguinTextualApp
from penguin.cli.command_registry import CommandRegistry
import penguin.cli.tui as tui_mod


class PrototypePenguinApp(PenguinTextualApp):
    """Subclass of the real app that skips Core init and offers demo actions."""

    BINDINGS = PenguinTextualApp.BINDINGS + [
        ("d", "demo_message", "Demo msg"),
        ("s", "stream_sample", "Stream"),
        ("a", "action_sample", "Action"),
        ("t", "tool_sample", "Tool"),
        ("e", "error_sample", "Error"),
        ("h", "stress_stream_heavy", "Stress stream"),
        ("j", "response_thread_demo_detailed", "Thread detailed"),
        ("r", "stress_tools_heavy", "Stress tools"),
        ("b", "jump_bottom", "Bottom"),
        ("A", "toggle_autoscroll", "Autoscroll"),
        ("m", "demo_threaded_group", "Steps+Final thread"),
        ("g", "response_thread_demo", "RespThread"),
        ("k", "response_thread_demo_four", "Thread x4"),
        ("n", "sample_random_exec", "Rnd sample"),
        ("M", "demo_minimal_messages", "Minimal demo"),
    ]

    async def on_mount(self) -> None:  # type: ignore[override]
        # Do NOT initialize PenguinCore; this is a mocked environment
        try:
            # Log textual + expander state for prototype sessions
            try:
                import importlib.metadata as _md
                try:
                    _v = _md.version("textual")
                except Exception:
                    _v = "<unknown>"
            except Exception:
                _v = "<unknown>"
            try:
                import textual as _textual
                _p = getattr(_textual, "__file__", "<unknown>")
            except Exception:
                _p = "<unimportable>"
            logging.getLogger(__name__).info(
                "[proto] Textual: version=%s path=%s expander_present=%s", _v, _p, getattr(tui_mod, "Expander", None) is not None
            )
        except Exception:
            pass
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
                            f"mock-model  |  tokens: {cur}/200000 (0.0%)  |  demo"
                        )
                    else:
                        self.query_one("#micro-status", Static).update("")
                except Exception:
                    pass
                await asyncio.sleep(1.0)

        asyncio.create_task(_mock_status())

        welcome_panel = Panel(
            "Prototype TUI (no LLM)\n\n"
            "Keys: D demo msg, S stream, A action, T tool, E error, G RespThread, K 4-msg thread.\n"
            "Commands: /theme, /layout, /view, /minimal, /collapse, /crumb.",
            title="Welcome",
            border_style="cyan",
        )
        self.query_one("#message-area", VerticalScroll).mount(Static(welcome_panel))
        # Show sidebar in detailed view for the prototype
        self._status_visible = True

    async def action_demo_minimal_messages(self) -> None:
        """Emit a set of messages intended to showcase Minimal Mode styling."""
        # Enable minimal UI (messages only) and keep sidebar/input visible
        self._minimal_mode = True
        self._apply_minimal_class()
        # Turn on crumb bar with sample text
        self._crumb_enabled = True
        self._crumb_text = "Model: mock-gpt | tokens 3,211 | 1.8s"
        try:
            crumb = self.query_one("#crumb-bar")
            crumb.update(self._crumb_text)
            crumb.display = True
        except Exception:
            pass
        
        # Add multiple messages with reasoning and plain output format
        msg1 = (
            "<details>\n<summary>🧠 Click to show / hide internal reasoning</summary>\n\n"
            "I need to understand the auth flow first. Let me scan the codebase for token refresh logic. "
            "I'll use workspace_search to find relevant files, then examine the implementation. "
            "This should give me the context I need to provide accurate guidance.\n\n"
            "</details>\n\n"
            "Looking at the codebase structure to understand auth flow..."
        )
        self.add_message(msg1, "assistant")
        await asyncio.sleep(0.1)
        
        msg2 = (
            "<details>\n<summary>🧠 Click to show / hide internal reasoning</summary>\n\n"
            "Found `services/auth/token.py` with a `refresh_token` function. "
            "Let me examine its implementation to see how it currently works. "
            "I should check if there's already caching logic or if we need to add it.\n\n"
            "</details>\n\n"
            "Found the token refresh logic in `services/auth/token.py`. Here's the current implementation:\n\n"
            "```python\n"
            "def refresh_token(old_token: str) -> str:\n"
            "    # Validate old token\n"
            "    payload = verify(old_token)\n"
            "    # Generate new token\n"
            "    return create_token(payload)\n"
            "```"
        )
        self.add_message(msg2, "assistant")
        await asyncio.sleep(0.1)
        
        msg3 = (
            "<details>\n<summary>🧠 Click to show / hide internal reasoning</summary>\n\n"
            "I notice there's no caching layer yet. The current implementation just validates and creates a new token. "
            "For the requirement, we need to add Redis caching with 60s TTL and handle upstream failures gracefully.\n\n"
            "</details>\n\n"
            "I see the endpoint is at `/v1/tokens/refresh`. Currently there's no caching - each request hits the token service directly."
        )
        self.add_message(msg3, "assistant")
        await asyncio.sleep(0.1)
        
        # Latest message (most recent, should stay expanded)
        msg4 = (
            "<details>\n<summary>🧠 Click to show / hide internal reasoning</summary>\n\n"
            "Let me structure the recommendation clearly. The solution needs:\n"
            "1. Endpoint that validates and refreshes tokens\n"
            "2. Redis cache layer with 60s TTL\n"
            "3. Fallback logic for upstream failures\n"
            "This is straightforward - we just need to add a caching middleware.\n\n"
            "</details>\n\n"
            "Use `POST /v1/tokens/refresh` with Redis caching:\n\n"
            "**Implementation:**\n\n"
            "- Endpoint validates old token and generates new one with same claims\n"
            "- Cache successful responses in Redis: `token:refresh:{user_id}` with 60s TTL\n"
            "- On upstream 5xx errors: serve cached token if available (≤60s old) and log warning\n"
            "- Return 503 only if both upstream and cache fail"
        )
        self.add_message(msg4, "assistant")
        
        # Enable collapsing after messages are added
        self.add_message("Minimal mode + collapse demo ready. Older messages should be collapsed.", "system")
        self._auto_collapse_assistant = True
        self._collapse_whole_messages = True
        self._collapse_keep = 1
        self._collapse_older_assistant()

    # ------------- Demo actions -------------
    async def action_response_thread_demo_four(self) -> None:
        """Emit 4 separate messages: collapsed Reasoning, collapsed Code/Tool,
        collapsed Notes/Drafts, then a visible Final message.

        Mirrors a response thread with interim steps auto-collapsed and the
        final answer prominent at the end.
        """
        # 0) Steps aggregator (collapsed) – contains all step messages as nested details
        logging.getLogger(__name__).info("[proto] k-demo start (4-message thread)")
        steps = self._load_sample_steps()
        steps_md = self._build_steps_md(steps)
        logging.getLogger(__name__).info("[proto] k-demo built steps: count=%s chars=%s", len(steps), len(steps_md))
        # Extra diagnostic: log first 200 chars to confirm nesting markup
        try:
            logging.getLogger(__name__).debug("[proto] k-demo steps md head=%r", steps_md[:200])
        except Exception:
            pass
        await self.handle_core_event(
            "message",
            {"role": "assistant", "content": steps_md, "category": "DIALOG"},
        )

        # 4) Final (visible)
        final_md = (
            "### Final\n"
            "Use `POST /v1/tokens/refresh`; cache success to Redis (TTL 60s).\n\n"
            "Fallback on upstream failures: serve last-good token ≤60s and log warn.\n"
        )
        logging.getLogger(__name__).debug("[proto] k-demo final length=%s", len(final_md))
        await self.handle_core_event(
            "message",
            {"role": "assistant", "content": final_md, "category": "DIALOG"},
        )

    async def action_response_thread_demo(self) -> None:
        """Show a compact response-thread: Final visible + collapsed Steps/Tools.

        This packs the "Final" and an expandable details section into a single
        message so the inline "Show steps" toggle appears and controls the
        expander. It visually approximates a grouped response without requiring
        engine-level response_id support.
        """
        logging.getLogger(__name__).info("[proto] g-demo start (single message Final+details)")
        content = (
            "### Final\n"
            "Use the Auth service's refresh endpoint and cache misses to Redis.\n\n"
            "- Endpoint: `POST /v1/tokens/refresh`\n"
            "- Fallback: serve last-good token from Redis for ≤60s window\n\n"
            "<details>\n"
            "<summary>Show steps, tools, and drafts</summary>\n\n"
            "<details>\n"
            "<summary>[3] Steps</summary>\n\n"
            "<details>\n"
            "<summary>Parse input</summary>\n\n"
            "Tokenize and normalize user input; extract intent, entities, and constraints.\n\n"
            "</details>\n\n"
            "<details>\n"
            "<summary>Select tools</summary>\n\n"
            "Choose workspace_search for code intel and run execute for quick validation.\n\n"
            "</details>\n\n"
            "<details>\n"
            "<summary>Summarize results</summary>\n\n"
            "Aggregate findings; present concise final guidance.\n\n"
            "</details>\n\n"
            "</details>\n\n"
            "#### Tool: workspace_search (call)\n"
            "```json\n{\n  \"tool\": \"workspace_search\",\n  \"query\": \"auth refresh token\",\n  \"max\": 5\n}\n```\n\n"
            "#### Tool: workspace_search (result preview)\n"
            "```text\n- services/auth/token.py:41 refresh_token()\n- services/auth/client.py:88 refresh()\n- apps/web/routes/auth.py:132 post_refresh()\n...\n```\n\n"
            "#### Draft (hidden by default)\n"
            "> Evaluate pros/cons of optimistic cache; confirm TTL semantics.\n\n"
            "</details>\n"
        )
        logging.getLogger(__name__).debug("[proto] g-demo content chars=%s", len(content))
        try:
            logging.getLogger(__name__).debug("[proto] g-demo md head=%r", content[:200])
        except Exception:
            pass
        await self.handle_core_event(
            "message",
            {"role": "assistant", "content": content, "category": "DIALOG"},
        )

    async def action_response_thread_demo_detailed(self) -> None:
        """Detailed-view variant: first details auto-open to check spacing/contrast."""
        prev_mode = getattr(self, "_view_mode", "compact")
        self._view_mode = "detailed"
        try:
            logging.getLogger(__name__).info("[proto] j-demo start (detailed view variant)")
            steps = self._load_sample_steps()
            steps_md = self._build_steps_md(steps)
            content = (
                "### Final\n"
                "Use the Auth service's refresh endpoint and cache misses to Redis.\n\n"
                "- Endpoint: `POST /v1/tokens/refresh`\n"
                "- Fallback: serve last-good token from Redis for ≤60s window\n\n"
                "<details open>\n"
                "<summary>Show steps, tools, and drafts</summary>\n\n"
                f"{steps_md}"  # Steps block inside this top-level details
                "</details>\n"
            )
            logging.getLogger(__name__).debug("[proto] j-demo steps chars=%s total chars=%s", len(steps_md), len(content))
            try:
                logging.getLogger(__name__).debug("[proto] j-demo md head=%r", content[:200])
            except Exception:
                pass
            await self.handle_core_event(
                "message",
                {"role": "assistant", "content": content, "category": "DIALOG"},
            )
        finally:
            self._view_mode = prev_mode

    # ------------------------
    # Helpers for sample steps
    # ------------------------
    def _load_sample_steps(self) -> list[tuple[str, str]]:
        """Best-effort: pull a few representative steps from recent JSON saves.

        Returns list of (title, body) tuples. Falls back to static samples.
        """
        logger = logging.getLogger(__name__)
        candidates: list[Path] = []
        try:
            home = Path.home()
            conv_home = (home/"penguin_workspace"/"conversations")
            candidates.extend(sorted(conv_home.glob("session_*.json"), key=lambda p: p.stat().st_mtime, reverse=True))
        except Exception:
            pass
        try:
            cwd = Path.cwd()
            conv_cwd = (cwd/"penguin_workspace"/"conversations")
            candidates.extend(sorted(conv_cwd.glob("session_*.json"), key=lambda p: p.stat().st_mtime, reverse=True))
        except Exception:
            pass
        try:
            logger.info("[proto] step-loader candidates=%s (home=%s, cwd=%s)", len(candidates), str(conv_home) if 'conv_home' in locals() else None, str(conv_cwd) if 'conv_cwd' in locals() else None)
        except Exception:
            pass
        for fp in candidates[:3]:
            try:
                data = json.loads(fp.read_text(encoding="utf-8"))
                msgs = data.get("messages") or []
                # Heuristic: grab first assistant message with a bullet list or heading
                for m in msgs:
                    if (m.get("role") == "assistant") and isinstance(m.get("content"), str):
                        txt = m["content"]
                        # Very light parsing to extract 3-4 step-like lines
                        lines = [ln.strip("- • \t ") for ln in txt.splitlines() if ln.strip().startswith(("- ", "• ", "1.", "2.", "3.", "4."))]
                        if len(lines) >= 3:
                            titles = [
                                (lines[0] or "Step 1", ""),
                                (lines[1] or "Step 2", ""),
                                (lines[2] or "Step 3", ""),
                            ]
                            if len(lines) > 3:
                                titles.append((lines[3] or "Step 4", ""))
                            logger.info("[proto] step-loader selected file=%s extracted_steps=%s", str(fp), len(titles))
                            return titles
            except Exception:
                continue
        # Fallback sample set
        fallback = [
            ("Planning a search strategy", "I'm going to scan the repo for existing planning logic and related prompts to ground recommendations. Then I'll propose targeted improvements and, if appropriate, lightweight patches to prompts/docs."),
            ("Investigating planning references", "I'm thinking about how Engine.run_task uses a completion phase to stop, which seems pretty basic as a planner. Meanwhile, I notice there's mention of multi-agent roles like 'planner', 'implementer', and 'QA'. I might need to search for AgentPersonaConfig."),
            ("Structuring Final Response", "- Add a first-class Plan model with steps, owners, status, dependencies, risks, and verification hooks.\n- Persist plan alongside the session and agent in conversation metadata."),
            ("Drafting a plan", "```python\nclass PlanningPlugin(BasePlugin):\n    def on_task_start(self, task: str) -> Plan:\n        pass\n    def on_step_complete(self, step: PlanStep, result: Any):\n        pass\n```"),
        ]
        try:
            logger.info("[proto] step-loader using fallback steps: count=%s", len(fallback))
        except Exception:
            pass
        return fallback

    def _build_steps_md(self, steps: list[tuple[str, str]]) -> str:
        count = len(steps)
        parts = ["<details>\n", f"<summary>[{count}] Steps</summary>\n\n"]
        for title, body in steps:
            parts.append("<details>\n")
            parts.append(f"<summary>{title}</summary>\n\n")
            parts.append(body if body.endswith("\n") else body + "\n")
            parts.append("</details>\n\n")
        parts.append("</details>\n")
        md = "".join(parts)
        try:
            logging.getLogger(__name__).debug("[proto] built steps md length=%s", len(md))
        except Exception:
            pass
        return md

    async def action_demo_message(self) -> None:
        # Demo message with inline ActionTag, then emit a separate tool call/result
        # to mirror the typical duplication sequence seen in real runs.
        content = (
            # Steps + Final demo (matches prompt clause)
            "<details>\n<summary>Plan / Steps</summary>\n\n"
            "1) Parse input\n\n"
            "2) Select tool(s)\n\n"
            "3) Summarize results\n\n"
            "</details>\n\n"
            "### Final\nUse endpoint X with key Y; fallback to cache on 404.\n\n"
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

    async def action_demo_threaded_group(self) -> None:
        """Show a Final message with an expandable group of sub-messages beneath it.

        Mimics Codex/Claude Code: prominent Final answer, with optional steps/drafts/tools
        revealed via a single expander containing multiple sub-blocks.
        """
        # Final first (prominent)
        final_md = (
            "### Final\n"
            "We will use the Auth service's `/v1/tokens/refresh` endpoint and cache misses to Redis.\n\n"
            "- Endpoint: `POST /v1/tokens/refresh`\n"
            "- Fallback: serve last-good token from Redis for ≤60s window\n"
        )
        await self.handle_core_event(
            "message",
            {"role": "assistant", "content": final_md, "category": "DIALOG"},
        )

        # Collapsed steps beneath final — multiple sub-messages rendered inside one details block
        sub_msgs = (
            "<details>\n<summary>Show steps (3)</summary>\n\n"
            "#### Draft 1\n"
            "> Explore token refresh flows; consider optimistic cache.\n\n"
            "#### Tool: workspace_search\n"
            "```json\n{\n  \"tool\": \"workspace_search\",\n  \"query\": \"auth refresh token\"\n}\n```\n\n"
            "#### Notes\n"
            "- Cache tokens in Redis with 60s TTL.\n"
            "- On 5xx from Auth, serve cache and log warn.\n\n"
            "#### Draft 2\n"
            "> Confirm endpoint semantics; finalize fallback policy.\n\n"
            "</details>\n"
        )
        await self.handle_core_event(
            "message",
            {"role": "assistant", "content": sub_msgs, "category": "DIALOG"},
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

    async def action_sample_random_exec(self) -> None:
        """Replay a compact random-number flow using the strict formatting contract."""
        # 1) Assistant message: Steps (collapsed) + clean python execute (markers on own lines)
        content1 = (
            "<details>\n<summary>Plan / Steps</summary>\n\n"
            "1) Define a random number generator.\n"
            "2) Execute and print only the number.\n\n"
            "</details>\n\n"
            "```python\n"
            "# <execute>\n"
            "import random\n\n"
            "def generate_random_number(low=1, high=1_000_000):\n"
            "    return random.randint(low, high)\n\n"
            "n = generate_random_number()\n"
            "print(n)\n"
            "# </execute>\n"
            "```\n"
        )
        await self.handle_core_event(
            "message",
            {"role": "assistant", "content": content1, "category": "DIALOG"},
        )
        await self.handle_core_event(
            "action",
            {"type": "execute", "params": "import random; print(41800)", "id": "call_bf6386fc"},
        )
        await self.handle_core_event(
            "action_result",
            {"result": "41800", "status": "completed", "id": "call_bf6386fc"},
        )
        # 2) Final message acknowledging the result
        final_md = "### Final\nRandom number: 41800"
        await self.handle_core_event(
            "message",
            {"role": "assistant", "content": final_md, "category": "DIALOG"},
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

    # Configure logging to the same penguin/cli/tui_debug.log file used by the main TUI
    try:
        root = logging.getLogger()
        for h in list(root.handlers):
            root.removeHandler(h)
        root.setLevel(logging.INFO)
        log_path = Path(__file__).resolve().with_name("tui_debug.log")
        fh = logging.FileHandler(str(log_path), mode="a", encoding="utf-8")
        fh.setLevel(logging.DEBUG)
        fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
        root.addHandler(fh)
        ch = logging.StreamHandler()
        ch.setLevel(logging.ERROR)
        ch.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
        root.addHandler(ch)
        logging.getLogger(__name__).info("[proto] logging configured path=%s", str(log_path))
    except Exception:
        pass

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
            logging.getLogger(__name__).info("[proto] launching PrototypePenguinApp (no profiler)")
            app = PrototypePenguinApp()
            app.run()
            return
        profiler = Profiler()
        profiler.start()
        try:
            logging.getLogger(__name__).info("[proto] launching PrototypePenguinApp (profile mode)")
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
        logging.getLogger(__name__).info("[proto] launching PrototypePenguinApp")
        app = PrototypePenguinApp()
        app.run()


if __name__ == "__main__":
    main()


