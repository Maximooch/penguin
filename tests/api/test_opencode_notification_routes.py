"""Tests for OpenCode-compatible notification settings routes."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from penguin.web.routes import api_notification_config
from penguin.web.services.notification_settings import notification_settings_payload


def test_notification_settings_default_to_disabled(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("PENGUIN_TUI_NOTIFICATION_MODE", raising=False)
    monkeypatch.delenv("PENGUIN_TUI_NOTIFICATION_SOUND_PACK", raising=False)

    payload = notification_settings_payload()

    assert payload["mode"] == "off"
    assert payload["soundPack"] == "generic"
    assert {"bell", "combined", "sound"} <= set(payload["supportedModes"])
    assert {"generic", "penguin", "train_station"} <= set(payload["soundPacks"])
    assert payload["delivery"]["owner"] == "client"


def test_notification_settings_accept_env_policy(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("PENGUIN_TUI_NOTIFICATION_MODE", "combined")
    monkeypatch.setenv("PENGUIN_TUI_NOTIFICATION_SOUND_PACK", "train-station")
    monkeypatch.setenv("PENGUIN_TUI_NOTIFICATION_INCLUDE_DETAILS", "true")
    monkeypatch.setenv("PENGUIN_TUI_NOTIFICATION_QUIET_START", "22:00")
    monkeypatch.setenv("PENGUIN_TUI_NOTIFICATION_QUIET_END", "07:00")

    payload = notification_settings_payload()

    assert payload["mode"] == "combined"
    assert payload["soundPack"] == "train_station"
    assert payload["includeDetails"] is True
    assert payload["quietHours"] == {"start": "22:00", "end": "07:00"}


@pytest.mark.asyncio
async def test_api_notification_config_returns_policy_payload():
    payload = await api_notification_config(core=SimpleNamespace())

    assert payload["mode"] in payload["supportedModes"]
    assert "ghostty" in payload["terminalAdapters"]
