from datetime import datetime
from pathlib import Path

import pytest

from penguin.project.exceptions import ValidationError
from penguin.project.manager import ProjectManager
from penguin.project.models import Task, TaskPhase, TaskStatus


def test_project_manager_resolves_task_recipe_from_blueprint_source(tmp_path: Path):
    blueprint_path = tmp_path / "blueprints" / "auth.md"
    blueprint_path.parent.mkdir(parents=True, exist_ok=True)
    blueprint_path.write_text(
        """# Auth Blueprint

## Tasks
- [ ] <AUTH-1> Implement auth flow
  - Recipe: smoke-auth-flow

## Usage Recipes
- recipe: smoke-auth-flow
  description: Smoke test auth flow
  - shell: echo auth-ok
""",
        encoding="utf-8",
    )

    manager = ProjectManager(tmp_path)
    task = Task(
        id="task-auth-1",
        title="Implement auth flow",
        description="Task with recipe",
        status=TaskStatus.ACTIVE,
        phase=TaskPhase.PENDING,
        blueprint_id="AUTH-1",
        blueprint_source=str(blueprint_path),
        recipe="smoke-auth-flow",
        created_at=datetime.utcnow().isoformat(),
        updated_at=datetime.utcnow().isoformat(),
    )
    manager.storage.create_task(task)

    resolved = manager.resolve_task_recipe(task.id)

    assert resolved is not None
    assert resolved["name"] == "smoke-auth-flow"
    assert resolved["steps"] == [{"shell": "echo auth-ok"}]


def test_project_manager_fails_closed_when_declared_recipe_is_missing(tmp_path: Path):
    blueprint_path = tmp_path / "blueprints" / "auth.md"
    blueprint_path.parent.mkdir(parents=True, exist_ok=True)
    blueprint_path.write_text(
        """# Auth Blueprint

## Tasks
- [ ] <AUTH-1> Implement auth flow
  - Recipe: missing-recipe

## Usage Recipes
- recipe: smoke-auth-flow
  description: Smoke test auth flow
  - shell: echo auth-ok
""",
        encoding="utf-8",
    )

    manager = ProjectManager(tmp_path)
    task = Task(
        id="task-auth-1",
        title="Implement auth flow",
        description="Task with missing recipe",
        status=TaskStatus.ACTIVE,
        phase=TaskPhase.PENDING,
        blueprint_id="AUTH-1",
        blueprint_source=str(blueprint_path),
        recipe="missing-recipe",
        created_at=datetime.utcnow().isoformat(),
        updated_at=datetime.utcnow().isoformat(),
    )
    manager.storage.create_task(task)

    with pytest.raises(ValidationError, match="Recipe 'missing-recipe' not found"):
        manager.resolve_task_recipe(task.id)
