"""Phase 0 REST API smoke checks for multi-agent endpoints.

This script spins up a FastAPI application with the real ``penguin.web.routes``
router but injects stubbed core/coordinator implementations so the agent
lifecycle endpoints can be exercised without bringing up the full Penguin
runtime. Intended usage:

    uv run python scripts/phase0_agents_api_smoke.py

It validates the happy-path behaviour for:

* Listing agents
* Spawning/destroying agents via the coordinator
* Sending directed messages to agents / humans
* Coordinator round-robin role routing helpers
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import FastAPI
from fastapi.testclient import TestClient

from penguin.web.routes import router


# ---------------------------------------------------------------------------
# Stub core + coordinator
# ---------------------------------------------------------------------------


class StubConversation:
    def __init__(self, agent_id: str) -> None:
        self.session = type("Session", (), {"id": f"session-{agent_id}"})()


class StubConversationManager:
    def __init__(self) -> None:
        self.agent_sessions: Dict[str, StubConversation] = {"default": StubConversation("default")}


class StubCoordinator:
    def __init__(self, core: "StubCore") -> None:
        self.core = core
        self.agents_by_role: Dict[str, List[str]] = {}
        self._rr_index: Dict[str, int] = {}

    async def spawn_agent(
        self,
        agent_id: str,
        *,
        role: str,
        system_prompt: Optional[str] = None,
        model_max_tokens: Optional[int] = None,
        activate: bool = False,
    ) -> None:
        self.core.conversation_manager.agent_sessions[agent_id] = StubConversation(agent_id)
        self.agents_by_role.setdefault(role, []).append(agent_id)
        self._rr_index.setdefault(role, 0)

    async def destroy_agent(self, agent_id: str) -> None:
        self.core.conversation_manager.agent_sessions.pop(agent_id, None)
        for agents in self.agents_by_role.values():
            if agent_id in agents:
                agents.remove(agent_id)
        for role, agents in list(self.agents_by_role.items()):
            if not agents:
                self.agents_by_role.pop(role, None)
                self._rr_index.pop(role, None)
            else:
                self._rr_index[role] %= max(len(agents), 1)

    def register_existing(self, agent_id: str, *, role: str) -> None:
        self.agents_by_role.setdefault(role, []).append(agent_id)
        self._rr_index.setdefault(role, 0)

    async def send_to_role(self, role: str, content: Any, *, message_type: str = "message") -> Optional[str]:
        agents = self.agents_by_role.get(role) or []
        if not agents:
            return None
        idx = self._rr_index.get(role, 0) % len(agents)
        target = agents[idx]
        self._rr_index[role] = (idx + 1) % len(agents)
        await self.core.send_to_agent(target, content, message_type=message_type)
        return target

    async def broadcast(self, roles: List[str], content: Any, *, message_type: str = "message") -> List[str]:
        sent: List[str] = []
        for role in roles:
            for agent_id in self.agents_by_role.get(role, []):
                await self.core.send_to_agent(agent_id, content, message_type=message_type)
                sent.append(agent_id)
        return sent

    async def simple_round_robin_workflow(self, prompts: List[str], *, role: str) -> None:
        for prompt in prompts:
            await self.send_to_role(role, prompt)

    async def role_chain_workflow(self, content: str, *, roles: List[str]) -> None:
        for role in roles:
            await self.send_to_role(role, content)


class StubCore:
    def __init__(self) -> None:
        self.conversation_manager = StubConversationManager()
        self.messages: List[Dict[str, Any]] = []
        self.coordinator = StubCoordinator(self)

    def get_coordinator(self) -> StubCoordinator:
        return self.coordinator

    async def send_to_agent(self, agent_id: str, content: Any, *, message_type: str = "message", metadata: Optional[Dict[str, Any]] = None) -> bool:
        self.messages.append({"target": agent_id, "content": content, "message_type": message_type, "metadata": metadata})
        return True

    async def send_to_human(self, content: Any, *, message_type: str = "status", metadata: Optional[Dict[str, Any]] = None) -> bool:
        self.messages.append({"target": "human", "content": content, "message_type": message_type, "metadata": metadata})
        return True

    async def human_reply(self, agent_id: str, content: Any, *, message_type: str = "message", metadata: Optional[Dict[str, Any]] = None) -> bool:
        self.messages.append({"target": agent_id, "content": content, "message_type": message_type, "metadata": metadata, "origin": "human"})
        return True


# ---------------------------------------------------------------------------
# Helper utilities
# ---------------------------------------------------------------------------


def build_app(core: StubCore) -> TestClient:
    router.core = core
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def pretty(title: str, payload: Any) -> None:
    print(f"\n=== {title} ===")
    print(payload)


def run_smoke() -> None:
    core = StubCore()
    client = build_app(core)

    pretty("GET /api/v1/agents", client.get("/api/v1/agents").json())

    resp = client.post(
        "/api/v1/agents",
        json={"agent_id": "planner", "role": "planner", "activate": True},
    )
    pretty("POST /api/v1/agents", resp.json())

    resp = client.post(
        "/api/v1/agents",
        json={"agent_id": "planner2", "role": "planner"},
    )
    pretty("POST /api/v1/agents (second)", resp.json())

    resp = client.post(
        "/api/v1/messages/to-agent",
        json={"agent_id": "planner", "content": {"task": "plan"}},
    )
    pretty("POST /api/v1/messages/to-agent", resp.json())

    resp = client.post(
        "/api/v1/messages/to-human",
        json={"content": "status update"},
    )
    pretty("POST /api/v1/messages/to-human", resp.json())

    resp = client.post(
        "/api/v1/messages/human-reply",
        json={"agent_id": "planner", "content": "Thanks"},
    )
    pretty("POST /api/v1/messages/human-reply", resp.json())

    resp = client.post(
        "/api/v1/coord/send-role",
        json={"role": "planner", "content": "next step"},
    )
    pretty("POST /api/v1/coord/send-role", resp.json())

    resp = client.post(
        "/api/v1/coord/broadcast",
        json={"roles": ["planner"], "content": "broadcast"},
    )
    pretty("POST /api/v1/coord/broadcast", resp.json())

    resp = client.post(
        "/api/v1/coord/rr-workflow",
        json={"role": "planner", "prompts": ["A", "B"]},
    )
    pretty("POST /api/v1/coord/rr-workflow", resp.json())

    resp = client.post(
        "/api/v1/coord/role-chain",
        json={"roles": ["planner"], "content": "handoff"},
    )
    pretty("POST /api/v1/coord/role-chain", resp.json())

    resp = client.delete("/api/v1/agents/planner")
    pretty("DELETE /api/v1/agents/planner", resp.json())

    resp = client.delete("/api/v1/agents/planner2")
    pretty("DELETE /api/v1/agents/planner2", resp.json())

    print("\nCaptured messages:")
    for message in core.messages:
        print(message)


if __name__ == "__main__":
    run_smoke()
