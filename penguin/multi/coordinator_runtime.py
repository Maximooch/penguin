"""Coordinator access helpers for PenguinCore multi-agent orchestration."""

from __future__ import annotations

import logging
from typing import Any, Callable

__all__ = ["get_core_coordinator"]

logger = logging.getLogger(__name__)

CoordinatorFactory = Callable[[Any], Any]


def get_core_coordinator(
    core: Any,
    *,
    coordinator_factory: CoordinatorFactory | None = None,
    log: logging.Logger | None = None,
) -> Any:
    """Return a cached MultiAgentCoordinator for a core-like owner."""
    active_logger = log or logger
    try:
        coordinator = getattr(core, "_coordinator", None)
        if coordinator is None:
            if coordinator_factory is None:
                from penguin.multi.coordinator import MultiAgentCoordinator

                coordinator_factory = MultiAgentCoordinator
            coordinator = coordinator_factory(core)
            core._coordinator = coordinator
        return coordinator
    except Exception as exc:
        active_logger.error("Failed to get coordinator: %s", exc)
        raise
