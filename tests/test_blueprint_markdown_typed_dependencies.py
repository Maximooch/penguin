from pathlib import Path

import pytest

from penguin.project.blueprint_parser import BlueprintParseError, BlueprintParser
from penguin.project.models import DependencyPolicy


def test_markdown_dependency_specs_override_depends_policy(tmp_path: Path):
    blueprint_path = tmp_path / "typed.md"
    blueprint_path.write_text(
        """---
title: "Typed Markdown"
project_key: "AUTH"
---

# Typed Markdown

## Tasks

- [ ] <AUTH-1> Base task
  - Acceptance: done

- [ ] <AUTH-2> Docs task
  - Depends:
    - <AUTH-1>
  - Dependency Specs:
    - task_id: <AUTH-1>
      policy: review_ready_ok
"""
    )

    parser = BlueprintParser(base_path=tmp_path)
    blueprint = parser.parse_file(blueprint_path)

    item = next(task for task in blueprint.items if task.id == "AUTH-2")
    assert item.depends_on == ["AUTH-1"]
    assert len(item.dependency_specs) == 1
    assert item.dependency_specs[0].task_id == "AUTH-1"
    assert item.dependency_specs[0].policy == DependencyPolicy.REVIEW_READY_OK


def test_markdown_dependency_specs_support_artifact_ready(tmp_path: Path):
    blueprint_path = tmp_path / "artifact.md"
    blueprint_path.write_text(
        """---
title: "Artifact Markdown"
project_key: "WEB"
---

# Artifact Markdown

## Tasks

- [ ] <SCHEMA-1> Generate client
  - Acceptance: client exists

- [ ] <WEB-1> Integrate generated client
  - Depends:
    - <SCHEMA-1>
  - Dependency Specs:
    - task_id: <SCHEMA-1>
      policy: artifact_ready
      artifact_key: generated_client
"""
    )

    parser = BlueprintParser(base_path=tmp_path)
    blueprint = parser.parse_file(blueprint_path)

    item = next(task for task in blueprint.items if task.id == "WEB-1")
    assert item.depends_on == ["SCHEMA-1"]
    assert len(item.dependency_specs) == 1
    assert item.dependency_specs[0].policy == DependencyPolicy.ARTIFACT_READY
    assert item.dependency_specs[0].artifact_key == "generated_client"


def test_markdown_artifact_ready_requires_artifact_key(tmp_path: Path):
    blueprint_path = tmp_path / "invalid-artifact.md"
    blueprint_path.write_text(
        """---
title: "Invalid Artifact"
project_key: "WEB"
---

# Invalid Artifact

## Tasks

- [ ] <SCHEMA-1> Generate client
  - Acceptance: client exists

- [ ] <WEB-1> Integrate generated client
  - Depends:
    - <SCHEMA-1>
  - Dependency Specs:
    - task_id: <SCHEMA-1>
      policy: artifact_ready
"""
    )

    parser = BlueprintParser(base_path=tmp_path)

    with pytest.raises(BlueprintParseError, match="artifact_key"):
        parser.parse_file(blueprint_path)


def test_markdown_duplicate_conflicting_dependency_specs_fail(tmp_path: Path):
    blueprint_path = tmp_path / "conflict.md"
    blueprint_path.write_text(
        """---
title: "Conflict"
project_key: "AUTH"
---

# Conflict

## Tasks

- [ ] <AUTH-1> Base task
  - Acceptance: done

- [ ] <AUTH-2> Dependent task
  - Depends:
    - <AUTH-1>
  - Dependency Specs:
    - task_id: <AUTH-1>
      policy: completion_required
    - task_id: <AUTH-1>
      policy: review_ready_ok
"""
    )

    parser = BlueprintParser(base_path=tmp_path)

    with pytest.raises(BlueprintParseError, match="conflicting dependency spec"):
        parser.parse_file(blueprint_path)


def test_markdown_dependency_specs_without_depends_fail(tmp_path: Path):
    blueprint_path = tmp_path / "missing-depends.md"
    blueprint_path.write_text(
        """---
title: "Missing Depends"
project_key: "AUTH"
---

# Missing Depends

## Tasks

- [ ] <AUTH-1> Base task
  - Acceptance: done

- [ ] <AUTH-2> Dependent task
  - Dependency Specs:
    - task_id: <AUTH-1>
      policy: review_ready_ok
"""
    )

    parser = BlueprintParser(base_path=tmp_path)

    with pytest.raises(BlueprintParseError, match="must also appear in Depends"):
        parser.parse_file(blueprint_path)
