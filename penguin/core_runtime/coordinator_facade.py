"""Multi-agent coordinator compatibility facade methods for ``PenguinCore``."""

from __future__ import annotations

import logging
from typing import Any

from penguin.multi import coordinator_runtime as multi_coordinator_runtime

__all__ = ["CoordinatorCoreFacade"]

logger = logging.getLogger("penguin.core")


class CoordinatorCoreFacade:
    """Compatibility method for accessing the core-scoped coordinator."""

    def get_coordinator(self) -> Any:
        """Return a singleton MultiAgentCoordinator bound to this Core."""
        return multi_coordinator_runtime.get_core_coordinator(self, log=logger)
