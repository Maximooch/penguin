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
async def test_validation_fails_closed_when_no_tests_collected(monkeypatch, tmp_path):
    manager = ValidationManager(workspace_path=tmp_path)
    task = SimpleNamespace(title="No Tests Task")

    async def fake_create_subprocess_exec(*args, **kwargs):
        return FakeProcess(returncode=5, stdout="collected 0 items", stderr="")

    monkeypatch.setattr(
        "asyncio.create_subprocess_exec",
        fake_create_subprocess_exec,
    )

    result = await manager.validate_task_completion(task, changed_files=[])

    assert result["validated"] is False
    assert result["summary"] == "No tests found to run."
    assert result["evidence"]["pytest_exit_code"] == 5


@pytest.mark.asyncio
async def test_validation_fails_closed_when_pytest_missing(monkeypatch, tmp_path):
    manager = ValidationManager(workspace_path=tmp_path)
    task = SimpleNamespace(title="Missing Pytest Task")

    async def fake_create_subprocess_exec(*args, **kwargs):
        raise FileNotFoundError("pytest not found")

    monkeypatch.setattr(
        "asyncio.create_subprocess_exec",
        fake_create_subprocess_exec,
    )

    result = await manager.validate_task_completion(task, changed_files=[])

    assert result["validated"] is False
    assert result["summary"] == "Validation failed: pytest not found."
    assert result["evidence"]["pytest_available"] is False
