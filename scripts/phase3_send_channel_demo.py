"""Demonstrate channel-based messaging between Penguin agents.

This script shows how multiple agents (and humans) can talk in a shared room by
leveraging the MessageBus channel plumbing added in Phase 3.

Run with:
    uv run python scripts/phase3_send_channel_demo.py
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

from penguin.core import PenguinCore
from penguin.system.message_bus import MessageBus, ProtocolMessage
from penguin.system.state import MessageCategory


class AsyncMock:
    """Tiny async-mock helper so we don't depend on unittest.mock."""

    def __init__(self) -> None:
        self.calls: List[tuple] = []

    async def __call__(self, *args: Any, **kwargs: Any) -> None:
        self.calls.append((args, kwargs))


@dataclass
class DemoMessage:
    role: str
    content: Any
    category: MessageCategory
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    metadata: Dict[str, Any] = field(default_factory=dict)
    agent_id: Optional[str] = None
    recipient_id: Optional[str] = None
    message_type: str = "message"


@dataclass
class DemoSession:
    agent_id: str
    id: str = field(init=False)
    messages: List[DemoMessage] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    last_active: str = field(default_factory=lambda: datetime.utcnow().isoformat())

    def __post_init__(self) -> None:
        self.id = f"session-{self.agent_id}-{datetime.utcnow().strftime('%H%M%S')}"
        self.metadata.setdefault("agent_id", self.agent_id)


class DemoConversation:
    def __init__(self, agent_id: str) -> None:
        self.agent_id = agent_id
        self.session = DemoSession(agent_id)
        self.system_prompt_sent = True

    def set_system_prompt(self, prompt: str) -> None:
        self.session.metadata["system_prompt"] = prompt

    def add_message(
        self,
        *,
        role: str,
        content: Any,
        category: MessageCategory,
        agent_id: Optional[str],
        recipient_id: Optional[str],
        message_type: str,
        metadata: Optional[Dict[str, Any]],
    ) -> DemoMessage:
        message = DemoMessage(
            role=role,
            content=content,
            category=category,
            agent_id=agent_id,
            recipient_id=recipient_id,
            message_type=message_type,
            metadata=metadata or {},
        )
        self.session.messages.append(message)
        self.session.last_active = message.timestamp
        return message

    def save(self) -> bool:
        return True


