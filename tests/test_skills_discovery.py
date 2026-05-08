from pathlib import Path

from penguin.skills.discovery import discover_skills


def make_skill(path: Path, name: str, description: str = "Desc") -> None:
    path.mkdir(parents=True, exist_ok=True)
    (path / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: {description}\n---\nBody for {name}\n",
        encoding="utf-8",
    )


def test_discover_nested_skills(tmp_path: Path) -> None:
    make_skill(tmp_path / "user" / "nested" / "skill", "nested-skill")
    config = {
        "skills": {
            "include_bundled": False,
            "scan_paths": {"user": [str(tmp_path / "user")]},
        }
    }

    skills, diagnostics = discover_skills(config)

    assert [skill.name for skill in skills] == ["nested-skill"]
    assert diagnostics == []


def test_discover_includes_bundled_browser_skill_by_default() -> None:
    skills, diagnostics = discover_skills({"skills": {"scan_paths": {"user": []}}})

    browser = next(skill for skill in skills if skill.name == "browser")
    assert browser.source == "bundled"
    assert (browser.path / "interaction-skills" / "screenshots.md").is_file()
    assert (browser.path / "domain-skills" / "README.md").is_file()
    assert diagnostics == []


def test_discover_invalid_skill_reports_diagnostic(tmp_path: Path) -> None:
    bad = tmp_path / "user" / "bad"
    bad.mkdir(parents=True)
    (bad / "SKILL.md").write_text("---\nname: Bad\n---\nBody\n", encoding="utf-8")
    config = {
        "skills": {
            "include_bundled": False,
            "scan_paths": {"user": [str(tmp_path / "user")]},
        }
    }

    skills, diagnostics = discover_skills(config)

    assert skills == []
    assert diagnostics[0].code == "invalid_skill"


def test_discover_collisions_keep_first(tmp_path: Path) -> None:
    make_skill(tmp_path / "a", "same-name", "First")
    make_skill(tmp_path / "b", "same-name", "Second")
    config = {
        "skills": {
            "include_bundled": False,
            "scan_paths": {"user": [str(tmp_path / "a"), str(tmp_path / "b")]},
        }
    }

    skills, diagnostics = discover_skills(config)

    assert len(skills) == 1
    assert skills[0].description == "First"
    assert any(diagnostic.code == "duplicate_skill_name" for diagnostic in diagnostics)


def test_discover_max_depth(tmp_path: Path) -> None:
    make_skill(tmp_path / "root" / "one" / "two", "too-deep")
    config = {
        "skills": {
            "include_bundled": False,
            "scan_paths": {"user": [str(tmp_path / "root")]},
            "max_scan_depth": 1,
        }
    }

    skills, diagnostics = discover_skills(config)

    assert skills == []
    assert diagnostics[0].code == "max_depth_exceeded"


def test_project_skills_ignored_when_not_trusted(tmp_path: Path) -> None:
    make_skill(tmp_path / ".penguin" / "skills" / "project", "project-skill")
    config = {
        "skills": {
            "include_bundled": False,
            "trust_project_skills": False,
            "scan_paths": {"user": [], "project": [".penguin/skills"]},
        }
    }

    skills, diagnostics = discover_skills(config, project_root=tmp_path)

    assert skills == []
    assert diagnostics == []


def test_project_skills_loaded_when_trusted(tmp_path: Path) -> None:
    make_skill(tmp_path / ".penguin" / "skills" / "project", "project-skill")
    config = {
        "skills": {
            "include_bundled": False,
            "trust_project_skills": True,
            "scan_paths": {"user": [], "project": [".penguin/skills"]},
        }
    }

    skills, _ = discover_skills(config, project_root=tmp_path)

    assert [skill.name for skill in skills] == ["project-skill"]
