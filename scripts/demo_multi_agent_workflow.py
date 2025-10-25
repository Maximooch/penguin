"""
Multi-Agent Workflow Demo

Demonstrates a complete multi-agent workflow using the Web API:
1. Spawn a team of agents (coordinator, coder, qa)
2. Coordinator delegates a task to coder
3. Coder completes the task and notifies QA
4. QA verifies and reports back to coordinator
5. Show complete message history

This is a simplified version suitable for demonstrating the API in action.

Run:
    penguin serve  # In one terminal
    python scripts/demo_multi_agent_workflow.py  # In another
"""

from __future__ import annotations

import time
from typing import Dict, List, Any

import requests

BASE_URL = "http://localhost:8000"


class AgentTeam:
    """Simplified multi-agent team orchestrator"""

    def __init__(self, base_url: str = BASE_URL):
        self.base_url = base_url
        self.session = requests.Session()
        self.agents: List[str] = []

    def _url(self, path: str) -> str:
        return f"{self.base_url}{path}"

    def spawn_agent(self, agent_id: str, role: str, persona: str, model_config_id: str = "anthropic/claude-sonnet-4") -> None:
        """Create a new agent"""
        print(f"🚀 Spawning {role}: {agent_id}")
        response = self.session.post(
            self._url("/api/v1/agents"),
            json={
                "id": agent_id,
                "model_config_id": model_config_id,
                "role": role,
                "persona": persona,
            },
        )
        response.raise_for_status()
        self.agents.append(agent_id)
        print(f"   ✅ {agent_id} is ready")

    def send_message(
        self, sender: str, recipient: str, content: str, channel: str = "#team"
    ) -> None:
        """Send a message from one agent to another"""
        print(f"💬 {sender} → {recipient}: {content[:50]}...")
        response = self.session.post(
            self._url("/api/v1/messages"),
            json={
                "sender": sender,
                "recipient": recipient,
                "content": content,
                "message_type": "message",
                "channel": channel,
            },
        )
        response.raise_for_status()

    def delegate(
        self, parent: str, child: str, task: str, summary: str
    ) -> str:
        """Delegate a task from parent to child"""
        print(f"📋 {parent} delegates to {child}: {summary}")
        response = self.session.post(
            self._url(f"/api/v1/agents/{child}/delegate"),
            json={
                "parent_agent_id": parent,
                "content": task,
                "summary": summary,
            },
        )
        response.raise_for_status()
        result = response.json()
        delegation_id = result.get("delegation_id", "unknown")
        print(f"   ✅ Delegation created: {delegation_id}")
        return delegation_id

    def get_roster(self) -> List[Dict[str, Any]]:
        """Get current agent roster"""
        response = self.session.get(self._url("/api/v1/agents"))
        response.raise_for_status()
        return response.json()

    def cleanup(self) -> None:
        """Delete all created agents"""
        print("\n🧹 Cleaning up agents...")
        for agent_id in self.agents:
            try:
                response = self.session.delete(
                    self._url(f"/api/v1/agents/{agent_id}"),
                    params={"preserve_conversation": False},
                )
                response.raise_for_status()
                print(f"   🗑️  Deleted {agent_id}")
            except Exception as e:
                print(f"   ⚠️  Failed to delete {agent_id}: {e}")


def main():
    """Run the demo workflow"""
    print("\n" + "=" * 70)
    print("MULTI-AGENT WORKFLOW DEMO")
    print("=" * 70 + "\n")

    team = AgentTeam()

    try:
        # Step 1: Spawn the team
        print("📍 STEP 1: Spawn Agent Team")
        print("-" * 70)
        team.spawn_agent(
            "coordinator",
            "lead",
            "Project coordinator responsible for task delegation",
        )
        team.spawn_agent(
            "coder",
            "engineer",
            "Python developer specializing in backend systems",
        )
        team.spawn_agent(
            "qa",
            "tester",
            "Quality assurance engineer for testing and verification",
        )

        time.sleep(0.5)  # Brief pause for visibility

        # Step 2: Show roster
        print("\n📍 STEP 2: Agent Roster")
        print("-" * 70)
        roster = team.get_roster()
        for agent in roster:
            status = "●" if agent.get("is_active") else "○"
            print(f"{status} {agent['id']}: {agent.get('persona', 'No description')}")

        time.sleep(0.5)

        # Step 3: Coordinator delegates to coder
        print("\n📍 STEP 3: Task Delegation")
        print("-" * 70)
        delegation_id = team.delegate(
            "coordinator",
            "coder",
            task=(
                "Implement a new authentication endpoint for the API. "
                "It should support JWT tokens and include rate limiting."
            ),
            summary="Implement JWT authentication endpoint",
        )

        time.sleep(0.5)

        # Step 4: Coder → QA
        print("\n📍 STEP 4: Work Handoff")
        print("-" * 70)
        team.send_message(
            "coder",
            "qa",
            (
                "Authentication endpoint completed. "
                "Implementation includes JWT token validation, "
                "rate limiting (100 req/min), and comprehensive error handling. "
                "Ready for testing."
            ),
            channel="#engineering",
        )

        time.sleep(0.5)

        # Step 5: QA → Coordinator
        print("\n📍 STEP 5: Verification & Report")
        print("-" * 70)
        team.send_message(
            "qa",
            "coordinator",
            (
                "QA Report: Authentication endpoint verified. "
                "All tests passed:\n"
                "✓ JWT validation works correctly\n"
                "✓ Rate limiting enforced\n"
                "✓ Error responses are appropriate\n"
                "✓ Security headers present\n"
                "Status: APPROVED for deployment"
            ),
            channel="#team",
        )

        time.sleep(0.5)

        # Step 6: Coordinator acknowledgment
        print("\n📍 STEP 6: Task Completion")
        print("-" * 70)
        team.send_message(
            "coordinator",
            "coder",
            (
                "Great work on the authentication endpoint! "
                "QA has approved it for deployment. "
                "Moving to next task in the backlog."
            ),
            channel="#team",
        )

        # Summary
        print("\n" + "=" * 70)
        print("✅ WORKFLOW COMPLETE")
        print("=" * 70)
        print("\nSummary:")
        print(f"  • Spawned {len(team.agents)} agents")
        print(f"  • Created delegation: {delegation_id}")
        print("  • Agents communicated across #engineering and #team channels")
        print("  • Task completed: JWT authentication endpoint")
        print("\nNext steps:")
        print("  • View message history in Penguin backend logs")
        print("  • Test WebSocket streaming with: wscat -c ws://localhost:8000/api/v1/ws/messages")
        print("  • Explore agent profiles: curl http://localhost:8000/api/v1/agents/{agent_id}")

    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        raise

    finally:
        team.cleanup()

    print("\n" + "=" * 70)
    print("Demo completed successfully!")
    print("=" * 70 + "\n")


if __name__ == "__main__":
    main()
