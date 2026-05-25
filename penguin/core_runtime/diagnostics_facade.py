"""Diagnostics and startup compatibility facade methods for ``PenguinCore``."""

from __future__ import annotations

import logging
from typing import Any

from penguin._version import __version__ as PENGUIN_VERSION
from penguin.utils.profiling import profiler

from . import (
    agent_lifecycle as core_agent_lifecycle,
    system_diagnostics as core_system_diagnostics,
)

__all__ = ["DiagnosticsCoreFacade"]

logger = logging.getLogger("penguin.core")


class DiagnosticsCoreFacade:
    """Compatibility methods for core diagnostics and startup helpers."""

    async def get_telemetry_summary(self) -> dict[str, Any]:
        return await core_system_diagnostics.get_telemetry_summary(self)

    def smoke_check_agents(self) -> dict[str, Any]:
        """Return a diagnostic snapshot of agent wiring and context windows."""
        return core_agent_lifecycle.smoke_check_agents(self)

    def get_system_info(self) -> dict[str, Any]:
        """
        Get comprehensive system information.

        Returns:
            Dictionary containing system information including model config,
            component status, and capabilities
        """
        return core_system_diagnostics.get_system_info(
            self,
            version=PENGUIN_VERSION,
            logger=logger,
        )

    def get_system_status(self) -> dict[str, Any]:
        """
        Get current system status including runtime state.

        Returns:
            Dictionary containing current system status and runtime information
        """
        return core_system_diagnostics.get_system_status(self, logger=logger)

    def get_startup_stats(self) -> dict[str, Any]:
        """Get comprehensive startup performance statistics."""
        return core_system_diagnostics.get_startup_stats(self, profiler=profiler)

    def print_startup_report(self) -> None:
        """Print a comprehensive startup performance report."""
        core_system_diagnostics.print_startup_report(self, profiler=profiler)

    def enable_fast_startup_globally(self) -> None:
        """Enable fast startup mode for future operations."""
        core_system_diagnostics.enable_fast_startup_globally(self, logger=logger)

    def get_memory_provider_status(self) -> dict[str, Any]:
        """Get current status of memory provider and indexing."""
        return core_system_diagnostics.get_memory_provider_status(self)
