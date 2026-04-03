"""Blueprint Parser for Penguin.

Parses Blueprint documents (markdown, YAML, JSON) into structured BlueprintItem
and Blueprint objects for DAG-based task scheduling and ITUV lifecycle management.

Supports the Blueprint template format defined in context/blueprint.template.md.
"""

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

import yaml

from .models import Blueprint, BlueprintItem, DependencyPolicy, TaskDependency

logger = logging.getLogger(__name__)


class BlueprintParseError(Exception):
    """Raised when Blueprint parsing fails."""
    
    def __init__(
        self,
        message: str,
        source: Optional[str] = None,
        line: Optional[int] = None,
        code: Optional[str] = None,
        suggestion: Optional[str] = None,
        task_id: Optional[str] = None,
    ):
        self.source = source
        self.line = line
        self.code = code
        self.suggestion = suggestion
        self.task_id = task_id
        super().__init__(f"{message}" + (f" (at {source}:{line})" if source and line else ""))


@dataclass
class BlueprintDiagnostic:
    """Structured lint/diagnostic finding for a Blueprint."""

    code: str
    severity: str
    message: str
    source: Optional[str] = None
    line: Optional[int] = None
    task_id: Optional[str] = None
    suggestion: Optional[str] = None


@dataclass
class BlueprintDiagnosticsReport:
    """Structured diagnostics report for a Blueprint."""

    diagnostics: List[BlueprintDiagnostic] = field(default_factory=list)

    @property
    def has_errors(self) -> bool:
        """Return True when the report contains at least one error."""
        return any(diagnostic.severity == "error" for diagnostic in self.diagnostics)

    @property
    def has_warnings(self) -> bool:
        """Return True when the report contains at least one warning."""
        return any(diagnostic.severity == "warning" for diagnostic in self.diagnostics)


class BlueprintLinter:
    """Post-parse linter for Blueprint structural and authoring diagnostics."""

    def lint(
        self,
        blueprint: Blueprint,
        source: Optional[str] = None,
    ) -> BlueprintDiagnosticsReport:
        """Lint a parsed Blueprint and return structured diagnostics."""
        diagnostics: List[BlueprintDiagnostic] = []
        tasks_by_id: Dict[str, List[BlueprintItem]] = {}

        for item in blueprint.items:
            tasks_by_id.setdefault(item.id, []).append(item)

        # Errors: duplicate task IDs
        for task_id, items in tasks_by_id.items():
            if len(items) > 1:
                for item in items[1:]:
                    diagnostics.append(
                        BlueprintDiagnostic(
                            code="BP-LINT-001",
                            severity="error",
                            message=f"Duplicate task id {task_id}",
                            source=item.source_file or source,
                            line=item.source_line,
                            task_id=task_id,
                            suggestion="Use unique task identifiers within a Blueprint.",
                        )
                    )

        task_ids = set(tasks_by_id.keys())

        # Errors/warnings: per-task checks
        for item in blueprint.items:
            for dep_id in item.depends_on:
                if dep_id not in task_ids:
                    diagnostics.append(
                        BlueprintDiagnostic(
                            code="BP-LINT-002",
                            severity="error",
                            message=f"Task {item.id} depends on missing task {dep_id}",
                            source=item.source_file or source,
                            line=item.source_line,
                            task_id=item.id,
                            suggestion=f"Add task {dep_id} to the Blueprint or remove it from Depends.",
                        )
                    )

            if not item.acceptance_criteria:
                diagnostics.append(
                    BlueprintDiagnostic(
                        code="BP-LINT-101",
                        severity="warning",
                        message=f"Task {item.id} has no acceptance criteria",
                        source=item.source_file or source,
                        line=item.source_line,
                        task_id=item.id,
                        suggestion="Add at least one Acceptance bullet so VERIFY has something concrete to check.",
                    )
                )

            if item.estimate is None:
                diagnostics.append(
                    BlueprintDiagnostic(
                        code="BP-LINT-103",
                        severity="warning",
                        message=f"Task {item.id} is missing an estimate",
                        source=item.source_file or source,
                        line=item.source_line,
                        task_id=item.id,
                        suggestion="Add estimate metadata to improve scheduling quality.",
                    )
                )

            if any(spec.policy == DependencyPolicy.COMPLETION_REQUIRED for spec in item.dependency_specs):
                diagnostics.append(
                    BlueprintDiagnostic(
                        code="BP-LINT-102",
                        severity="warning",
                        message=f"Task {item.id} has redundant explicit completion_required dependency specs",
                        source=item.source_file or source,
                        line=item.source_line,
                        task_id=item.id,
                        suggestion="Remove explicit completion_required specs unless you need them for clarity.",
                    )
                )

        # Errors: cycle detection
        graph = {
            item.id: [dep_id for dep_id in item.depends_on if dep_id in task_ids]
            for item in blueprint.items
        }
        visited = set()
        visiting = set()
        cycle_path: List[str] = []

        def visit(node: str, stack: List[str]) -> bool:
            nonlocal cycle_path

            if node in visiting:
                start = stack.index(node)
                cycle_path = stack[start:] + [node]
                return True
            if node in visited:
                return False

            visiting.add(node)
            for dep in graph.get(node, []):
                if visit(dep, stack + [dep]):
                    return True
            visiting.remove(node)
            visited.add(node)
            return False

        for task_id in graph:
            if visit(task_id, [task_id]):
                diagnostics.append(
                    BlueprintDiagnostic(
                        code="BP-LINT-003",
                        severity="error",
                        message=f"Dependency cycle detected: {' -> '.join(cycle_path)}",
                        source=source,
                        task_id=task_id,
                        suggestion="Break the cycle so the scheduler can compute a valid frontier.",
                    )
                )
                break

        return BlueprintDiagnosticsReport(diagnostics=diagnostics)


