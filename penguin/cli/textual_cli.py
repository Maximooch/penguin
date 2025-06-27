from __future__ import annotations

"""textual_cli.py
A Textual (https://textual.textualize.io/) based terminal user-interface for the
Penguin AI assistant.

The implementation purposefully keeps the UI minimal for now – a scrollable chat
log, a single-line input field, and a status bar which we reuse for token usage
and progress messages.  All business logic (model calls, streaming, project /
task commands, …) is delegated to :class:`penguin.cli.interface.PenguinInterface`.

This file is *not* wired into the default ``penguin`` console entry-point yet;
classic ``cli.py`` keeps functioning.  Once the Textual interface has matured
we can switch the main entry-point to this module.
"""

from typing import Any, Dict, Optional, Callable
import asyncio

from textual.app import App, ComposeResult
from textual.containers import Vertical
from textual.widgets import Header, Footer, Input, Static

# Chat log widget fallback resolution ------------------------------------

try:
    from textual.widgets import RichLog as ChatLogWidget  # type: ignore
except ImportError:
    try:
        from textual.widgets import Log as ChatLogWidget  # type: ignore
    except ImportError:  # pragma: no cover – extremely old Textual
        # Final fallback: use a simple Static widget (read-only) so the app at
        # least runs, albeit without scrolling.
        from textual.widgets import Static as ChatLogWidget  # type: ignore

        class _SimpleStaticLog(ChatLogWidget):  # type: ignore
            """Very naive fallback when no Log widget exists."""

            def write(self, text: str) -> None:  # pylint: disable=unused-argument
                # Append text with a newline to the static content.
                current = self.renderable or ""
                self.update(f"{current}\n{text}")

        ChatLogWidget = _SimpleStaticLog  # type: ignore  # noqa: E305,E501

# -----------------------------------------------------------------------

from textual.reactive import reactive
from textual.message import Message


# Re-use the existing global initialisation helpers to avoid duplication.
from penguin.cli.cli import _initialize_core_components_globally, _interface  # pylint: disable=protected-access
from penguin.cli.interface import PenguinInterface

__all__ = ["PenguinTextualApp", "run"]


