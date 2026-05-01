"""Data models for Agent Skills integration."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass(frozen=True)
class Skill:
    """A parsed skill directory containing a valid SKILL.md file."""

    name: str
    description: str
    path: Path
    skill_file: Path
    body: str
    frontmatter: Dict[str, Any] = field(default_factory=dict)
    allowed_tools: List[str] = field(default_factory=list)
    source: str = "project"


@dataclass(frozen=True)
class SkillCatalogEntry:
    """Compact skill information safe to disclose at startup."""

    name: str
    description: str
    source: str
    path: str


@dataclass(frozen=True)
class SkillDiagnostic:
    """Discovery or validation diagnostic for a candidate skill."""

    path: str
    severity: str
    code: str
    message: str
    source: str = "unknown"
    skill_name: Optional[str] = None