class DemoConversationManager:
    def __init__(self) -> None:
        self.agent_sessions: Dict[str, DemoConversation] = {}
        self.current_agent_id = "default"
        self.conversation = self._ensure("default")

    def _ensure(self, agent_id: str) -> DemoConversation:
        if agent_id not in self.agent_sessions:
            self.agent_sessions[agent_id] = DemoConversation(agent_id)
        return self.agent_sessions[agent_id]

    def set_current_agent(self, agent_id: str) -> None:
        self.current_agent_id = agent_id
        self.conversation = self._ensure(agent_id)

    def get_agent_conversation(self, agent_id: str, create_if_missing: bool = True) -> DemoConversation:
        if create_if_missing:
            return self._ensure(agent_id)
        return self.agent_sessions.get(agent_id)

    def save(self) -> bool:
        return True

    def load(self, conversation_id: str) -> bool:
        for agent_id, conv in self.agent_sessions.items():
            if conv.session.id == conversation_id:
                self.set_current_agent(agent_id)
                return True
        return False

    def get_current_session(self) -> DemoSession:
        return self.conversation.session

    def list_conversations(self, limit: int = 100, offset: int = 0, search_term: Optional[str] = None) -> List[Dict[str, Any]]:
        conversations: List[Dict[str, Any]] = []
        for agent_id, conv in self.agent_sessions.items():
            title = None
            for msg in conv.session.messages:
                if msg.role == "user":
                    text = str(msg.content)
                    title = (text[:37] + "...") if len(text) > 40 else text
                    break
            conversations.append(
                {
                    "id": conv.session.id,
                    "agent_id": agent_id,
                    "title": title or f"Session with {agent_id}",
                    "last_active": conv.session.last_active,
                }
            )
        if search_term:
            search = search_term.lower()
            conversations = [c for c in conversations if search in c["title"].lower()]
        conversations.sort(key=lambda item: item["last_active"], reverse=True)
        return conversations[offset : offset + limit]

    def get_conversation_history(
        self,
        session_id: str,
        *,
        include_system: bool = True,
        limit: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        for conv in self.agent_sessions.values():
            if conv.session.id == session_id:
                messages = []
                for msg in conv.session.messages:
                    if not include_system and msg.role == "system":
                        continue
                    messages.append(
                        {
                            "timestamp": msg.timestamp,
                            "role": msg.role,
                            "content": msg.content,
                            "category": msg.category.name,
                            "agent_id": msg.agent_id,
                            "recipient_id": msg.recipient_id,
                            "message_type": msg.message_type,
                            "metadata": msg.metadata,
                        }
                    )
                if limit is not None:
                    messages = messages[-limit:]
                return messages
        return []


async def main() -> None:
    bus = MessageBus.get_instance()
    bus._handlers.clear()  # type: ignore[attr-defined]

    manager = DemoConversationManager()

    core = PenguinCore.__new__(PenguinCore)
    core.conversation_manager = manager
    core.emit_ui_event = AsyncMock()
    core.event_types = {"message", "status"}
    core._agent_bus_handlers = {}
    core.engine = type("StubEngine", (), {"register_agent": lambda *a, **k: None, "unregister_agent": lambda *a, **k: None})()

    def attach_agent(agent_id: str) -> None:
        manager._ensure(agent_id)

        async def handler(msg: ProtocolMessage) -> None:
            manager.set_current_agent(agent_id)
            conv = manager.get_agent_conversation(agent_id)
            conv.add_message(
                role="user",
                content=msg.content,
                category=MessageCategory.DIALOG,
                agent_id=msg.sender,
                recipient_id=agent_id,
                message_type=msg.message_type,
                metadata={**msg.metadata, "channel": msg.channel},
            )

        MessageBus.get_instance().register_handler(agent_id, handler)

    for agent_id in ("planner", "implementer", "qa"):
        attach_agent(agent_id)

    async def human_handler(msg: ProtocolMessage) -> None:
        print(f"[HUMAN CHANNEL {msg.channel}] {msg.sender}: {msg.content}")

    MessageBus.get_instance().register_handler("human", human_handler)

    async def send(agent: str, target: str, content: str, channel: str) -> None:
        manager.set_current_agent(agent)
        conv = manager.get_agent_conversation(agent)
        conv.add_message(
            role="assistant",
            content=content,
            category=MessageCategory.DIALOG,
            agent_id=agent,
            recipient_id=target,
            message_type="message",
            metadata={"channel": channel},
        )
        await core.send_to_agent(
            target,
            content,
            message_type="message",
            metadata={"via": "room"},
            channel=channel,
        )

    room = "dev-room"
    await send("planner", "implementer", "Let's add input validation to summarize_numbers().", room)
    await send("implementer", "planner", "Patch ready; handing off to QA for verification.", room)
    await send("planner", "qa", "Please smoke test the fix before merging.", room)

    await core.human_reply("planner", "QA confirms tests pass!", channel=room)

    print("\n=== Conversation Histories (dev-room) ===")
    for agent_id, conv in manager.agent_sessions.items():
        history = manager.get_conversation_history(conv.session.id)
        print(f"\nAgent: {agent_id} (session {conv.session.id})")
        for entry in history:
            channel = entry["metadata"].get("channel")
            sender = entry.get("agent_id")
            print(f"  [{entry['timestamp']}] ({channel}) {sender} -> {entry['recipient_id']}: {entry['content']}")

    print("\nAvailable conversations:")
    for info in core.list_conversations():
        print(info)


if __name__ == "__main__":
    asyncio.run(main())