class BlueprintParser:
    """Parses Blueprint documents from markdown, YAML, or JSON formats.
    
    The parser extracts:
    - Frontmatter metadata (YAML between --- delimiters)
    - Tasks with inline metadata {key=value, ...}
    - Acceptance criteria, dependencies, and recipe references
    - Usage recipes for the USE gate
    - Validation criteria for the VERIFY gate
    """
    
    # Regex patterns for parsing
    FRONTMATTER_PATTERN = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)
    TASK_LINE_PATTERN = re.compile(
        r"^(\s*)-\s*\[([x ])\]\s*<?([A-Z0-9_-]+(?:-\d+[A-Z]?)?)>?\s+(.+?)(?:\s*\{([^}]+)\})?\s*$",
        re.IGNORECASE
    )
    METADATA_KV_PATTERN = re.compile(r"(\w+)\s*=\s*([^,}]+)")
    ACCEPTANCE_PATTERN = re.compile(r"^\s*-\s*Acceptance:\s*(.+)$", re.IGNORECASE)
    DEPENDS_PATTERN = re.compile(r"^\s*-\s*Depends:\s*(.+)$", re.IGNORECASE)
    DEPENDS_HEADER_PATTERN = re.compile(r"^\s*-\s*Depends:\s*$", re.IGNORECASE)
    DEPENDENCY_SPECS_HEADER_PATTERN = re.compile(r"^\s*-\s*Dependency\s+Specs:\s*$", re.IGNORECASE)
    DEPENDENCY_SPEC_ITEM_PATTERN = re.compile(r"^\s*-\s*task_id:\s*(.+)$", re.IGNORECASE)
    KEY_VALUE_LINE_PATTERN = re.compile(r"^\s*([a-zA-Z_][a-zA-Z0-9_]*):\s*(.+)$")
    RECIPE_PATTERN = re.compile(r"^\s*-\s*Recipe:\s*(.+)$", re.IGNORECASE)
    DESCRIPTION_PATTERN = re.compile(r"^\s*-\s*Description:\s*(.+)$", re.IGNORECASE)
    SECTION_PATTERN = re.compile(r"^##\s+(.+)$", re.MULTILINE)
    LIST_ITEM_PATTERN = re.compile(r"^\s*-\s+(.+)$")
    
    def __init__(self, base_path: Optional[Path] = None):
        """Initialize the parser.
        
        Args:
            base_path: Base path for resolving relative file references.
        """
        self.base_path = base_path or Path.cwd()
    
    def parse_file(self, file_path: Union[str, Path]) -> Blueprint:
        """Parse a Blueprint from a file.
        
        Args:
            file_path: Path to the Blueprint file (markdown, yaml, or json).
            
        Returns:
            Parsed Blueprint object.
            
        Raises:
            BlueprintParseError: If parsing fails.
        """
        path = Path(file_path)
        if not path.exists():
            raise BlueprintParseError(f"File not found: {path}")
        
        content = path.read_text(encoding="utf-8")
        suffix = path.suffix.lower()
        
        if suffix in (".yaml", ".yml"):
            return self.parse_yaml(content, source=str(path))
        elif suffix == ".json":
            return self.parse_json(content, source=str(path))
        elif suffix in (".md", ".markdown"):
            return self.parse_markdown(content, source=str(path))
        else:
            # Try markdown as default
            return self.parse_markdown(content, source=str(path))
    
    def parse_markdown(self, content: str, source: Optional[str] = None) -> Blueprint:
        """Parse a Blueprint from markdown content.
        
        Args:
            content: Markdown content with optional YAML frontmatter.
            source: Optional source file path for error messages.
            
        Returns:
            Parsed Blueprint object.
        """
        # Extract frontmatter
        frontmatter = {}
        body = content
        
        fm_match = self.FRONTMATTER_PATTERN.match(content)
        if fm_match:
            try:
                frontmatter = yaml.safe_load(fm_match.group(1)) or {}
            except yaml.YAMLError as e:
                raise BlueprintParseError(f"Invalid YAML frontmatter: {e}", source)
            body = content[fm_match.end():]
        
        # Parse metadata from frontmatter
        blueprint = self._build_blueprint_from_frontmatter(frontmatter, source)
        
        # Parse sections
        sections = self._parse_sections(body)
        
        # Extract content from sections
        if "Overview" in sections:
            blueprint.overview = sections["Overview"].strip()
        
        if "Goals" in sections:
            blueprint.goals = self._parse_list_items(sections["Goals"])
        
        if "Non-Goals" in sections:
            blueprint.non_goals = self._parse_list_items(sections["Non-Goals"])
        
        if "Context" in sections:
            blueprint.context = self._parse_context_section(sections["Context"])
        
        # Parse tasks
        if "Tasks" in sections:
            blueprint.items = self._parse_tasks_section(sections["Tasks"], source)
        
        # Parse usage recipes
        if "Usage Recipes" in sections:
            blueprint.recipes = self._parse_recipes_section(sections["Usage Recipes"])
        
        # Parse validation
        if "Validation" in sections:
            blueprint.validation = self._parse_validation_section(sections["Validation"])
        
        # Parse risks/questions
        if "Risks / Open Questions" in sections:
            risks, questions = self._parse_risks_section(sections["Risks / Open Questions"])
            blueprint.risks = risks
            blueprint.questions = questions
        
        return blueprint
    
    def parse_yaml(self, content: str, source: Optional[str] = None) -> Blueprint:
        """Parse a Blueprint from YAML content.
        
        Args:
            content: YAML content.
            source: Optional source file path for error messages.
            
        Returns:
            Parsed Blueprint object.
        """
        try:
            data = yaml.safe_load(content)
        except yaml.YAMLError as e:
            raise BlueprintParseError(f"Invalid YAML: {e}", source)
        
        return self._build_blueprint_from_dict(data, source)
    
    def parse_json(self, content: str, source: Optional[str] = None) -> Blueprint:
        """Parse a Blueprint from JSON content.
        
        Args:
            content: JSON content.
            source: Optional source file path for error messages.
            
        Returns:
            Parsed Blueprint object.
        """
        try:
            data = json.loads(content)
        except json.JSONDecodeError as e:
            raise BlueprintParseError(f"Invalid JSON: {e}", source)
        
        return self._build_blueprint_from_dict(data, source)

    def lint_blueprint(
        self,
        blueprint: Blueprint,
        source: Optional[str] = None,
    ) -> BlueprintDiagnosticsReport:
        """Run post-parse lint checks against a Blueprint."""
        return BlueprintLinter().lint(blueprint, source=source)
    
    def _build_blueprint_from_frontmatter(
        self, fm: Dict[str, Any], source: Optional[str]
    ) -> Blueprint:
        """Build a Blueprint object from frontmatter data."""
        # Extract ITUV settings
        ituv = fm.get("ituv", {})
        agent_defaults = fm.get("agent_defaults", {})
        
        return Blueprint(
            title=fm.get("title", "Untitled Blueprint"),
            project_key=fm.get("project_key", "UNKNOWN"),
            version=fm.get("version", "0.1.0"),
            status=fm.get("status", "draft"),
            owners=fm.get("owners", []),
            labels=fm.get("labels", []),
            repo=fm.get("repo"),
            path=fm.get("path") or source,
            links=fm.get("links", []),
            created=fm.get("created"),
            updated=fm.get("updated"),
            ituv_enabled=ituv.get("enabled", True),
            phase_timebox_sec=ituv.get("phase_timebox_sec", {
                "implement": 600,
                "test": 300,
                "use": 180,
                "verify": 120
            }),
            default_agent_role=agent_defaults.get("agent_role", "implementer"),
            default_required_tools=agent_defaults.get("required_tools", []),
            default_skills=agent_defaults.get("skills", []),
        )
    
    def _build_blueprint_from_dict(
        self, data: Dict[str, Any], source: Optional[str]
    ) -> Blueprint:
        """Build a Blueprint from a dictionary (YAML/JSON)."""
        # Handle items/tasks
        items = []
        for item_data in data.get("items", data.get("tasks", [])):
            items.append(self._build_item_from_dict(item_data, source))
        
        ituv = data.get("ituv", {})
        agent_defaults = data.get("agent_defaults", {})
        
        return Blueprint(
            title=data.get("title", "Untitled Blueprint"),
            project_key=data.get("project_key", "UNKNOWN"),
            version=data.get("version", "0.1.0"),
            status=data.get("status", "draft"),
            owners=data.get("owners", []),
            labels=data.get("labels", []),
            repo=data.get("repo"),
            path=data.get("path") or source,
            links=data.get("links", []),
            created=data.get("created"),
            updated=data.get("updated"),
            ituv_enabled=ituv.get("enabled", True),
            phase_timebox_sec=ituv.get("phase_timebox_sec", {
                "implement": 600,
                "test": 300,
                "use": 180,
                "verify": 120
            }),
            default_agent_role=agent_defaults.get("agent_role", "implementer"),
            default_required_tools=agent_defaults.get("required_tools", []),
            default_skills=agent_defaults.get("skills", []),
            overview=data.get("overview", ""),
            goals=data.get("goals", []),
            non_goals=data.get("non_goals", []),
            context=data.get("context", {}),
            items=items,
            recipes=data.get("recipes", []),
            validation=data.get("validation", []),
            risks=data.get("risks", []),
            questions=data.get("questions", []),
        )
    
    def _build_item_from_dict(
        self, data: Dict[str, Any], source: Optional[str]
    ) -> BlueprintItem:
        """Build a BlueprintItem from a dictionary."""
        return BlueprintItem(
            id=data.get("id", ""),
            title=data.get("title", ""),
            description=data.get("description", ""),
            acceptance_criteria=data.get("acceptance_criteria", []),
            depends_on=data.get("depends_on", data.get("dependencies", [])),
            dependency_specs=data.get("dependency_specs", []),
            recipe=data.get("recipe"),
            estimate=data.get("estimate"),
            priority=data.get("priority", "medium"),
            labels=data.get("labels", []),
            assignees=data.get("assignees", []),
            due_date=data.get("due_date", data.get("due")),
            effort=data.get("effort"),
            value=data.get("value"),
            risk=data.get("risk"),
            sequence=data.get("sequence"),
            agent_role=data.get("agent_role"),
            required_tools=data.get("required_tools", []),
            skills=data.get("skills", []),
            parallelizable=data.get("parallelizable", False),
            batch=data.get("batch"),
            parent_id=data.get("parent_id"),
            source_file=source,
        )
    
    def _parse_sections(self, content: str) -> Dict[str, str]:
        """Parse markdown content into sections by ## headings."""
        sections = {}
        current_section = None
        current_content = []
        
        for line in content.split("\n"):
            match = self.SECTION_PATTERN.match(line)
            if match:
                # Save previous section
                if current_section:
                    sections[current_section] = "\n".join(current_content)
                current_section = match.group(1).strip()
                current_content = []
            elif current_section:
                current_content.append(line)
        
        # Save last section
        if current_section:
            sections[current_section] = "\n".join(current_content)
        
        return sections
    
    def _parse_list_items(self, content: str) -> List[str]:
        """Parse a section into a list of items."""
        items = []
        for line in content.split("\n"):
            match = self.LIST_ITEM_PATTERN.match(line)
            if match:
                item = match.group(1).strip()
                if item:
                    items.append(item)
        return items
    
    def _parse_context_section(self, content: str) -> Dict[str, str]:
        """Parse the Context section into key-value pairs."""
        context = {}
        for line in content.split("\n"):
            match = self.LIST_ITEM_PATTERN.match(line)
            if match:
                item = match.group(1).strip()
                if ":" in item:
                    key, value = item.split(":", 1)
                    context[key.strip()] = value.strip()
        return context
    
    def _parse_tasks_section(
        self, content: str, source: Optional[str]
    ) -> List[BlueprintItem]:
        """Parse the Tasks section into BlueprintItems."""
        items = []
        lines = content.split("\n")
        current_item: Optional[BlueprintItem] = None
        parent_stack: List[Tuple[int, BlueprintItem]] = []  # (indent, item)
        active_subsection: Optional[str] = None
        subsection_indent: Optional[int] = None
        current_dependency_spec: Optional[Dict[str, str]] = None
        current_dependency_spec_line: Optional[int] = None

        def finalize_dependency_spec() -> None:
            nonlocal current_dependency_spec, current_dependency_spec_line

            if not current_item or not current_dependency_spec:
                current_dependency_spec = None
                current_dependency_spec_line = None
                return

            task_id = current_dependency_spec.get("task_id", "").strip().strip("<>")
            policy = current_dependency_spec.get("policy", "").strip()
            artifact_key = current_dependency_spec.get("artifact_key")

            if not task_id:
                raise BlueprintParseError(
                    "Dependency spec requires task_id",
                    source,
                    current_dependency_spec_line,
                    code="BP-PARSE-007",
                    suggestion="Add task_id under Dependency Specs.",
                )

            if not policy:
                raise BlueprintParseError(
                    f"Dependency spec for {task_id} requires policy",
                    source,
                    current_dependency_spec_line,
                    code="BP-PARSE-007",
                    suggestion=f"Add policy under Dependency Specs for task_id <{task_id}>.",
                    task_id=task_id,
                )

            valid_policies = {dependency_policy.value for dependency_policy in DependencyPolicy}
            if policy not in valid_policies:
                raise BlueprintParseError(
                    f"Unknown dependency policy '{policy}'",
                    source,
                    current_dependency_spec_line,
                    code="BP-PARSE-003",
                    suggestion="Use one of: completion_required, review_ready_ok, artifact_ready.",
                    task_id=task_id,
                )

            if policy == DependencyPolicy.ARTIFACT_READY.value and not artifact_key:
                raise BlueprintParseError(
                    f"artifact_ready dependency for {task_id} requires artifact_key",
                    source,
                    current_dependency_spec_line,
                    code="BP-PARSE-004",
                    suggestion=f"Add artifact_key under Dependency Specs for task_id <{task_id}>.",
                    task_id=task_id,
                )

            if task_id not in current_item.depends_on:
                raise BlueprintParseError(
                    f"Dependency spec task_id {task_id} must also appear in Depends",
                    source,
                    current_dependency_spec_line,
                    code="BP-PARSE-005",
                    suggestion=f"Add <{task_id}> under Depends for this task.",
                    task_id=task_id,
                )

            for existing in current_item.dependency_specs:
                existing_task_id = str(existing.task_id).strip().strip("<>")
                if existing_task_id != task_id:
                    continue
                if (
                    existing.policy.value != policy
                    or existing.artifact_key != artifact_key
                ):
                    raise BlueprintParseError(
                        f"conflicting dependency spec for task_id {task_id}",
                        source,
                        current_dependency_spec_line,
                        code="BP-PARSE-006",
                        suggestion=f"Keep only one dependency spec for task_id <{task_id}>.",
                        task_id=task_id,
                    )
                current_dependency_spec = None
                current_dependency_spec_line = None
                return

            spec = TaskDependency(
                task_id=task_id,
                policy=policy,
                artifact_key=artifact_key.strip().strip("\"'") if artifact_key else None,
            )
            current_item.dependency_specs.append(spec)
            current_dependency_spec = None
            current_dependency_spec_line = None

        def reset_subsection_state() -> None:
            nonlocal active_subsection, subsection_indent

            finalize_dependency_spec()
            active_subsection = None
            subsection_indent = None

        for line_num, line in enumerate(lines, start=1):
            # Skip comments and empty lines
            if line.strip().startswith("<!--") or not line.strip():
                continue
            if line.strip().startswith("-->"):
                continue
            if line.strip().startswith("<!--"):
                continue

            task_match = self.TASK_LINE_PATTERN.match(line)
            if task_match:
                reset_subsection_state()
                indent = len(task_match.group(1))
                ident = task_match.group(3)
                title = task_match.group(4).strip()
                metadata_str = task_match.group(5)

                metadata = self._parse_inline_metadata(metadata_str) if metadata_str else {}

                parent_id = None
                while parent_stack and parent_stack[-1][0] >= indent:
                    parent_stack.pop()
                if parent_stack:
                    parent_id = parent_stack[-1][1].id

                item = BlueprintItem(
                    id=metadata.get("id", ident),
                    title=title,
                    description=metadata.get("description", ""),
                    priority=metadata.get("priority", "medium"),
                    labels=self._parse_csv(metadata.get("labels", "")),
                    assignees=self._parse_csv(metadata.get("assignees", "")),
                    due_date=metadata.get("due"),
                    estimate=self._parse_int(metadata.get("estimate")),
                    effort=self._parse_int(metadata.get("effort")),
                    value=self._parse_int(metadata.get("value")),
                    risk=self._parse_int(metadata.get("risk")),
                    sequence=metadata.get("sequence"),
                    agent_role=metadata.get("agent_role"),
                    required_tools=self._parse_csv(metadata.get("required_tools", "")),
                    skills=self._parse_csv(metadata.get("skills", "")),
                    parallelizable=metadata.get("parallelizable", "").lower() == "true",
                    batch=metadata.get("batch"),
                    parent_id=parent_id,
                    source_file=source,
                    source_line=line_num,
                )

                items.append(item)
                current_item = item
                parent_stack.append((indent, item))
                continue

            if current_item:
                current_indent = len(line) - len(line.lstrip(" "))

                if active_subsection and subsection_indent is not None and current_indent <= subsection_indent:
                    reset_subsection_state()

                if active_subsection == "depends":
                    list_match = self.LIST_ITEM_PATTERN.match(line)
                    if list_match:
                        dep = list_match.group(1).strip().strip("<>")
                        if dep and dep not in current_item.depends_on:
                            current_item.depends_on.append(dep)
                        continue

                if active_subsection == "dependency_specs":
                    spec_item_match = self.DEPENDENCY_SPEC_ITEM_PATTERN.match(line)
                    if spec_item_match:
                        finalize_dependency_spec()
                        current_dependency_spec = {
                            "task_id": spec_item_match.group(1).strip(),
                        }
                        current_dependency_spec_line = line_num
                        continue

                    kv_match = self.KEY_VALUE_LINE_PATTERN.match(line)
                    if kv_match and current_dependency_spec is not None:
                        key = kv_match.group(1).strip()
                        value = kv_match.group(2).strip().strip("\"'")
                        current_dependency_spec[key] = value
                        continue

                acc_match = self.ACCEPTANCE_PATTERN.match(line)
                if acc_match:
                    reset_subsection_state()
                    current_item.acceptance_criteria.append(acc_match.group(1).strip())
                    continue

                dep_match = self.DEPENDS_PATTERN.match(line)
                if dep_match:
                    reset_subsection_state()
                    deps = [d.strip().strip("<>") for d in dep_match.group(1).split(",")]
                    current_item.depends_on.extend([dep for dep in deps if dep])
                    continue

                dep_header_match = self.DEPENDS_HEADER_PATTERN.match(line)
                if dep_header_match:
                    reset_subsection_state()
                    active_subsection = "depends"
                    subsection_indent = current_indent
                    continue

                dep_specs_header_match = self.DEPENDENCY_SPECS_HEADER_PATTERN.match(line)
                if dep_specs_header_match:
                    reset_subsection_state()
                    active_subsection = "dependency_specs"
                    subsection_indent = current_indent
                    continue

                recipe_match = self.RECIPE_PATTERN.match(line)
                if recipe_match:
                    reset_subsection_state()
                    current_item.recipe = recipe_match.group(1).strip()
                    continue

                desc_match = self.DESCRIPTION_PATTERN.match(line)
                if desc_match:
                    reset_subsection_state()
                    current_item.description = desc_match.group(1).strip()
                    continue

        reset_subsection_state()
        return items

    def _parse_inline_metadata(self, metadata_str: str) -> Dict[str, str]:
        """Parse inline metadata from {key=value, ...} format."""
        metadata = {}
        for match in self.METADATA_KV_PATTERN.finditer(metadata_str):
            key = match.group(1).strip()
            value = match.group(2).strip()
            metadata[key] = value
        return metadata
    
    def _parse_csv(self, value: str) -> List[str]:
        """Parse a comma-separated value into a list."""
        if not value:
            return []
        return [v.strip() for v in value.split(",") if v.strip()]
    
    def _parse_int(self, value: Optional[str]) -> Optional[int]:
        """Parse a string to int, returning None if invalid."""
        if value is None:
            return None
        try:
            return int(value)
        except ValueError:
            return None
    
    def _parse_recipes_section(self, content: str) -> List[Dict[str, Any]]:
        """Parse the Usage Recipes section.
        
        This is a simplified parser that extracts recipe blocks.
        For full YAML recipe parsing, use parse_yaml on the section.
        """
        recipes = []
        current_recipe: Optional[Dict[str, Any]] = None
        
        lines = content.split("\n")
        for line in lines:
            # Skip comments
            if line.strip().startswith("<!--") or line.strip().startswith("-->"):
                continue
            
            # Check for recipe start
            if line.strip().startswith("- recipe:"):
                if current_recipe:
                    recipes.append(current_recipe)
                name_match = re.search(r'recipe:\s*["\']?([^"\']+)["\']?', line)
                current_recipe = {
                    "name": name_match.group(1) if name_match else "unnamed",
                    "steps": [],
                }
            elif current_recipe and line.strip().startswith("description:"):
                desc_match = re.search(r'description:\s*["\']?([^"\']+)["\']?', line)
                if desc_match:
                    current_recipe["description"] = desc_match.group(1)
            elif current_recipe and line.strip().startswith("- shell:"):
                step_match = re.search(r'shell:\s*["\']?([^"\']+)["\']?', line)
                if step_match:
                    current_recipe["steps"].append({"shell": step_match.group(1)})
            elif current_recipe and line.strip().startswith("- http:"):
                step_match = re.search(r'http:\s*["\']?([^"\']+)["\']?', line)
                if step_match:
                    current_recipe["steps"].append({"http": step_match.group(1)})
            elif current_recipe and line.strip().startswith("- python:"):
                step_match = re.search(r'python:\s*["\']?([^"\']+)["\']?', line)
                if step_match:
                    current_recipe["steps"].append({"python": step_match.group(1)})
        
        if current_recipe:
            recipes.append(current_recipe)
        
        return recipes
    
    def _parse_validation_section(self, content: str) -> List[str]:
        """Parse the Validation section into criteria."""
        criteria = []
        for line in content.split("\n"):
            # Match checkbox items
            match = re.match(r"^\s*-\s*\[[ x]\]\s*(.+)$", line, re.IGNORECASE)
            if match:
                criteria.append(match.group(1).strip())
        return criteria
    
    def _parse_risks_section(self, content: str) -> Tuple[List[str], List[str]]:
        """Parse the Risks / Open Questions section."""
        risks = []
        questions = []
        
        for line in content.split("\n"):
            match = self.LIST_ITEM_PATTERN.match(line)
            if match:
                item = match.group(1).strip()
                if item.lower().startswith("risk:"):
                    risks.append(item[5:].strip())
                elif item.lower().startswith("question:"):
                    questions.append(item[9:].strip())
        
        return risks, questions


# Convenience functions

def parse_blueprint(
    source: Union[str, Path],
    base_path: Optional[Path] = None
) -> Blueprint:
    """Parse a Blueprint from a file path.
    
    Args:
        source: Path to the Blueprint file.
        base_path: Optional base path for resolving references.
        
    Returns:
        Parsed Blueprint object.
    """
    parser = BlueprintParser(base_path)
    return parser.parse_file(source)


def parse_blueprint_content(
    content: str,
    format: str = "markdown",
    source: Optional[str] = None
) -> Blueprint:
    """Parse a Blueprint from content string.
    
    Args:
        content: Blueprint content.
        format: Content format ("markdown", "yaml", or "json").
        source: Optional source identifier for error messages.
        
    Returns:
        Parsed Blueprint object.
    """
    parser = BlueprintParser()
    
    if format == "yaml":
        return parser.parse_yaml(content, source)
    elif format == "json":
        return parser.parse_json(content, source)
    else:
        return parser.parse_markdown(content, source)

