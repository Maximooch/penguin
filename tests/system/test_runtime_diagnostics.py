"""Request-scoped runtime timing and liveness diagnostics tests."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from penguin.llm.runtime import execute_pending_tool_calls
from penguin.system.runtime_diagnostics import (
    ConnectionHistory,
    RuntimeDiagnosticsRecorder,
    current_runtime_diagnostics,
    record_runtime_duration,
    runtime_diagnostics_scope,
)


@pytest.mark.asyncio
async def test_real_tool_batch_attributes_execution_and_orchestration() -> None:
    """The production tool loop records execution separately from batch overhead."""

    class _Handler:
        def get_and_clear_pending_tool_calls(self) -> list[dict[str, str]]:
            return [
                {
                    "call_id": "call-diagnostics",
                    "name": "read_file",
                    "arguments": '{"path":"README.md"}',
                }
            ]

    class _ToolManager:
        def execute_tool(self, name: str, arguments: object) -> dict[str, str]:
            assert name == "read_file"
            assert arguments == {"path": "README.md"}
            return {"action": name, "status": "completed", "result": "bounded"}

    api_client = SimpleNamespace(
        client_handler=_Handler(),
        model_config=SimpleNamespace(provider="fake", model="deterministic"),
    )
    recorder = RuntimeDiagnosticsRecorder(
        request_id="tool-diagnostics",
        session_id="tool-session",
    )
    persisted: list[dict[str, object]] = []

    with runtime_diagnostics_scope(recorder):
        results = await execute_pending_tool_calls(
            api_client=api_client,
            tool_manager=_ToolManager(),
            persist_action_result=lambda result, metadata: persisted.append(
                {"result": result, "metadata": metadata}
            ),
        )

    snapshot = recorder.snapshot()
    assert len(results) == 1
    assert len(persisted) == 1
    assert snapshot["stages"]["tool.execution"]["count"] == 1
    assert snapshot["stages"]["tool.batch"]["count"] == 1
    assert snapshot["derived"]["tool_batch_ms"] >= snapshot["derived"][
        "tool_execution_ms"
    ]
    assert snapshot["progress_age_ms"]["tool"] is not None


class _Clock:
    """Manually advanced monotonic clock."""

    def __init__(self) -> None:
        self.value = 100.0

    def __call__(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        """Advance the deterministic clock."""

        self.value += seconds


def test_recorder_separates_stages_and_progress_ages() -> None:
    """Provider, tool, UI, and request ages remain independent evidence."""

    clock = _Clock()
    recorder = RuntimeDiagnosticsRecorder(
        request_id="request-1",
        session_id="session-1",
        monotonic=clock,
    )

    with recorder.measure("provider.wait"):
        clock.advance(0.020)
    recorder.mark_progress("provider")
    clock.advance(0.010)
    with recorder.measure("tool.execution"):
        clock.advance(0.005)
    recorder.mark_progress("tool")
    clock.advance(0.015)
    recorder.mark_progress("ui")
    clock.advance(0.050)

    snapshot = recorder.snapshot()

    assert snapshot["request_age_ms"] == 100.0
    assert snapshot["progress_age_ms"] == {
        "provider": 80.0,
        "tool": 65.0,
        "ui": 50.0,
        "runtime": None,
    }
    assert snapshot["stages"]["provider.wait"] == {
        "count": 1,
        "total_ms": 20.0,
        "max_ms": 20.0,
        "last_ms": 20.0,
    }
    assert snapshot["stages"]["tool.execution"]["total_ms"] == 5.0


def test_scope_records_low_level_duration_without_content() -> None:
    """Low-level helpers can attribute time without accepting payload text."""

    clock = _Clock()
    recorder = RuntimeDiagnosticsRecorder(
        request_id="request-2",
        session_id=None,
        monotonic=clock,
    )

    assert current_runtime_diagnostics() is None
    with runtime_diagnostics_scope(recorder):
        assert current_runtime_diagnostics() is recorder
        record_runtime_duration("ledger.commit", 12.5)
    assert current_runtime_diagnostics() is None

    snapshot_text = str(recorder.snapshot())
    assert "ledger.commit" in snapshot_text
    assert "prompt" not in snapshot_text
    assert "tool_payload" not in snapshot_text


def test_event_history_is_bounded_and_names_are_normalized() -> None:
    """Diagnostics history cannot grow forever or absorb arbitrary payloads."""

    clock = _Clock()
    recorder = RuntimeDiagnosticsRecorder(
        request_id="request-3",
        session_id="session-3",
        monotonic=clock,
        max_events=3,
    )
    for index in range(5):
        recorder.record_duration(f"stage {index}", float(index))

    snapshot = recorder.snapshot()

    assert len(snapshot["events"]) == 3
    assert [event["name"] for event in snapshot["events"]] == [
        "stage_2",
        "stage_3",
        "stage_4",
    ]


def test_tool_orchestration_is_distinct_from_actual_execution() -> None:
    """Batch wall time minus execution is reported as local orchestration."""

    recorder = RuntimeDiagnosticsRecorder(
        request_id="request-4",
        session_id="session-4",
    )
    recorder.record_duration("tool.batch", 60.0)
    recorder.record_duration("tool.execution", 10.0)

    snapshot = recorder.snapshot()

    assert snapshot["derived"]["tool_execution_ms"] == 10.0
    assert snapshot["derived"]["tool_batch_ms"] == 60.0
    assert snapshot["derived"]["tool_orchestration_ms"] == 50.0


def test_connection_history_is_bounded_and_content_free() -> None:
    """Connection diagnostics retain lifecycle codes, not exception payloads."""

    clock = _Clock()
    history = ConnectionHistory(max_entries=2, monotonic=clock)
    history.record("attempt", transport="sse")
    clock.advance(1.0)
    history.record("connected", transport="sse")
    clock.advance(1.0)
    history.record("disconnected", transport="sse", reason_code="stream_closed")

    assert history.snapshot() == [
        {
            "state": "connected",
            "transport": "sse",
            "reason_code": None,
            "monotonic_ms": 101000.0,
        },
        {
            "state": "disconnected",
            "transport": "sse",
            "reason_code": "stream_closed",
            "monotonic_ms": 102000.0,
        },
    ]
