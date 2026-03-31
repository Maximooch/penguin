from types import SimpleNamespace

import pytest

from penguin.project.validation_manager import ValidationManager


class FakeProcess:
    def __init__(self, returncode, stdout="", stderr=""):
        self.returncode = returncode
        self._stdout = stdout.encode()
        self._stderr = stderr.encode()

    async def communicate(self):
        return self._stdout, self._stderr


@pytest.mark.asyncio
async def test_validation_includes_acceptance_criteria_evidence(monkeypatch, tmp_path):
    manager = ValidationManager(workspace_path=tmp_path)
    task = SimpleNamespace(
        title="Acceptance Criteria Task",
        acceptance_criteria=[
            "CLI returns 200",
            "Response contains health payload",
        ],
    )

    async def fake_create_subprocess_exec(*args, **kwargs):
        return FakeProcess(returncode=0, stdout="2 passed", stderr="")

    monkeypatch.setattr(
        "asyncio.create_subprocess_exec",
        fake_create_subprocess_exec,
    )

    result = await manager.validate_task_completion(
        task,
        changed_files=["tests/test_health.py"],
    )

    assert result["validated"] is True
    assert result["review_required"] is True
    assert result["acceptance_criteria_gate_passed"] is True
    assert len(result["acceptance_criteria_results"]) == 2
    assert all(item["status"] == "covered_by_test_evidence" for item in result["acceptance_criteria_results"])
    assert result["evidence"]["tests_passed"] is True
    assert result["evidence"]["tests_run"] is True


@pytest.mark.asyncio
async def test_validation_marks_acceptance_criteria_unchecked_without_tests(monkeypatch, tmp_path):
    manager = ValidationManager(workspace_path=tmp_path)
    task = SimpleNamespace(
        title="Unchecked Acceptance Criteria Task",
        acceptance_criteria=["A real criterion"],
    )

    async def fake_create_subprocess_exec(*args, **kwargs):
        return FakeProcess(returncode=5, stdout="collected 0 items", stderr="")

    monkeypatch.setattr(
        "asyncio.create_subprocess_exec",
        fake_create_subprocess_exec,
    )

    result = await manager.validate_task_completion(task, changed_files=[])

    assert result["validated"] is False
    assert result["acceptance_criteria_gate_passed"] is False
    assert result["acceptance_criteria_results"][0]["status"] == "unchecked"
    assert result["evidence"]["tests_run"] is False
