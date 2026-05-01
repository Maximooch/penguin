from pathlib import Path

from penguin.system.conversation_manager import ConversationManager
from penguin.system.state import MessageCategory


def make_skill(path: Path, name: str) -> None:
    path.mkdir(parents=True, exist_ok=True)
    (path / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: Desc\n---\nInstructions.\n",
        encoding="utf-8",
    )


def test_conversation_manager_injects_compact_skill_catalog(tmp_path: Path) -> None:
    make_skill(tmp_path / ".penguin" / "skills" / "demo", "demo-skill")
    config = {
        "skills": {
            "enabled": True,
            "trust_project_skills": True,
            "scan_paths": {"user": [], "project": [".penguin/skills"]},
        },
        "context": {"autoload_project_docs": False},
    }

    manager = ConversationManager(
        workspace_path=tmp_path,
        skills_config=config,
        project_root=tmp_path,
    )

    messages = [msg for msg in manager.conversation.session.messages if msg.metadata.get("source") == "skills_catalog"]
    assert len(messages) == 1
    assert messages[0].category == MessageCategory.CONTEXT
    assert "demo-skill" in messages[0].content
