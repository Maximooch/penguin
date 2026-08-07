"""Lifecycle contracts for the extracted interactive CLI application."""

from types import SimpleNamespace
from unittest.mock import Mock, patch

from penguin.cli.interactive import PenguinCLI


def _core() -> SimpleNamespace:
    return SimpleNamespace(
        show_tool_results=True,
        register_progress_callback=Mock(),
        conversation_manager=SimpleNamespace(save=Mock()),
    )


def test_cli_facade_exports_extracted_interactive_application() -> None:
    from penguin.cli.cli import PenguinCLI as FacadePenguinCLI

    assert FacadePenguinCLI is PenguinCLI


def test_cancel_streaming_restores_manager_state() -> None:
    event_bus = SimpleNamespace(subscribe=Mock())
    with patch("penguin.cli.interactive.EventBus.get_sync", return_value=event_bus):
        application = PenguinCLI(_core())
    application.console = Mock()
    application.streaming_manager = SimpleNamespace(
        safely_stop_progress=Mock(), finalize_streaming=Mock()
    )
    application._streaming_started = True

    application._cancel_streaming()

    application.streaming_manager.safely_stop_progress.assert_called_once_with()
    application.streaming_manager.finalize_streaming.assert_called_once_with()


def test_finalize_streaming_clears_all_stream_identifiers() -> None:
    event_bus = SimpleNamespace(subscribe=Mock())
    with patch("penguin.cli.interactive.EventBus.get_sync", return_value=event_bus):
        application = PenguinCLI(_core())
    application.streaming_manager = SimpleNamespace(finalize_streaming=Mock())
    application._streaming_started = True
    application._streaming_session_id = "legacy"
    application._active_stream_id = "active"

    application._finalize_streaming()

    assert application._streaming_started is False
    assert application._streaming_session_id is None
    assert application._active_stream_id is None
