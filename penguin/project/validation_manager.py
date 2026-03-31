"""Validation Manager for Penguin.

For the MVP, this module implements a validation step centered on pytest.
"""

import asyncio
import logging
from pathlib import Path
from typing import Any, Dict, List, Union

from penguin.project.models import Task

logger = logging.getLogger(__name__)


class ValidationManager:
    """Manages validation of task deliverables by running tests."""

    def __init__(self, workspace_path: Union[str, Path]):
        """Initialize ValidationManager.

        Args:
            workspace_path: Path to the workspace root where tests will be run.
        """
        self.workspace_path = Path(workspace_path)
        logger.info("ValidationManager initialized.")

    def _build_acceptance_criteria_results(
        self,
        task: Task,
        tests_passed: bool,
        tests_run: bool,
    ) -> List[Dict[str, Any]]:
        """Build a minimal evidence map for acceptance criteria."""
        criteria = list(getattr(task, "acceptance_criteria", []) or [])

        if not criteria:
            return []

        if tests_passed and tests_run:
            status = "covered_by_test_evidence"
        else:
            status = "unchecked"

        return [
            {
                "criterion": criterion,
                "status": status,
            }
            for criterion in criteria
        ]

    async def validate_task_completion(self, task: Task, changed_files: List[str]) -> Dict[str, Any]:
        """Validate task completion by running pytest, targeting changed files."""
        logger.info("Performing validation for task: %s", task.title)

        test_files_to_run = [
            file for file in changed_files
            if file.startswith("tests/") or file.startswith("test_") or file.endswith("_test.py")
        ]

        if test_files_to_run:
            command = ["pytest"] + test_files_to_run
            logger.info(
                "Found %s changed test files. Running targeted tests.",
                len(test_files_to_run),
            )
        else:
            command = ["pytest"]
            logger.info("No test files were modified. Running full test suite as a fallback.")

        evidence: Dict[str, Any] = {
            "command": command,
            "changed_files": changed_files,
            "test_files_to_run": test_files_to_run,
            "targeted": bool(test_files_to_run),
            "pytest_available": True,
            "pytest_exit_code": None,
            "stdout": "",
            "stderr": "",
            "tests_run": False,
            "tests_passed": False,
        }

        try:
            process = await asyncio.create_subprocess_exec(
                *command,
                cwd=self.workspace_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=300)
            stdout_text = stdout.decode()
            stderr_text = stderr.decode()

            evidence["pytest_exit_code"] = process.returncode
            evidence["stdout"] = stdout_text
            evidence["stderr"] = stderr_text

            if process.returncode == 0:
                validated = True
                summary = "Tests passed."
                evidence["tests_run"] = True
                evidence["tests_passed"] = True
            elif process.returncode == 5:
                validated = False
                summary = "No tests found to run."
            else:
                validated = False
                summary = "Tests failed."
                evidence["tests_run"] = True

            acceptance_criteria_results = self._build_acceptance_criteria_results(
                task=task,
                tests_passed=evidence["tests_passed"],
                tests_run=evidence["tests_run"],
            )
            acceptance_criteria_gate_passed = all(
                item["status"] == "covered_by_test_evidence"
                for item in acceptance_criteria_results
            )

            if not acceptance_criteria_results:
                acceptance_criteria_gate_passed = True

            details = (
                f"pytest exit code: {process.returncode}\n\n"
                f"STDOUT:\n{stdout_text}\n\nSTDERR:\n{stderr_text}"
            )

            logger.info(
                "Validation for '%s' completed. Success: %s.",
                task.title,
                validated,
            )

            return {
                "validated": validated,
                "summary": summary,
                "details": details,
                "evidence": evidence,
                "review_required": bool(getattr(task, "acceptance_criteria", [])),
                "acceptance_criteria_results": acceptance_criteria_results,
                "acceptance_criteria_gate_passed": acceptance_criteria_gate_passed,
            }

        except FileNotFoundError:
            logger.warning("`pytest` command not found. Failing validation closed.")
            evidence["pytest_available"] = False
            acceptance_criteria_results = self._build_acceptance_criteria_results(
                task=task,
                tests_passed=False,
                tests_run=False,
            )
            return {
                "validated": False,
                "summary": "Validation failed: pytest not found.",
                "details": "Pytest is not installed in the environment.",
                "evidence": evidence,
                "review_required": bool(getattr(task, "acceptance_criteria", [])),
                "acceptance_criteria_results": acceptance_criteria_results,
                "acceptance_criteria_gate_passed": False if acceptance_criteria_results else True,
            }
        except asyncio.TimeoutError:
            logger.error("Validation for '%s' timed out.", task.title)
            acceptance_criteria_results = self._build_acceptance_criteria_results(
                task=task,
                tests_passed=False,
                tests_run=False,
            )
            return {
                "validated": False,
                "summary": "Tests timed out.",
                "details": "The test suite took longer than 5 minutes to run.",
                "evidence": evidence,
                "review_required": bool(getattr(task, "acceptance_criteria", [])),
                "acceptance_criteria_results": acceptance_criteria_results,
                "acceptance_criteria_gate_passed": False if acceptance_criteria_results else True,
            }
        except Exception as exc:
            logger.error(
                "An unexpected error occurred during validation for '%s': %s",
                task.title,
                exc,
                exc_info=True,
            )
            acceptance_criteria_results = self._build_acceptance_criteria_results(
                task=task,
                tests_passed=False,
                tests_run=False,
            )
            return {
                "validated": False,
                "summary": "An unexpected error occurred during validation.",
                "details": str(exc),
                "evidence": evidence,
                "review_required": bool(getattr(task, "acceptance_criteria", [])),
                "acceptance_criteria_results": acceptance_criteria_results,
                "acceptance_criteria_gate_passed": False if acceptance_criteria_results else True,
            }
