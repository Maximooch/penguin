"""Legacy multiedit compatibility facade.

The canonical edit execution path now lives in `penguin.tools.editing`.
This module remains only to preserve older imports and tests.
"""

from __future__ import annotations

from .editing.legacy_multifile import (
    FileEdit,
    MultiEdit,
    MultiEditResult,
    apply_multiedit,
)

__all__ = [
    "FileEdit",
    "MultiEdit",
    "MultiEditResult",
    "apply_multiedit",
]
