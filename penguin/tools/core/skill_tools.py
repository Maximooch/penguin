"""Tool helpers for listing and activating Agent Skills."""

from __future__ import annotations

import json
from typing import Any, Optional

from penguin.skills.manager import SkillManager
from penguin.system.state import MessageCategory


class SkillTools:
    """Adapter exposing SkillManager operations as Penguin tools."""

    def __init__(self, manager: SkillManager, *, conversation_manager: Any = None):
        self.manager = manager
        self.conversation_manager = conversation_manager

    def list_skills(
        self,
        refresh: bool = False,
        session_id: Optional[str] = None,
    ) -> str:
        resolved_session_id = session_id or self._current_session_id() or "default"
        if refresh:
            self.manager.refresh()
        payload = self.manager.list_payload()
        active_names = set(self.manager.active_names(resolved_session_id))
        payload["active"] = sorted(active_names)
        payload["skills"] = [
            {**skill, "active": skill.get("name") in active_names}
            for skill in payload.get("skills", [])
        ]
        return json.dumps(payload, indent=2)

    def activate_skill(
        self,
        name: str,
        session_id: Optional[str] = None,
        load_into_context: bool = True,
    ) -> str:
        resolved_session_id = session_id or self._current_session_id() or "default"
        result = self.manager.activate(name, session_id=resolved_session_id)
        if result.get("status") == "activated" and load_into_context:
            self._add_skill_context(name, result["content"])
        return json.dumps(result, indent=2)

    def deactivate_skill(
        self,
        name: str,
        session_id: Optional[str] = None,
    ) -> str:
        resolved_session_id = session_id or self._current_session_id() or "default"
        result = self.manager.deactivate(name, session_id=resolved_session_id)
        if result.get("status") == "deactivated":
            self._remove_skill_context(name)
        return json.dumps(result, indent=2)

    def _current_session_id(self) -> Optional[str]:
        try:
            conversation = self.conversation_manager.conversation
            return conversation.session.id
        except Exception:
            return None

    def _add_skill_context(self, name: str, content: str) -> None:
        if self.conversation_manager is None:
            return
        try:
            message = self.conversation_manager.conversation.add_message(
                "system",
                content,
                MessageCategory.CONTEXT,
                {
                    "source": f"skill:{name}",
                    "type": "skill_activation",
                    "skill_name": name,
                },
            )
            message.metadata.setdefault("skill_name", name)
        except Exception:
            return

    def _remove_skill_context(self, name: str) -> None:
        if self.conversation_manager is None:
            return
        try:
            conversation = self.conversation_manager.conversation
            session = conversation.session
            session.messages = [
                message
                for message in session.messages
                if (
                    message.metadata.get("skill_name") != name
                    or message.metadata.get("type") != "skill_activation"
                )
            ]
            if hasattr(conversation, "_modified"):
                conversation._modified = True
        except Exception:
            return
