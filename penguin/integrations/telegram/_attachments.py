"""Inbound Telegram attachment validation."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PIL import Image, UnidentifiedImageError

if TYPE_CHECKING:
    from pathlib import Path

TEXT_DOCUMENT_MIMES = frozenset(
    {
        "application/json",
        "application/xml",
        "application/x-yaml",
        "text/csv",
        "text/markdown",
        "text/plain",
        "text/yaml",
    }
)


def validate_image(path: Path) -> None:
    """Reject malformed or unsupported Telegram photos."""

    try:
        with Image.open(path) as image:
            image.verify()
    except (OSError, UnidentifiedImageError) as exc:
        raise ValueError("Telegram photo is not a valid supported image") from exc


__all__ = ["TEXT_DOCUMENT_MIMES", "validate_image"]
