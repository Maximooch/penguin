from pathlib import Path

from penguin.skills.manager import SkillManager
from penguin.system.conversation import ConversationSystem
from penguin.system.state import MessageCategory
from penguin.tools.core.skill_tools import SkillTools


class ConversationManagerStub:
    def __init__(self) -> None:
        self.conversation = ConversationSystem()


def make_skill(path: Path, name: str) -> None:
    path.mkdir(parents=True, exist_ok=True)
    (path / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: Desc\n---\nInstructions.\n",
        encoding="utf-8",
    )


def test_activate_skill_tool_loads_context_message_once(tmp_path: Path) -> None:
    make_skill(tmp_path / "skills" / "demo", "demo-skill")
    manager = SkillManager({"skills": {"scan_paths": {"user": [str(tmp_path / "skills")]}}})
    conversation_manager = ConversationManagerStub()
    tools = SkillTools(manager, conversation_manager=conversation_manager)

    tools.activate_skill("demo-skill")
    tools.activate_skill("demo-skill")

    skill_messages = [
        msg for msg in conversation_manager.conversation.session.messages
        if msg.metadata.get("type") == "skill_activation"
    ]
    assert len(skill_messages) == 1
    assert skill_messages[0].category == MessageCategory.CONTEXT


def test_deactivate_skill_tool_removes_loaded_context_message(tmp_path: Path) -> None:
    make_skill(tmp_path / "skills" / "demo", "demo-skill")
    manager = SkillManager({"skills": {"scan_paths": {"user": [str(tmp_path / "skills")]}}})
    conversation_manager = ConversationManagerStub()
    tools = SkillTools(manager, conversation_manager=conversation_manager)

    tools.activate_skill("demo-skill", session_id="s1")
    assert manager.is_active("demo-skill", "s1")
    assert any(
        msg.metadata.get("type") == "skill_activation"
        for msg in conversation_manager.conversation.session.messages
    )

    tools.deactivate_skill("demo-skill", session_id="s1")

    assert not manager.is_active("demo-skill", "s1")
    assert not any(
        msg.metadata.get("type") == "skill_activation"
        for msg in conversation_manager.conversation.session.messages
    )