class PenguinTextualApp(App[None]):
    """A minimal Textual based chat interface for Penguin."""

    def __init__(self, interface: PenguinInterface, **kwargs):
        super().__init__(**kwargs)
        self.interface = interface

    CSS = """
    Screen {
        layout: vertical;
    }

    #chat_log {
        height: 1fr;
        overflow-y: auto;
        background: $panel;
    }

    #status_bar {
        height: 1;
        background: $surface;
        color: $text;
    }

    #input_field {
        height: 3;
    }
    """

    BINDINGS = [
        ("q", "quit", "Quit"),
    ]

    # --- Reactive state ---------------------------------------------------
    interface: reactive[PenguinInterface | None] = reactive(None)

    # ---------------------------------------------------------------------
    # Life-cycle hooks
    # ---------------------------------------------------------------------

    async def on_mount(self) -> None:  # noqa: D401
        """Initialise Penguin core components once the UI is ready."""
        from traceback import format_exc  # Local import to avoid top-level cost

        # We *must* call the global initialiser before using the interface.
        try:
            await _initialize_core_components_globally()
        except Exception as exc:  # pragma: no cover – we want *all* info
            # Any exception here would normally terminate the Textual app with
            # very little feedback.  We surface it explicitly so that users see
            # the root cause on stdout / stderr.
            self.console.print("[red bold]Fatal initialisation error:[/red bold]", str(exc))
            self.console.print(format_exc())
            # Exit the application so that the underlying exception is not
            # swallowed silently.
            self.exit(str(exc))

        # After the call the global _interface variable is populated; keep a
        # reference locally for convenience.
        self.interface = _interface  # type: ignore[assignment]

        if self.interface is None:
            # Fatal – something went wrong during initialisation.
            self.exit("Failed to initialise Penguin core components.")
            return

        # Register callbacks for progress and token usage so we can update the
        # status bar in real-time.
        self.interface.register_progress_callback(self._on_progress_update)
        self.interface.register_token_callback(self._on_token_update)
        self.input_field.focus()

    # ------------------------------------------------------------------ UI

    def compose(self) -> ComposeResult:  # noqa: D401
        """Create child widgets."""
        yield Header(show_clock=True)
        # Chat log widget (RichLog / Log / fallback Static).  Different Textual
        # versions expose different constructor keywords, so we build kwargs
        # dynamically to avoid runtime *TypeError*.
        from inspect import signature  # Local import to keep top tidy

        kw: dict[str, object] = {"id": "chat_log"}

        try:
            params = signature(ChatLogWidget.__init__).parameters
            if "markup" in params:
                kw["markup"] = True
            if "highlight" in params:
                kw["highlight"] = True
            if "wrap" in params:
                kw["wrap"] = True
        except (TypeError, ValueError):
            # Could not introspect; fall back to a minimal set.
            pass

        try:
            yield ChatLogWidget(**kw)  # type: ignore[arg-type]
        except TypeError:
            # Some very old versions may still object; strip extras.
            yield ChatLogWidget(id="chat_log")
        yield Static("", id="status_bar")
        yield Input(placeholder="Type a message and press ⏎", id="input_field")
        yield Footer()

    # ---------------------------------------------------------------------
    # Helper properties
    # ---------------------------------------------------------------------

    def chat_log(self):  # -> ChatLogWidget once Textual types catch-up
        return self.query_one("#chat_log")

    @property
    def status_bar(self) -> Static:
        return self.query_one("#status_bar", Static)

    @property
    def input_field(self) -> Input:
        return self.query_one("#input_field", Input)

    # ---------------------------------------------------------------------
    # Event handlers & callbacks
    # ---------------------------------------------------------------------

    async def on_input_submitted(self, event: Input.Submitted) -> None:  # noqa: D401
        """Handle *Enter* pressed in the input field."""
        text = event.value.strip()
        # Clear the input *immediately* for snappy UX.
        self.input_field.value = ""

        if not text:
            return  # Ignore empty submissions

        # Echo the user message into the chat log.
        self.chat_log.write(f"[bold cyan]You:[/bold cyan] {text}")

        # Define a streaming callback that appends chunks as they arrive.
        async def _stream_cb(chunk: str) -> None:  # noqa: D401
            if chunk:
                # We write without a newline to simulate a streaming effect.
                # TextLog has *no* incremental update method so we rebuild the
                # last line each time.
                self._ensure_last_stream_line()
                self.chat_log.pop()  # Remove last line
                self.chat_log.write(f"[bold blue]Penguin (streaming):[/bold blue] {chunk}")

        # Run the LLM call in the background – negotiating with the Textual
        # message pump.
        asyncio.create_task(self._process_message(text, _stream_cb))

    async def _process_message(self, text: str, stream_cb: Callable[[str], Any]) -> None:  # noqa: D401
        """Call the backend and print the assistant response once ready."""
        if self.interface is None:
            self.chat_log.write("[red]Error: Backend not ready.[/red]")
            return

        response: Dict[str, Any] | str = await self.interface.process_input(
            {"text": text}, stream_callback=stream_cb
        )

        # Remove the temporary streaming line, if any.
        self._wipe_stream_placeholder()

        if isinstance(response, dict):
            assistant_msg = response.get("assistant_response", "")
            if assistant_msg:
                self.chat_log.write(f"[bold blue]Penguin:[/bold blue] {assistant_msg}")

            # Display action results, if present.
            for result in response.get("action_results", []):
                action = result.get("action", "unknown")
                status = result.get("status", "completed")
                output = result.get("result", result.get("output", ""))
                self.chat_log.write(
                    f"[yellow]Action {action} ({status}):[/yellow] {output}"
                )
        else:
            # Fallback – unexpected response type.
            self.chat_log.write(str(response))

    # ------------------------------------------------------------------
    # Backend -> UI callbacks
    # ------------------------------------------------------------------

    def _on_token_update(self, usage: Dict[str, Any]) -> None:  # noqa: D401
        current = usage.get("current_total_tokens", 0)
        max_tokens = usage.get("max_tokens", 0)
        percentage = usage.get("percentage", 0)
        self.status_bar.update(
            f"Tokens: {current}/{max_tokens} ({percentage:.1f}%)"
        )

    def _on_progress_update(self, iteration: int, max_iter: int, message: Optional[str] | None) -> None:  # noqa: D401,E501
        self.status_bar.update(
            f"Progress: {iteration}/{max_iter} {message or ''}"
        )

    # ------------------------------------------------------------------
    # Utility helpers
    # ------------------------------------------------------------------

    def _ensure_last_stream_line(self) -> None:
        """Ensure there is at least one line to update during streaming."""
        if not self.chat_log.lines or self.chat_log.lines[-1] == "":
            # Insert an empty placeholder if nothing exists yet.
            self.chat_log.write("")

    def _wipe_stream_placeholder(self) -> None:
        """Remove the temporary streaming line (if present)."""
        if self.chat_log.lines and "(streaming):" in self.chat_log.lines[-1]:
            self.chat_log.pop()


# -------------------------------------------------------------------------
# Top-level helpers
# -------------------------------------------------------------------------

def run(interface: PenguinInterface) -> None:  # noqa: D401
    """Run the Textual application with a pre-initialized interface."""
    app = PenguinTextualApp(interface=interface)
    app.run()
