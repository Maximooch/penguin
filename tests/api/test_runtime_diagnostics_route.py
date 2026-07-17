"""Runtime diagnostics debug export contract tests."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from penguin.system.runtime_diagnostics import (
    RuntimeDiagnosticsRecorder,
    store_runtime_diagnostics,
)
from penguin.web import routes


def test_verbose_chat_trace_does_not_enter_info_telemetry(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Potentially sensitive debug arguments are absent from ordinary INFO logs."""

    sentinel = "ROUTE-PRIVATE-PROMPT-NEVER-LOG"
    with caplog.at_level("INFO"):
        routes._request_log_debug("chat.trace.private value=%s", sentinel)

    assert sentinel not in "\n".join(record.getMessage() for record in caplog.records)


@pytest.mark.asyncio
async def test_runtime_diagnostics_export_is_bounded_and_content_free() -> None:
    """The debug export exposes correlated timings without conversation content."""

    core = SimpleNamespace()
    recorder = RuntimeDiagnosticsRecorder(
        request_id="request-1",
        session_id="session-1",
    )
    recorder.record_duration("provider.stream", 12.5)
    recorder.mark_progress("provider")
    recorder.finish("completed")
    store_runtime_diagnostics(core, recorder)

    payload = await routes.get_runtime_diagnostics(core=core)

    assert len(payload["requests"]) == 1
    request = payload["requests"][0]
    assert request["request_id"] == "request-1"
    assert request["terminal_status"] == "completed"
    assert request["stages"]["provider.stream"]["last_ms"] == 12.5
    assert payload["sse_connections"] == []
