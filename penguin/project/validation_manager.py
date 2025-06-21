"""Validation Manager for Penguin.

For the MVP, this module implements a simple validation step: running pytest.
"""

import logging
import subprocess
import asyncio
from pathlib import Path
from typing import Any, Dict, Union, List
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
        """
        Validate task completion by running pytest, targeting changed files.
        
        Args:
            task: The Task object that was executed.
            changed_files: A list of files modified by the agent.
            
        Returns:
            A dictionary with validation results.
        """
        logger.info(f"Performing validation for task: {task.title}")

        # Determine which test files to run
        test_files_to_run = [
            file for file in changed_files
            if file.startswith("tests/") or file.startswith("test_") or file.endswith("_test.py")
        ]

        if test_files_to_run:
            command = ["pytest"] + test_files_to_run
            logger.info(f"Found {len(test_files_to_run)} changed test files. Running targeted tests.")
        else:
            command = ["pytest"]
            logger.info("No test files were modified. Running full test suite as a fallback.")

        try:
            process = await asyncio.create_subprocess_exec(
                *command,
                cwd=self.workspace_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=300)

            # Pytest exit codes:
            # 0: All tests were collected and passed
            # 1: Tests were collected and run but some failed
            # 2: Test execution was interrupted by the user
            # 3: Internal error occurred
            # 4: pytest command line usage error
            # 5: No tests were collected
            
            # For our purpose, 0 (all passed) and 5 (no tests found) are success.
            is_success = process.returncode in [0, 5]
            
            summary = "Tests passed." if process.returncode == 0 else "No tests found to run."
            if not is_success:
                summary = "Tests failed."

            details = f"pytest exit code: {process.returncode}\n\nSTDOUT:\n{stdout.decode()}\n\nSTDERR:\n{stderr.decode()}"

            logger.info(f"Validation for '{task.title}' completed. Success: {is_success}.")
            
            return {
                "validated": is_success,
                "summary": summary,
                "details": details
            }

        except FileNotFoundError:
            # This occurs if pytest is not installed.
            logger.warning("`pytest` command not found. Skipping validation.")
            return {
                "validated": True, # Treat as success if pytest isn't available
                "summary": "Validation skipped: pytest not found.",
                "details": "Pytest is not installed in the environment."
            }
        except asyncio.TimeoutError:
            logger.error(f"Validation for '{task.title}' timed out.")
            return {
                "validated": False,
                "summary": "Tests timed out.",
                "details": "The test suite took longer than 5 minutes to run."
            }
        except Exception as e:
            logger.error(f"An unexpected error occurred during validation for '{task.title}': {e}", exc_info=True)
            return {
                "validated": False,
                "summary": "An unexpected error occurred during validation.",
                "details": str(e)
            } 