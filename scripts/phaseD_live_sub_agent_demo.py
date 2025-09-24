"""
Phase D – Live Sub-Agent Demo

Spin up a few scoped sub-agents using the Python client, run research-style
prompts against each, and print their results along with session info. This
is meant to mimic a small “in the wild” workflow beyond the smoke harnesses.

Usage:
    uv run python scripts/phaseD_live_sub_agent_demo.py

Assumes the default parent agent is available and that the Moonshot Kimi model
has been configured (model id ``moonshotai/kimi-k2-0905``). Adjust prompts or
model id via environment variables if needed.
"""

from __future__ import annotations

import asyncio
import json
import os
import uuid
from typing import Any, Dict

from penguin.api_client import PenguinClient


SCENARIOS = [
    {
        "label": "micro_saas",
        "persona": "research",
        "prompt": (
            "You are a fast, pragmatic researcher. Task: Generate three micro-SaaS"
            " product ideas suitable for a solo developer to ship in 6-8 weeks."
            " For each idea provide: (1) one-sentence value proposition,"
            " (2) target user + urgent pain, (3) key MVP features (max 5),"
            " (4) GTM plan (channels + first two experiments),"
            " (5) pricing hypothesis. Constraints: B2B, $20-$200 MRR, ROI inside"
            " 30 days. Output concise bullet points."),
    },
    {
        "label": "process_improvements",
        "persona": "research",
        "prompt": (
            "You are a pragmatic strategy researcher. Propose three high-leverage"
            " engineering process improvements for a five-person B2B SaaS team."
            " For each include: (1) problem, (2) expected impact with metric +"
            " estimate, (3) effort (S/M/L), (4) first experiment to validate,"
            " (5) main risk. Keep output tight, bullets only."),
    },
]

MODEL_ID = os.getenv("PENGUIN_MODEL_ID", "moonshotai/kimi-k2-0905")
SHARED_CW_MAX = int(os.getenv("PENGUIN_SHARED_CW_MAX", "250000"))


async def run_scenario(label: str, persona: str, prompt: str) -> Dict[str, Any]:
    async with PenguinClient() as client:
        core = client.core
        child_id = f"{label}_{uuid.uuid4().hex[:6]}"
        print(f"\n=== Scenario: {label} ({child_id}) ===")

        # Spawn sub-agent
        core.create_sub_agent(
            child_id,
            parent_agent_id="default",
            share_session=False,
            share_context_window=False,
            persona=persona or None,
            model_config_id=MODEL_ID,
            shared_cw_max_tokens=SHARED_CW_MAX,
            activate=True,
        )
        print(f"Spawned sub-agent '{child_id}' with persona={persona or 'default'}")

        # Run the prompt via Engine so the child produces output
        response = await core.engine.run_response(
            prompt,
            agent_id=child_id,
            max_iterations=3,
            streaming=False,
        )
        assistant_text = response.get("assistant_response", "")
        print("\nAssistant response:\n", assistant_text)

        # Gather conversation metadata
        conv = core.conversation_manager.get_agent_conversation(child_id)
        session_id = getattr(conv.session, "id", None)
        history = []
        if session_id:
            history = core.get_conversation_history(session_id, include_system=True)

        print(f"\nSession id: {session_id}")
        print(f"History entries: {len(history)}")
        return {
            "agent_id": child_id,
            "session_id": session_id,
            "assistant_response": assistant_text,
            "history": history,
        }


async def main() -> int:
    results = []
    for scenario in SCENARIOS:
        result = await run_scenario(
            label=scenario.get("label", "scenario"),
            persona=scenario.get("persona", "research"),
            prompt=scenario.get("prompt", ""),
        )
        results.append(result)

    dump_path = os.getenv("PENGUIN_PHASED_DUMP")
    if dump_path:
        with open(dump_path, "w", encoding="utf-8") as fh:
            json.dump(results, fh, ensure_ascii=False, indent=2)
        print(f"\nSaved conversation data to {dump_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

