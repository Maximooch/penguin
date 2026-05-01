"""Rendering helpers for skills catalog and activation payloads."""

from __future__ import annotations

from typing import Iterable, List

from penguin.skills.models import Skill, SkillCatalogEntry


_RESOURCE_IGNORE_DIRS = {".git", "__pycache__", "node_modules", ".venv", "venv"}


def render_catalog(entries: Iterable[SkillCatalogEntry]) -> str:
    """Render compact skill catalog for CONTEXT injection."""
    entries = list(entries)
    if not entries:
        return ""

    lines = [
        "# Available Agent Skills",
        "",
        "Skills are optional task-specific instructions. Use `activate_skill` to load full skill instructions when relevant.",
        "",
    ]
    for entry in entries:
        lines.append(f"- `{entry.name}` ({entry.source}): {entry.description}")
    return "\n".join(lines)


def list_skill_resources(skill: Skill, *, max_resources: int = 200) -> List[str]:
    """List non-SKILL.md files under a skill directory."""
    resources: List[str] = []
    root = skill.path
    for path in sorted(root.rglob("*")):
        if path.is_dir():
            continue
        rel = path.relative_to(root)
        if rel.name == "SKILL.md" or any(part in _RESOURCE_IGNORE_DIRS for part in rel.parts):
            continue
        resources.append(str(rel))
        if len(resources) >= max_resources:
            break
    return resources


def render_activation(skill: Skill, *, max_resources: int = 200) -> str:
    """Render an activated skill in structured XML-like wrappers."""
    resources = list_skill_resources(skill, max_resources=max_resources)
    lines = [
        f'<skill_content name="{skill.name}" source="{skill.source}" path="{skill.path}">',
        skill.body,
        "</skill_content>",
    ]
    if resources:
        lines.extend([
            f'<skill_resources name="{skill.name}">',
            *[f"- {resource}" for resource in resources],
            "</skill_resources>",
        ])
    return "\n".join(lines).strip()
