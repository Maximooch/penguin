"""Skill manager for discovery, catalog state, activation, and session dedupe."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from penguin.skills.discovery import discover_skills
from penguin.skills.models import Skill, SkillCatalogEntry, SkillDiagnostic
from penguin.skills.renderer import render_activation, render_catalog


class SkillManager:
    """Coordinates skill discovery and activation for a Penguin runtime."""

    def __init__(self, config: Any, *, project_root: Optional[Union[str, Path]] = None):
        self.config = config
        self.project_root = Path(project_root).resolve() if project_root is not None else None
        self._skills: Dict[str, Skill] = {}
        self._diagnostics: List[SkillDiagnostic] = []
        self._activated_by_session: Dict[str, set[str]] = {}
        self.refresh()

    def refresh(self) -> None:
        """Refresh discovered skills from disk."""
        skills, diagnostics = discover_skills(self.config, project_root=self.project_root)
        self._skills = {skill.name: skill for skill in skills}
        self._diagnostics = diagnostics

    @property
    def diagnostics(self) -> List[SkillDiagnostic]:
        return list(self._diagnostics)

    def catalog(self) -> List[SkillCatalogEntry]:
        """Return compact catalog entries sorted by name."""
        return [
            SkillCatalogEntry(
                name=skill.name,
                description=skill.description,
                source=skill.source,
                path=str(skill.path),
            )
            for skill in sorted(self._skills.values(), key=lambda item: item.name)
        ]

    def render_catalog_context(self) -> str:
        """Render compact catalog for startup/session CONTEXT loading."""
        return render_catalog(self.catalog())

    def get(self, name: str) -> Optional[Skill]:
        return self._skills.get(name)

    def list_payload(self) -> Dict[str, Any]:
        return {
            "skills": [entry.__dict__ for entry in self.catalog()],
            "diagnostics": [diagnostic.__dict__ for diagnostic in self.diagnostics],
        }

    def active_names(self, session_id: str = "default") -> List[str]:
        """Return activated skill names for a session."""
        return sorted(self._activated_by_session.get(session_id, set()))

    def is_active(self, name: str, session_id: str = "default") -> bool:
        """Check whether a skill is already active for a session."""
        return name in self._activated_by_session.get(session_id, set())

    def activate(
        self,
        name: str,
        *,
        session_id: str = "default",
        max_resources: int = 200,
    ) -> Dict[str, Any]:
        """Activate a skill for a session and return rendered content."""
        skill = self.get(name)
        if skill is None:
            return {
                "status": "not_found",
                "error": f"Skill not found: {name}",
                "available_skills": [entry.name for entry in self.catalog()],
            }

        activated = self._activated_by_session.setdefault(session_id, set())
        duplicate = name in activated
        if not duplicate:
            activated.add(name)

        return {
            "status": "already_active" if duplicate else "activated",
            "duplicate": duplicate,
            "skill": SkillCatalogEntry(
                name=skill.name,
                description=skill.description,
                source=skill.source,
                path=str(skill.path),
            ).__dict__,
            "content": render_activation(skill, max_resources=max_resources),
        }
