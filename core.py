# shim module – will be removed once full consolidation is done.
"""penguin.core

Temporary compatibility shim forwarding all imports to the consolidated
implementation at ``penguin.penguin.core``.

This allows callers to simply ``import penguin.core`` regardless of whether
Penguin is being used from the monorepo or the installed, single-package
layout.  Once all code has migrated to live directly under the top-level
``penguin`` namespace the shim can be deleted.
"""

# test

from __future__ import annotations

import importlib
import sys
from types import ModuleType
from typing import TYPE_CHECKING

# ---------------------------------------------------------------------------
# Dynamically import the real module and forward *everything* to it so that
# ``sys.modules["penguin.core"]`` becomes an alias for
# ``penguin.penguin.core``.
# ---------------------------------------------------------------------------

_real_mod: ModuleType = importlib.import_module("penguin.penguin.core")

# Replace the current (empty) shim entry with the real module object so that
# subsequent ``import penguin.core`` statements receive the full module.
sys.modules[__name__] = _real_mod

# Mypy / static-analysis helpers – honour the public API
if TYPE_CHECKING:  # pragma: no cover
    from penguin.penguin.core import (  # type: ignore  # noqa: F401
        PenguinCore,  # re-export for type checkers
    ) 