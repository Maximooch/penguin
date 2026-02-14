"""Configuration service helpers for route handlers."""

from __future__ import annotations

from typing import Any


def runtime_config_payload(core: Any) -> dict[str, Any]:
    """Build runtime configuration payload."""
    config_dict = core.runtime_config.to_dict()
    return {"status": "success", "config": config_dict}
