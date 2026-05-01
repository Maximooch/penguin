from pathlib import Path

import pytest

from penguin.skills.parser import SkillParseError, parse_skill_file


def write_skill(root: Path, content: str) -> Path:
    path = root / "SKILL.md"
    path.write_text(content, encoding="utf-8")
    return path


def test_parse_valid_skill(tmp_path: Path) -> None:
    path = write_skill(
        tmp_path,
        "---\nname: demo-skill\ndescription: Demo skill.\n---\n# Body\nDo work.\n",
    )

    skill = parse_skill_file(path)

    assert skill.name == "demo-skill"
    assert skill.description == "Demo skill."
    assert skill.body == "# Body\nDo work."


@pytest.mark.parametrize(
    "frontmatter",
    [
        "description: Missing name",
        "name: missing-description",
    ],
)
def test_parse_missing_required_fields(tmp_path: Path, frontmatter: str) -> None:
    path = write_skill(tmp_path, f"---\n{frontmatter}\n---\nBody\n")

    with pytest.raises(SkillParseError):
        parse_skill_file(path)


@pytest.mark.parametrize("name", ["BadName", "bad_name", "-bad", "bad-", "bad skill"])
def test_parse_invalid_names(tmp_path: Path, name: str) -> None:
    path = write_skill(tmp_path, f"---\nname: {name}\ndescription: Desc\n---\nBody\n")

    with pytest.raises(SkillParseError):
        parse_skill_file(path)


def test_parse_long_description(tmp_path: Path) -> None:
    path = write_skill(
        tmp_path,
        f"---\nname: long-desc\ndescription: {'x' * 1025}\n---\nBody\n",
    )

    with pytest.raises(SkillParseError):
        parse_skill_file(path)


def test_parse_malformed_yaml(tmp_path: Path) -> None:
    path = write_skill(tmp_path, "---\nname: [broken\ndescription: Desc\n---\nBody\n")

    with pytest.raises(SkillParseError):
        parse_skill_file(path)


def test_parse_optional_fields(tmp_path: Path) -> None:
    path = write_skill(
        tmp_path,
        "---\nname: optional-fields\ndescription: Has optional fields.\nallowed-tools:\n  - read_file\n  - grep_search\nmetadata:\n  owner: test\n---\nBody\n",
    )

    skill = parse_skill_file(path)

    assert skill.allowed_tools == ["read_file", "grep_search"]
    assert skill.frontmatter["metadata"]["owner"] == "test"
