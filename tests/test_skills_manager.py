from pathlib import Path

from penguin.skills.manager import SkillManager


def make_skill(path: Path, name: str) -> None:
    path.mkdir(parents=True, exist_ok=True)
    (path / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: Desc for {name}\n---\n# {name}\nInstructions.\n",
        encoding="utf-8",
    )
    (path / "references" / "guide.md").parent.mkdir(parents=True, exist_ok=True)
    (path / "references" / "guide.md").write_text("Guide", encoding="utf-8")


def test_manager_catalog_and_activation_dedupe(tmp_path: Path) -> None:
    make_skill(tmp_path / "skills" / "demo", "demo-skill")
    manager = SkillManager({"skills": {"scan_paths": {"user": [str(tmp_path / "skills")]}}})

    catalog = manager.catalog()
    first = manager.activate("demo-skill", session_id="s1")
    second = manager.activate("demo-skill", session_id="s1")

    assert catalog[0].name == "demo-skill"
    assert first["status"] == "activated"
    assert first["duplicate"] is False
    assert '<skill_content name="demo-skill"' in first["content"]
    assert "<skill_resources" in first["content"]
    assert second["status"] == "already_active"
    assert second["duplicate"] is True


def test_manager_dedupe_is_per_session(tmp_path: Path) -> None:
    make_skill(tmp_path / "skills" / "demo", "demo-skill")
    manager = SkillManager({"skills": {"scan_paths": {"user": [str(tmp_path / "skills")]}}})

    manager.activate("demo-skill", session_id="s1")
    other_session = manager.activate("demo-skill", session_id="s2")

    assert other_session["status"] == "activated"
