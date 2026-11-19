"""Resuming a system restores that system's own previous state.

Covers SM-75 (PenguinState): one ``_previous_state`` slot was shared by every
system, so resuming one system could restore another system's state.
"""

from __future__ import annotations

import pytest

from penguin.system.state import PenguinState, SystemState


@pytest.mark.asyncio
async def test_resume_restores_the_systems_own_previous_state() -> None:
    state = PenguinState()
    await state.update_system_state("chat", SystemState.CHAT)
    await state.update_system_state("chat", SystemState.PROCESSING)
    await state.update_system_state("tools", SystemState.IDLE)
    await state.update_system_state("tools", SystemState.ERROR)

    await state.resume_previous_state("chat")

    assert state.system_states["chat"] is SystemState.CHAT
