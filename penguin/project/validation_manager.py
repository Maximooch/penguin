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
            elif process.returncode == 5:
                validated = False
                summary = "No tests found to run."
            else:
                validated = False
                summary = "Tests failed."

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
            }

        except FileNotFoundError:
            logger.warning("`pytest` command not found. Failing validation closed.")
            evidence["pytest_available"] = False
            return {
                "validated": False,
                "summary": "Validation failed: pytest not found.",
                "details": "Pytest is not installed in the environment.",
                "evidence": evidence,
            }
        except asyncio.TimeoutError:
            logger.error("Validation for '%s' timed out.", task.title)
            return {
                "validated": False,
                "summary": "Tests timed out.",
                "details": "The test suite took longer than 5 minutes to run.",
                "evidence": evidence,
            }
        except Exception as exc:
            logger.error(
                "An unexpected error occurred during validation for '%s': %s",
                task.title,
                exc,
                exc_info=True,
            )
            return {
                "validated": False,
                "summary": "An unexpected error occurred during validation.",
                "details": str(exc),
                "evidence": evidence,
            }
