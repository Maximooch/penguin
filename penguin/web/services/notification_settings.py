"""Notification settings payloads for Penguin TUI clients."""

from __future__ import annotations

import os
from typing import Any

NOTIFICATION_MODES = {
    "off",
    "visual",
    "bell",
    "osc",
    "os",
    "terminal",
    "sound",
    "combined",
}
SOUND_PACKS = {"generic", "train_station", "penguin"}


def _env_bool(name: str, *, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _env_choice(name: str, allowed: set[str], *, default: str) -> str:
    value = os.getenv(name, "").strip().lower().replace("-", "_")
    return value if value in allowed else default


def _quiet_hours_from_env() -> dict[str, str] | None:
    start = os.getenv("PENGUIN_TUI_NOTIFICATION_QUIET_START", "").strip()
    end = os.getenv("PENGUIN_TUI_NOTIFICATION_QUIET_END", "").strip()
    if not start or not end:
        return None
    return {"start": start, "end": end}


def notification_settings_payload(core: Any | None = None) -> dict[str, Any]:
    """Return notification policy metadata for the terminal TUI.

    The backend owns the user-visible policy defaults and capabilities. The TUI
    still owns terminal-specific delivery, so unsupported OS/terminal adapters
    remain opt-in no-ops unless configured by the client.
    """
    mode = _env_choice(
        "PENGUIN_TUI_NOTIFICATION_MODE",
        NOTIFICATION_MODES,
        default="off",
    )
    sound_pack = _env_choice(
        "PENGUIN_TUI_NOTIFICATION_SOUND_PACK",
        SOUND_PACKS,
        default="generic",
    )
    payload: dict[str, Any] = {
        "mode": mode,
        "soundPack": sound_pack,
        "includeDetails": _env_bool(
            "PENGUIN_TUI_NOTIFICATION_INCLUDE_DETAILS",
            default=False,
        ),
        "supportedModes": sorted(NOTIFICATION_MODES),
        "soundPacks": sorted(SOUND_PACKS),
        "terminalAdapters": ["cmux", "ghostty"],
        "delivery": {
            "owner": "client",
            "portable": ["visual", "bell", "osc"],
            "optional": ["os", "terminal", "sound"],
        },
    }

    quiet_hours = _quiet_hours_from_env()
    if quiet_hours:
        payload["quietHours"] = quiet_hours

    return payload
