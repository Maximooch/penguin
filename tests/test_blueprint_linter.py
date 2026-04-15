from pathlib import Path

import pytest

from penguin.project.blueprint_parser import (
    BlueprintDiagnostic,
    BlueprintDiagnosticsReport,
    BlueprintLinter,
    BlueprintParseError,
    BlueprintParser,
)


def test_parse_error_exposes_code_and_suggestion():
    error = BlueprintParseError(
        "artifact_ready dependency for SCHEMA-1 requires artifact_key",
        source="example.md",
        line=12,
        code="BP-PARSE-004",
        suggestion="Add artifact_key under Dependency Specs for task_id <SCHEMA-1>",
        task_id="SCHEMA-1",
    )

    assert error.code == "BP-PARSE-004"
    assert error.suggestion is not None
    assert error.task_id == "SCHEMA-1"
    assert "artifact_ready dependency" in str(error)


def test_linter_reports_duplicate_task_ids_and_missing_dependency_refs(tmp_path: Path):
    blueprint_path = tmp_path / "lint.yaml"
    blueprint_path.write_text(
        """
title: Lint Blueprint
project_key: LINT
tasks:
  - id: AUTH-1
    title: First task
    description: First task
    acceptance_criteria:
      - done
  - id: AUTH-1
    title: Duplicate task
    description: Duplicate task
    depends_on:
      - MISSING-1
""".strip()
    )

    parser = BlueprintParser(base_path=tmp_path)
    blueprint = parser.parse_file(blueprint_path)
    report = parser.lint_blueprint(blueprint, source=str(blueprint_path))

    assert report.has_errors
    codes = {diagnostic.code for diagnostic in report.diagnostics}
    assert "BP-LINT-001" in codes
    assert "BP-LINT-002" in codes


def test_linter_reports_dependency_cycles(tmp_path: Path):
    blueprint_path = tmp_path / "cycle.yaml"
    blueprint_path.write_text(
        """
title: Cycle Blueprint
project_key: CYCLE
tasks:
  - id: AUTH-1
    title: Task A
    description: Task A
    depends_on:
      - AUTH-2
  - id: AUTH-2
    title: Task B
    description: Task B
    depends_on:
      - AUTH-1
""".strip()
    )

    parser = BlueprintParser(base_path=tmp_path)
    blueprint = parser.parse_file(blueprint_path)
    report = parser.lint_blueprint(blueprint, source=str(blueprint_path))

    cycle_diagnostics = [d for d in report.diagnostics if d.code == "BP-LINT-003"]
    assert len(cycle_diagnostics) == 1
    assert cycle_diagnostics[0].severity == "error"


def test_linter_reports_high_signal_warnings(tmp_path: Path):
    blueprint_path = tmp_path / "warnings.yaml"
    blueprint_path.write_text(
        """
title: Warning Blueprint
project_key: WARN
tasks:
  - id: AUTH-1
    title: Missing signal
    description: Missing signal
    depends_on:
      - AUTH-0
    dependency_specs:
      - task_id: AUTH-0
        policy: completion_required
  - id: AUTH-0
    title: Base task
    description: Base task
""".strip()
    )

    parser = BlueprintParser(base_path=tmp_path)
    blueprint = parser.parse_file(blueprint_path)
    report = parser.lint_blueprint(blueprint, source=str(blueprint_path))

    warnings = {
        diagnostic.code
        for diagnostic in report.diagnostics
        if diagnostic.severity == "warning"
    }
    assert "BP-LINT-101" in warnings
    assert "BP-LINT-102" in warnings
    assert "BP-LINT-103" in warnings


def test_parser_raises_coded_error_for_missing_artifact_key(tmp_path: Path):
    blueprint_path = tmp_path / "invalid.md"
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

    with pytest.raises(BlueprintParseError) as exc_info:
        parser.parse_file(blueprint_path)

    error = exc_info.value
    assert error.code == "BP-PARSE-004"
    assert error.task_id == "SCHEMA-1"
    assert error.suggestion is not None


def test_diagnostics_report_helpers():
    report = BlueprintDiagnosticsReport(
        diagnostics=[
            BlueprintDiagnostic(code="X1", severity="warning", message="warn"),
            BlueprintDiagnostic(code="X2", severity="error", message="err"),
        ]
    )

    assert report.has_errors is True
    assert report.has_warnings is True
