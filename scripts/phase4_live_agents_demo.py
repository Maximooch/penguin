"""Example end-to-end multi-agent run using real PenguinCore."""

from __future__ import annotations

import asyncio
from typing import Optional

from penguin.api_client import ChatOptions, PenguinClient, create_client

PLANNER_SYSTEM_PROMPT = (
    "You are the Planner agent. Focus on analyzing requirements, outlining steps, and "
    "delegating implementation tasks. Keep responses concise and structured."
)

IMPLEMENTER_SYSTEM_PROMPT = (
    "You are the Implementer agent. Apply code changes, run tools, and report concrete "
    "modifications. Prefer actionable commands over high-level discussion."
)

QA_SYSTEM_PROMPT = (
    "You are the QA agent. Verify fixes, design tests, and report validation results."
)

ROOM = "dev-room"


async def chat(client: PenguinClient, agent_id: str, message: str) -> str:
    print(f"\n[{agent_id.upper()} INPUT]\n{message}\n")
    response = await client.chat(
        message,
        options=ChatOptions(agent_id=agent_id, streaming=False),
    )
    print(f"[{agent_id.upper()} OUTPUT]\n{response}\n")
    return response


async def main() -> None:
    async with await create_client() as client:
        # Register agents with tailored prompts
        client.create_agent("planner", system_prompt=PLANNER_SYSTEM_PROMPT, activate=True)
        client.create_agent("implementer", system_prompt=IMPLEMENTER_SYSTEM_PROMPT)
        client.create_agent("qa", system_prompt=QA_SYSTEM_PROMPT)

        # Planner analyses the bug
        planner_brief = await chat(
            client,
            "planner",
            "We observed summarize_numbers([]) raising ValueError. Outline a remediation plan.",
        )

        # Share planner brief in the dev room
        await client.send_to_agent(
            "implementer",
            planner_brief,
            channel=ROOM,
            metadata={"from": "planner"},
        )

        # Implementer performs modifications
        await chat(
            client,
            "implementer",
            "Apply the planner's recommended fix and mention any tests we should run.",
        )

        # QA validates and reports results
        qa_summary = await chat(
            client,
            "qa",
            "Validate that summarize_numbers([]) no longer errors and note regression coverage.",
        )

        # Broadcast QA verdict back to planner and human
        await client.send_to_agent(
            "planner",
            qa_summary,
            channel=ROOM,
            metadata={"from": "qa"},
        )
        await client.send_to_human(
            qa_summary,
            channel=ROOM,
            metadata={"from": "qa"},
        )

        # Print room history for review
        print("\n=== dev-room transcripts ===")
        for agent in ("planner", "implementer", "qa"):
            session_id = client.core.conversation_manager.agent_sessions[agent].session.id  # type: ignore[attr-defined]
            history = client.get_conversation_history(session_id, include_system=False)
            print(f"\nAgent: {agent} (session {session_id})")
            for entry in history:
                if entry.get("metadata", {}).get("channel") != ROOM:
                    continue
                print(
                    f"  [{entry['timestamp']}] {entry['agent_id']} -> {entry['recipient_id']}: "
                    f"{entry['content']}"
                )


if __name__ == "__main__":
    asyncio.run(main())
