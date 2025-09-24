"""
Phase B – Persona & Model Override

Spawns a sub-agent with persona 'research' and preferred model id
'moonshotai/kimi-k2-0905' (OpenRouter). Falls back to 'kimi-lite' or default.
Verifies with `agent info` equivalent via core.get_agent_profile.

Run: python scripts/phaseB_persona_model_override.py
"""

from __future__ import annotations

import asyncio
from typing import Optional

from penguin.api_client import PenguinClient


async def main() -> None:
    child = "persona_model_child"
    async with PenguinClient() as client:
        core = client.core

        # Preferred model id, with fallbacks
        model_id: Optional[str] = None
        cfg = getattr(core, "config", None)
        mc = getattr(cfg, "model_configs", {}) or {}
        if "moonshotai/kimi-k2-0905" in mc:
            model_id = "moonshotai/kimi-k2-0905"
        elif "kimi-lite" in mc:
            model_id = "kimi-lite"

        # If model id is unavailable, fall back to explicit model_overrides
        if model_id:
            core.create_sub_agent(
                child,
                parent_agent_id="default",
                share_session=False,
                share_context_window=False,
                persona="research",
                model_config_id=model_id,
                activate=True,
            )
        else:
            core.create_sub_agent(
                child,
                parent_agent_id="default",
                share_session=False,
                share_context_window=False,
                persona="research",
                model_overrides={
                    "model": "moonshotai/kimi-k2-0905",
                    "provider": "openrouter",
                    "client_preference": "openrouter",
                },
                activate=True,
            )

        profile = core.get_agent_profile(child) or {}
        print("[profile]", profile)
        model = (profile.get("model") or {})
        print("[model]", model)


if __name__ == "__main__":
    asyncio.run(main())
