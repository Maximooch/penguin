"""Blueprint Parser for Penguin.

Parses Blueprint documents (markdown, YAML, JSON) into structured BlueprintItem
and Blueprint objects for DAG-based task scheduling and ITUV lifecycle management.

Supports the Blueprint template format defined in context/blueprint.template.md.
"""

import json
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

import yaml

from .models import Blueprint, BlueprintItem

logger = logging.getLogger(__name__)


class BlueprintParseError(Exception):
    """Raised when Blueprint parsing fails."""
    
    def __init__(self, message: str, source: Optional[str] = None, line: Optional[int] = None):
        self.source = source
        self.line = line
        super().__init__(f"{message}" + (f" (at {source}:{line})" if source and line else ""))


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
        
        for line_num, line in enumerate(lines, start=1):
            # Skip comments and empty lines
            if line.strip().startswith("<!--") or not line.strip():
                continue
            if line.strip().startswith("-->"):
                continue
            if line.strip().startswith("<!--"):
                # Skip until -->
                continue
            
            # Try to match a task line
            task_match = self.TASK_LINE_PATTERN.match(line)
            if task_match:
                indent = len(task_match.group(1))
                is_checked = task_match.group(2).lower() == "x"
                ident = task_match.group(3)
                title = task_match.group(4).strip()
                metadata_str = task_match.group(5)
                
                # Parse inline metadata
                metadata = self._parse_inline_metadata(metadata_str) if metadata_str else {}
                
                # Determine parent
                parent_id = None
                while parent_stack and parent_stack[-1][0] >= indent:
                    parent_stack.pop()
                if parent_stack:
                    parent_id = parent_stack[-1][1].id
                
                # Create item
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
            
            # Parse sub-bullets for current item
            if current_item:
                # Acceptance criteria
                acc_match = self.ACCEPTANCE_PATTERN.match(line)
                if acc_match:
                    current_item.acceptance_criteria.append(acc_match.group(1).strip())
                    continue
                
                # Dependencies
                dep_match = self.DEPENDS_PATTERN.match(line)
                if dep_match:
                    deps = [d.strip().strip("<>") for d in dep_match.group(1).split(",")]
                    current_item.depends_on.extend(deps)
                    continue
                
                # Recipe
                recipe_match = self.RECIPE_PATTERN.match(line)
                if recipe_match:
                    current_item.recipe = recipe_match.group(1).strip()
                    continue
                
                # Description
                desc_match = self.DESCRIPTION_PATTERN.match(line)
                if desc_match:
                    current_item.description = desc_match.group(1).strip()
                    continue
        
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

