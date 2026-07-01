"""System diagnostics helpers for :mod:`penguin.core`."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Callable

__all__ = [
    "enable_fast_startup_globally",
    "get_memory_provider_status",
    "get_startup_stats",
    "get_system_info",
    "get_system_status",
    "get_telemetry_summary",
    "print_startup_report",
]


def get_system_info(
    owner: Any,
    *,
    version: str,
    logger: Any,
) -> dict[str, Any]:
    """Return component and capability information for a core-like owner."""
    try:
        info = {
            "penguin_version": version,
            "engine_available": hasattr(owner, "engine") and owner.engine is not None,
            "checkpoints_enabled": owner.get_checkpoint_stats().get("enabled", False),
            "current_model": None,
            "conversation_manager": {
                "active": hasattr(owner, "conversation_manager")
                and owner.conversation_manager is not None,
                "current_session_id": None,
                "total_messages": 0,
            },
            "tool_manager": {
                "active": hasattr(owner, "tool_manager")
                and owner.tool_manager is not None,
                "total_tools": 0,
            },
            "memory_provider": {"initialized": False, "provider_type": None},
        }

        if hasattr(owner, "model_config") and owner.model_config:
            info["current_model"] = {
                "model": owner.model_config.model,
                "provider": owner.model_config.provider,
                "streaming_enabled": owner.model_config.streaming_enabled,
                "vision_enabled": bool(
                    getattr(owner.model_config, "vision_enabled", False)
                ),
            }

        if hasattr(owner, "conversation_manager") and owner.conversation_manager:
            try:
                current_session = owner.conversation_manager.get_current_session()
                if current_session:
                    info["conversation_manager"]["current_session_id"] = (
                        current_session.id
                    )
                    info["conversation_manager"]["total_messages"] = len(
                        current_session.messages
                    )
            except Exception:
                pass

        if hasattr(owner, "tool_manager") and owner.tool_manager:
            info["tool_manager"]["total_tools"] = len(
                getattr(owner.tool_manager, "tools", {})
            )

            if (
                hasattr(owner.tool_manager, "_memory_provider")
                and owner.tool_manager._memory_provider
            ):
                info["memory_provider"]["initialized"] = True
                info["memory_provider"]["provider_type"] = type(
                    owner.tool_manager._memory_provider
                ).__name__

        return info

    except Exception as exc:
        logger.error("Error getting system info: %s", exc)
        return {"error": f"Failed to get system info: {exc!s}"}


def get_system_status(owner: Any, *, logger: Any) -> dict[str, Any]:
    """Return current runtime status for a core-like owner."""
    try:
        status = {
            "status": "active",
            "runmode_status": getattr(
                owner,
                "current_runmode_status_summary",
                "RunMode idle.",
            ),
            "continuous_mode": getattr(owner, "_continuous_mode", False),
            "streaming_active": getattr(owner, "streaming_active", False),
            "token_usage": owner.get_token_usage(),
            "timestamp": datetime.now().isoformat(),
            "initialization": {
                "core_initialized": getattr(owner, "initialized", False),
                "fast_startup_enabled": (
                    getattr(owner.tool_manager, "fast_startup", False)
                    if hasattr(owner, "tool_manager")
                    else False
                ),
            },
        }

        if hasattr(owner, "get_memory_provider_status"):
            status["memory_provider"] = owner.get_memory_provider_status()

        return status

    except Exception as exc:
        logger.error("Error getting system status: %s", exc)
        return {
            "status": "error",
            "error": f"Failed to get system status: {exc!s}",
            "timestamp": datetime.now().isoformat(),
        }


def get_startup_stats(owner: Any, *, profiler: Any) -> dict[str, Any]:
    """Return startup performance statistics for a core-like owner."""
    return {
        "profiling_summary": profiler.get_summary(),
        "tool_manager_stats": (
            owner.tool_manager.get_startup_stats()
            if hasattr(owner.tool_manager, "get_startup_stats")
            else {}
        ),
        "memory_provider_initialized": hasattr(owner.tool_manager, "_memory_provider")
        and owner.tool_manager._memory_provider is not None,
        "core_initialized": owner.initialized,
    }


def print_startup_report(
    owner: Any,
    *,
    profiler: Any,
    output: Callable[[str], None] = print,
) -> None:
    """Print a comprehensive startup performance report."""
    output("\n" + "=" * 60)
    output("PENGUIN STARTUP PERFORMANCE REPORT")
    output("=" * 60)

    if hasattr(owner.tool_manager, "get_startup_stats"):
        tool_stats = owner.tool_manager.get_startup_stats()
        output("\nTool Manager Configuration:")
        output(f"  Fast startup mode: {tool_stats.get('fast_startup', 'Unknown')}")
        output(
            "  Memory provider initialized: "
            f"{tool_stats.get('memory_provider_exists', 'Unknown')}"
        )
        output(
            f"  Indexing completed: {tool_stats.get('indexing_completed', 'Unknown')}"
        )

        lazy_init = tool_stats.get("lazy_initialized", {})
        output("\nLazy-loaded components:")
        for component, initialized in lazy_init.items():
            status = "✓ Loaded" if initialized else "○ Deferred"
            output(f"  {component}: {status}")

    output("\nDetailed Performance Breakdown:")
    profiler_report = profiler.get_startup_report()
    output(profiler_report)

    output("=" * 60)


def enable_fast_startup_globally(owner: Any, *, logger: Any) -> None:
    """Enable fast startup mode for future operations."""
    if hasattr(owner.tool_manager, "fast_startup"):
        owner.tool_manager.fast_startup = True
        logger.info("Fast startup mode enabled globally")


def get_memory_provider_status(owner: Any) -> dict[str, Any]:
    """Return current memory provider and indexing status."""
    if not hasattr(owner.tool_manager, "_memory_provider"):
        return {"status": "not_initialized", "provider": None}

    provider = owner.tool_manager._memory_provider
    if provider is None:
        return {"status": "disabled", "provider": None}

    status = {
        "status": "initialized" if provider else "not_initialized",
        "provider": type(provider).__name__ if provider else None,
        "indexing_completed": getattr(owner.tool_manager, "_indexing_completed", False),
        "indexing_task_running": False,
    }

    if (
        hasattr(owner.tool_manager, "_indexing_task")
        and owner.tool_manager._indexing_task
    ):
        task = owner.tool_manager._indexing_task
        status["indexing_task_running"] = not task.done()
        status["indexing_task_status"] = {
            "done": task.done(),
            "cancelled": task.cancelled(),
            "exception": (
                str(task.exception()) if task.done() and task.exception() else None
            ),
        }

    return status


async def get_telemetry_summary(owner: Any) -> dict[str, Any]:
    """Return telemetry snapshot data when telemetry is configured."""

    telemetry = getattr(owner, "telemetry", None)
    if telemetry is None:
        return {}
    return await telemetry.snapshot()
