"""Process input normalization helpers for :mod:`penguin.core`."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

__all__ = ["NormalizedProcessInput", "normalize_process_input"]


@dataclass(frozen=True)
class NormalizedProcessInput:
    """Normalized user input values consumed by ``PenguinCore.process``."""

    message: Any
    image_paths: Any
    client_message_id: str | None

    @property
    def is_empty(self) -> bool:
        """Return whether the request has neither text nor image input."""

        return not self.message and not self.image_paths


def _normalize_client_message_id(value: Any) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    return value


def _normalize_image_paths(payload: Mapping[str, Any]) -> Any:
    image_paths = payload.get("image_paths")
    if not image_paths:
        legacy_path = payload.get("image_path")
        if isinstance(legacy_path, str) and legacy_path.strip():
            image_paths = [legacy_path.strip()]

    if isinstance(image_paths, str):
        return [image_paths.strip()] if image_paths.strip() else None
    if isinstance(image_paths, list):
        normalized = [
            path.strip()
            for path in image_paths
            if isinstance(path, str) and path.strip()
        ]
        return normalized or None
    return image_paths


def normalize_process_input(
    input_data: str | Mapping[str, Any],
) -> NormalizedProcessInput:
    """Normalize the flexible process input payload without changing semantics."""

    if isinstance(input_data, str):
        return NormalizedProcessInput(
            message=input_data,
            image_paths=None,
            client_message_id=None,
        )

    return NormalizedProcessInput(
        message=input_data.get("text", ""),
        image_paths=_normalize_image_paths(input_data),
        client_message_id=_normalize_client_message_id(
            input_data.get("client_message_id")
        ),
    )
