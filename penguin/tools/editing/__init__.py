"""Canonical file editing contracts and service helpers."""

from .contracts import EditOperation, FileEditResult
from .service import EditService

__all__ = ["EditOperation", "FileEditResult", "EditService"]
