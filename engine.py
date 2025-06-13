# shim module – will be removed once full consolidation is done.
"""penguin.engine

Compatibility shim mapping the historical import path ``penguin.engine`` to
``penguin.penguin.engine``.

Down-stream code can continue to use ``from penguin.engine import Engine``
without modification during the ongoing namespace consolidation.
"""

from __future__ import annotations

import importlib
import sys
from types import ModuleType
from typing import TYPE_CHECKING

_real_mod: ModuleType = importlib.import_module("penguin.penguin.engine")

# Alias the real module so the import system hands it out for the shim name.
sys.modules[__name__] = _real_mod

# Static-analysis: surface the Engine class for type checkers
if TYPE_CHECKING:  # pragma: no cover
    from penguin.penguin.engine import (  # type: ignore  # noqa: F401
        Engine,
        EngineSettings,
        StopCondition,
        TokenBudgetStop,
        WallClockStop,
    ) 