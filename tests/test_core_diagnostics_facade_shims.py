"""Tests for PenguinCore diagnostics facade compatibility methods."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

from penguin.core import PenguinCore


def test_core_diagnostics_facade_shims_delegate_to_runtime(monkeypatch) -> None:
    owner = SimpleNamespace()
    calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []

    facade_globals = PenguinCore.get_system_info.__globals__
    diagnostics = facade_globals["core_system_diagnostics"]
    agent_lifecycle = facade_globals["core_agent_lifecycle"]
    expected_logger = facade_globals["logger"]
    expected_profiler = facade_globals["profiler"]
    expected_version = facade_globals["PENGUIN_VERSION"]

    async def fake_get_telemetry_summary(core: Any) -> dict[str, Any]:
        calls.append(("get_telemetry_summary", (core,), {}))
        return {"events": 2}

    def fake_smoke_check_agents(core: Any) -> dict[str, Any]:
        calls.append(("smoke_check_agents", (core,), {}))
        return {"agents": "ok"}

    def fake_get_system_info(
        core: Any,
        *,
        version: str,
        logger: Any,
    ) -> dict[str, Any]:
        calls.append(
            (
                "get_system_info",
                (core,),
                {"version": version, "logger": logger},
            )
        )
        return {"penguin_version": version}

    def fake_get_system_status(core: Any, *, logger: Any) -> dict[str, Any]:
        calls.append(("get_system_status", (core,), {"logger": logger}))
        return {"status": "active"}

    def fake_get_startup_stats(core: Any, *, profiler: Any) -> dict[str, Any]:
        calls.append(("get_startup_stats", (core,), {"profiler": profiler}))
        return {"core_initialized": True}

    def fake_print_startup_report(core: Any, *, profiler: Any) -> None:
        calls.append(("print_startup_report", (core,), {"profiler": profiler}))

    def fake_enable_fast_startup_globally(core: Any, *, logger: Any) -> None:
        calls.append(("enable_fast_startup_globally", (core,), {"logger": logger}))

    def fake_get_memory_provider_status(core: Any) -> dict[str, Any]:
        calls.append(("get_memory_provider_status", (core,), {}))
        return {"status": "initialized"}

    monkeypatch.setattr(
        diagnostics,
        "get_telemetry_summary",
        fake_get_telemetry_summary,
    )
    monkeypatch.setattr(agent_lifecycle, "smoke_check_agents", fake_smoke_check_agents)
    monkeypatch.setattr(diagnostics, "get_system_info", fake_get_system_info)
    monkeypatch.setattr(diagnostics, "get_system_status", fake_get_system_status)
    monkeypatch.setattr(diagnostics, "get_startup_stats", fake_get_startup_stats)
    monkeypatch.setattr(
        diagnostics,
        "print_startup_report",
        fake_print_startup_report,
    )
    monkeypatch.setattr(
        diagnostics,
        "enable_fast_startup_globally",
        fake_enable_fast_startup_globally,
    )
    monkeypatch.setattr(
        diagnostics,
        "get_memory_provider_status",
        fake_get_memory_provider_status,
    )

    assert asyncio.run(PenguinCore.get_telemetry_summary(owner)) == {"events": 2}
    assert PenguinCore.smoke_check_agents(owner) == {"agents": "ok"}
    assert PenguinCore.get_system_info(owner) == {"penguin_version": expected_version}
    assert PenguinCore.get_system_status(owner) == {"status": "active"}
    assert PenguinCore.get_startup_stats(owner) == {"core_initialized": True}
    assert PenguinCore.get_memory_provider_status(owner) == {"status": "initialized"}
    assert PenguinCore.print_startup_report(owner) is None
    assert PenguinCore.enable_fast_startup_globally(owner) is None

    assert calls == [
        ("get_telemetry_summary", (owner,), {}),
        ("smoke_check_agents", (owner,), {}),
        (
            "get_system_info",
            (owner,),
            {"version": expected_version, "logger": expected_logger},
        ),
        ("get_system_status", (owner,), {"logger": expected_logger}),
        ("get_startup_stats", (owner,), {"profiler": expected_profiler}),
        ("get_memory_provider_status", (owner,), {}),
        ("print_startup_report", (owner,), {"profiler": expected_profiler}),
        ("enable_fast_startup_globally", (owner,), {"logger": expected_logger}),
    ]
