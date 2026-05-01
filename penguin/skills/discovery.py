"""Skill discovery across configured user and project paths."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple, Union

from penguin.skills.models import Skill, SkillDiagnostic
from penguin.skills.parser import SkillParseError, parse_skill_file

DEFAULT_USER_SCAN_PATHS = [
    "~/.penguin/skills",
    "~/.agents/skills",
    "~/.claude/skills",
]
DEFAULT_PROJECT_SCAN_PATHS = [
    ".penguin/skills",
    ".agents/skills",
]


def _config_get(config: Any, *keys: str, default: Any = None) -> Any:
    current = config
    for key in keys:
        if isinstance(current, dict):
            current = current.get(key, default)
        else:
            current = getattr(current, key, default)
        if current is default:
            return default
    return current


def get_skills_config(config: Any) -> Dict[str, Any]:
    """Return normalized skills configuration."""
    raw = _config_get(config, "skills", default={}) or {}
    if not isinstance(raw, dict):
        raw = {}
    return {
        "enabled": raw.get("enabled", True),
        "trust_project_skills": raw.get("trust_project_skills", False),
        "scan_paths": raw.get("scan_paths", {}) if isinstance(raw.get("scan_paths", {}), dict) else {},
        "max_scan_depth": int(raw.get("max_scan_depth", 6)),
        "max_skill_dirs": int(raw.get("max_skill_dirs", 2000)),
    }


def _expand_paths(paths: Iterable[str], *, root: Optional[Path] = None) -> List[Path]:
    expanded: List[Path] = []
    for raw_path in paths:
        path = Path(os.path.expandvars(str(raw_path))).expanduser()
        if not path.is_absolute() and root is not None:
            path = root / path
        expanded.append(path.resolve())
    return expanded


def configured_scan_roots(
    config: Any,
    *,
    project_root: Optional[Union[str, Path]] = None,
) -> List[Tuple[Path, str]]:
    """Resolve configured scan roots as `(path, source)` tuples."""
    skills_config = get_skills_config(config)
    scan_paths = skills_config["scan_paths"]
    project_base = Path(project_root or os.environ.get("PENGUIN_PROJECT_ROOT") or os.getcwd()).resolve()

    user_paths = scan_paths.get("user", DEFAULT_USER_SCAN_PATHS)
    project_paths = scan_paths.get("project", DEFAULT_PROJECT_SCAN_PATHS)

    roots: List[Tuple[Path, str]] = [(path, "user") for path in _expand_paths(user_paths)]
    if skills_config["trust_project_skills"]:
        roots.extend((path, "project") for path in _expand_paths(project_paths, root=project_base))
    return roots


def _depth_from_root(path: Path, root: Path) -> int:
    try:
        return len(path.relative_to(root).parts)
    except ValueError:
        return 999999


def discover_skills(
    config: Any,
    *,
    project_root: Optional[Union[str, Path]] = None,
) -> Tuple[List[Skill], List[SkillDiagnostic]]:
    """Discover valid skills and diagnostics from configured roots."""
    skills_config = get_skills_config(config)
    diagnostics: List[SkillDiagnostic] = []
    if not skills_config["enabled"]:
        return [], diagnostics

    max_depth = max(0, skills_config["max_scan_depth"])
    max_skill_dirs = max(1, skills_config["max_skill_dirs"])
    candidates: List[Tuple[Path, str]] = []

    for root, source in configured_scan_roots(config, project_root=project_root):
        if not root.exists():
            continue
        if not root.is_dir():
            diagnostics.append(
                SkillDiagnostic(
                    path=str(root),
                    severity="warning",
                    code="scan_root_not_directory",
                    message="Configured skill scan path is not a directory",
                    source=source,
                )
            )
            continue

        for skill_file in root.rglob("SKILL.md"):
            if _depth_from_root(skill_file.parent, root) > max_depth:
                diagnostics.append(
                    SkillDiagnostic(
                        path=str(skill_file),
                        severity="warning",
                        code="max_depth_exceeded",
                        message=f"Skill exceeds max_scan_depth={max_depth}",
                        source=source,
                    )
                )
                continue
            candidates.append((skill_file, source))
            if len(candidates) >= max_skill_dirs:
                diagnostics.append(
                    SkillDiagnostic(
                        path=str(root),
                        severity="warning",
                        code="max_skill_dirs_reached",
                        message=f"Stopped skill discovery after {max_skill_dirs} candidates",
                        source=source,
                    )
                )
                break

    valid: List[Skill] = []
    seen: Dict[str, Skill] = {}
    for skill_file, source in candidates:
        try:
            skill = parse_skill_file(skill_file, source=source)
        except SkillParseError as exc:
            diagnostics.append(
                SkillDiagnostic(
                    path=str(skill_file),
                    severity="error",
                    code="invalid_skill",
                    message=str(exc),
                    source=source,
                )
            )
            continue

        previous = seen.get(skill.name)
        if previous is not None:
            diagnostics.append(
                SkillDiagnostic(
                    path=str(skill.skill_file),
                    severity="warning",
                    code="duplicate_skill_name",
                    message=f"Duplicate skill name `{skill.name}` ignored; first match kept at {previous.skill_file}",
                    source=source,
                    skill_name=skill.name,
                )
            )
            continue
        seen[skill.name] = skill
        valid.append(skill)

    valid.sort(key=lambda item: item.name)
    return valid, diagnostics
