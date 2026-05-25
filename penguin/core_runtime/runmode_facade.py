"""RunMode lifecycle compatibility facade methods for ``PenguinCore``."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from penguin.run_mode import RunMode
from penguin.utils.log_error import log_error

from . import runmode_lifecycle as core_runmode_lifecycle

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

__all__ = ["RunModeCoreFacade"]

logger = logging.getLogger("penguin.core")


class RunModeCoreFacade:
    """Compatibility method for autonomous RunMode execution."""

    async def start_run_mode(
        self,
        name: str | None = None,
        description: str | None = None,
        context: dict[str, Any] | None = None,
        continuous: bool = False,
        time_limit: int | None = None,
        mode_type: str = "task",
        stream_callback_for_cli: Callable[[str], Awaitable[None]] | None = None,
        ui_update_callback_for_cli: Callable[[], Awaitable[None]] | None = None,
    ) -> None:
        """Start autonomous run mode for executing a task."""
        await core_runmode_lifecycle.start_run_mode(
            self,
            name=name,
            description=description,
            context=context,
            continuous=continuous,
            time_limit=time_limit,
            mode_type=mode_type,
            stream_callback_for_cli=stream_callback_for_cli,
            ui_update_callback_for_cli=ui_update_callback_for_cli,
            run_mode_factory=RunMode,
            log_error=log_error,
            logger=logger,
        )
