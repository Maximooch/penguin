"""Parser and validation for Agent Skills `SKILL.md` files."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, Tuple, Union

import yaml

from penguin.skills.models import Skill


class SkillParseError(ValueError):
    """Raised when a SKILL.md file is malformed or invalid."""


_NAME_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?$")
_MAX_DESCRIPTION_CHARS = 1024
_OPTIONAL_LIST_FIELDS = ("allowed-tools", "allowed_tools")


def split_frontmatter(text: str) -> Tuple[Dict[str, Any], str]:
    """Split YAML frontmatter from markdown body."""
    if not text.startswith("---\n") and text != "---":
        raise SkillParseError("SKILL.md must start with YAML frontmatter")

    end = text.find("\n---", 4)
    if end == -1:
        raise SkillParseError("SKILL.md frontmatter is missing a closing delimiter")

    raw_frontmatter = text[4:end]
    body_start = end + len("\n---")
    if body_start < len(text) and text[body_start] == "\n":
        body_start += 1

    try:
        frontmatter = yaml.safe_load(raw_frontmatter) or {}
    except yaml.YAMLError as exc:
        raise SkillParseError(f"Invalid YAML frontmatter: {exc}") from exc

    if not isinstance(frontmatter, dict):
        raise SkillParseError("SKILL.md frontmatter must be a mapping")

    return frontmatter, text[body_start:]


def _validate_name(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SkillParseError("Skill frontmatter requires a non-empty string `name`")
    name = value.strip()
    if not _NAME_RE.match(name):
        raise SkillParseError(
            "Skill `name` must be lowercase kebab-case, 1-64 chars, using a-z, 0-9, and hyphen"
        )
    return name


def _validate_description(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SkillParseError("Skill frontmatter requires a non-empty string `description`")
    description = " ".join(value.strip().split())
    if len(description) > _MAX_DESCRIPTION_CHARS:
        raise SkillParseError(
            f"Skill `description` must be <= {_MAX_DESCRIPTION_CHARS} characters"
        )
    return description


def _validate_allowed_tools(frontmatter: Dict[str, Any]) -> list[str]:
    tools_value = None
    for field_name in _OPTIONAL_LIST_FIELDS:
        if field_name in frontmatter:
            tools_value = frontmatter[field_name]
            break

    if tools_value is None:
        return []
    if not isinstance(tools_value, list) or not all(
        isinstance(item, str) and item.strip() for item in tools_value
    ):
        raise SkillParseError("Skill `allowed-tools` must be a list of non-empty strings")
    return [item.strip() for item in tools_value]


def parse_skill_file(path: Union[str, Path], *, source: str = "project") -> Skill:
    """Parse and validate a SKILL.md file."""
    skill_file = Path(path).expanduser().resolve()
    if skill_file.name != "SKILL.md":
        raise SkillParseError("Skill file must be named SKILL.md")
    if not skill_file.exists() or not skill_file.is_file():
        raise SkillParseError(f"Skill file not found: {skill_file}")

    text = skill_file.read_text(encoding="utf-8")
    frontmatter, body = split_frontmatter(text)
    name = _validate_name(frontmatter.get("name"))
    description = _validate_description(frontmatter.get("description"))
    allowed_tools = _validate_allowed_tools(frontmatter)

    return Skill(
        name=name,
        description=description,
        path=skill_file.parent,
        skill_file=skill_file,
        body=body.strip(),
        frontmatter=frontmatter,
        allowed_tools=allowed_tools,
        source=source,
    )
