"""Tests for core system diagnostics runtime helpers."""

from __future__ import annotations

import asyncio
import logging
from types import SimpleNamespace
from typing import Any

from penguin.core_runtime import system_diagnostics


class _MemoryProvider:
    pass


class _DoneTask:
    def done(self) -> bool:
        return True

    def cancelled(self) -> bool:
        return False

    def exception(self) -> Exception:
        return RuntimeError("index failed")


class _Profiler:
    def get_summary(self) -> dict[str, Any]:
        return {"total_time": 1.25}

    def get_startup_report(self) -> str:
        return "startup report"


def test_get_system_info_reports_components_without_session_failure() -> None:
    conversation_manager = SimpleNamespace(
        get_current_session=lambda: SimpleNamespace(
            id="session_1",
            messages=["a", "b"],
        )
    )
    owner = SimpleNamespace(
        engine=object(),
        model_config=SimpleNamespace(
            model="gpt-5",
            provider="openai",
            streaming_enabled=True,
            vision_enabled=True,
        ),
        conversation_manager=conversation_manager,
        tool_manager=SimpleNamespace(
            tools={"read": object(), "write": object()},
            _memory_provider=_MemoryProvider(),
        ),
        get_checkpoint_stats=lambda: {"enabled": True},
    )

    info = system_diagnostics.get_system_info(
        owner,
        version="test-version",
        logger=logging.getLogger(__name__),
    )

    assert info["penguin_version"] == "test-version"
    assert info["engine_available"] is True
    assert info["checkpoints_enabled"] is True
    assert info["current_model"]["model"] == "gpt-5"
    assert info["conversation_manager"]["current_session_id"] == "session_1"
    assert info["conversation_manager"]["total_messages"] == 2
    assert info["tool_manager"]["total_tools"] == 2
    assert info["memory_provider"] == {
        "initialized": True,
        "provider_type": "_MemoryProvider",
    }


def test_get_system_status_reports_runtime_state_and_memory_provider() -> None:
    owner = SimpleNamespace(
        current_runmode_status_summary="Running",
        _continuous_mode=True,
        streaming_active=True,
        initialized=True,
        tool_manager=SimpleNamespace(fast_startup=True, _memory_provider=None),
        get_token_usage=lambda: {"total": {"input": 1, "output": 2}},
    )
    owner.get_memory_provider_status = lambda: {"status": "disabled", "provider": None}

    status = system_diagnostics.get_system_status(
        owner,
        logger=logging.getLogger(__name__),
    )

    assert status["status"] == "active"
    assert status["runmode_status"] == "Running"
    assert status["continuous_mode"] is True
    assert status["streaming_active"] is True
    assert status["token_usage"]["total"]["input"] == 1
    assert status["initialization"] == {
        "core_initialized": True,
        "fast_startup_enabled": True,
    }
    assert status["memory_provider"]["status"] == "disabled"
    assert "timestamp" in status


def test_get_startup_stats_uses_profiler_and_tool_manager_stats() -> None:
    owner = SimpleNamespace(
        initialized=True,
        tool_manager=SimpleNamespace(
            _memory_provider=_MemoryProvider(),
            get_startup_stats=lambda: {"fast_startup": True},
        ),
    )

    stats = system_diagnostics.get_startup_stats(owner, profiler=_Profiler())

    assert stats == {
        "profiling_summary": {"total_time": 1.25},
        "tool_manager_stats": {"fast_startup": True},
        "memory_provider_initialized": True,
        "core_initialized": True,
    }


def test_print_startup_report_accepts_output_injection() -> None:
    lines: list[str] = []
    owner = SimpleNamespace(
        tool_manager=SimpleNamespace(
            get_startup_stats=lambda: {
                "fast_startup": True,
                "memory_provider_exists": True,
                "indexing_completed": False,
                "lazy_initialized": {"memory": True, "search": False},
            }
        )
    )

    system_diagnostics.print_startup_report(
        owner,
        profiler=_Profiler(),
        output=lines.append,
    )

    assert "PENGUIN STARTUP PERFORMANCE REPORT" in lines
    assert "startup report" in lines
    assert any("memory: ✓ Loaded" in line for line in lines)
    assert any("search: ○ Deferred" in line for line in lines)


def test_enable_fast_startup_globally_sets_existing_flag() -> None:
    owner = SimpleNamespace(tool_manager=SimpleNamespace(fast_startup=False))

    system_diagnostics.enable_fast_startup_globally(
        owner,
        logger=logging.getLogger(__name__),
    )

    assert owner.tool_manager.fast_startup is True


def test_get_memory_provider_status_reports_done_indexing_task_exception() -> None:
    owner = SimpleNamespace(
        tool_manager=SimpleNamespace(
            _memory_provider=_MemoryProvider(),
            _indexing_completed=False,
            _indexing_task=_DoneTask(),
        )
    )

    status = system_diagnostics.get_memory_provider_status(owner)

    assert status == {
        "status": "initialized",
        "provider": "_MemoryProvider",
        "indexing_completed": False,
        "indexing_task_running": False,
        "indexing_task_status": {
            "done": True,
            "cancelled": False,
            "exception": "index failed",
        },
    }


def test_get_telemetry_summary_returns_empty_without_telemetry() -> None:
    summary = asyncio.run(system_diagnostics.get_telemetry_summary(SimpleNamespace()))

    assert summary == {}


def test_get_telemetry_summary_returns_snapshot_payload() -> None:
    class _Telemetry:
        async def snapshot(self) -> dict[str, Any]:
            return {"events": 3, "errors": 0}

    summary = asyncio.run(
        system_diagnostics.get_telemetry_summary(
            SimpleNamespace(telemetry=_Telemetry())
        )
    )

    assert summary == {"events": 3, "errors": 0}
