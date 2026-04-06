from datetime import datetime
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from hypothesis import given, strategies as st
from hypothesis.stateful import RuleBasedStateMachine, initialize, invariant, rule

from penguin.project.manager import ProjectManager
from penguin.project.models import (
    ExecutionResult,
    Task,
    TaskDependency,
    TaskPhase,
    TaskStatus,
)
from penguin.run_mode import RunMode


def make_task(task_id: str = "task-1", **overrides) -> Task:
    base = {
        "id": task_id,
        "title": task_id,
        "description": task_id,
        "status": TaskStatus.ACTIVE,
        "phase": TaskPhase.PENDING,
        "created_at": datetime.utcnow().isoformat(),
        "updated_at": datetime.utcnow().isoformat(),
        "metadata": {},
    }
    base.update(overrides)
    return Task(**base)


class DummyCore:
    def __init__(self, project_manager, engine):
        self.project_manager = project_manager
        self.engine = engine
        self.emit_ui_event = AsyncMock()

    async def _handle_stream_chunk(self, *args, **kwargs):
        return None

    def finalize_streaming_message(self):
        return None


class TaskLifecycleStateMachine(RuleBasedStateMachine):
    def __init__(self):
        super().__init__()
        self.task = None

    @initialize()
    def init_task(self):
        self.task = make_task()

    @rule()
    def start_execution(self):
        self.task.start_execution()

    @rule()
    def complete_success(self):
        self.task.start_execution()
        self.task.complete_current_execution(ExecutionResult.SUCCESS, response="ok")

    @rule()
    def complete_failure(self):
        self.task.start_execution()
        self.task.complete_current_execution(ExecutionResult.FAILURE, error_details="boom")

    @rule()
    def reopen_to_active(self):
        self.task.transition_to(TaskStatus.ACTIVE, reason="reopen")

    @rule()
    def approve_if_review_ready(self):
        if self.task.status == TaskStatus.PENDING_REVIEW:
            self.task.approve("reviewer")

    @invariant()
    def completed_implies_done_phase(self):
        if self.task.status == TaskStatus.COMPLETED:
            assert self.task.phase == TaskPhase.DONE

    @invariant()
    def done_phase_implies_review_or_completed(self):
        if self.task.phase == TaskPhase.DONE:
            assert self.task.status in {
                TaskStatus.PENDING_REVIEW,
                TaskStatus.COMPLETED,
            }

    @invariant()
    def failed_task_is_not_done(self):
        if self.task.status == TaskStatus.FAILED:
            assert self.task.phase != TaskPhase.DONE


TestTaskLifecycleStateMachine = TaskLifecycleStateMachine.TestCase


@given(
    st.sampled_from(list(TaskStatus)),
    st.sampled_from(list(TaskPhase)),
)
def test_start_execution_never_leaves_task_in_non_running_terminal_state(status, phase):
    task = make_task(status=status, phase=phase)
    task.start_execution()

    assert task.status in {TaskStatus.ACTIVE, TaskStatus.RUNNING}
    assert task.get_current_execution() is not None


@given(st.booleans(), st.booleans())
@pytest.mark.asyncio
async def test_clarification_resume_preserves_task_identity_and_never_completes_implicitly(
    answered_by_human,
    seed_extra_metadata,
):
    with TemporaryDirectory() as tmpdir:
        manager = ProjectManager(tmpdir)
        project = manager.create_project("Clarification", "Clarification project")
        metadata = {}
        if seed_extra_metadata:
            metadata["note"] = "keep-me"

        task = make_task(
            task_id="task-clarify",
            status=TaskStatus.RUNNING,
            phase=TaskPhase.IMPLEMENT,
            project_id=project.id,
            metadata={
                **metadata,
                "clarification_requests": [
                    {
                        "task_id": "task-clarify",
                        "task_status": TaskStatus.RUNNING.value,
                        "task_phase": TaskPhase.IMPLEMENT.value,
                        "prompt": "Choose auth mode",
                        "status": "open",
                        "requested_at": "2026-04-02T00:00:00",
                    }
                ],
            },
        )
        manager.storage.create_task(task)

        engine = SimpleNamespace(settings=SimpleNamespace(streaming_default=False))
        core = DummyCore(project_manager=manager, engine=engine)
        run_mode = RunMode(core=core)
        run_mode._execute_task = AsyncMock(
            return_value={
                "status": "waiting_input",
                "message": "Need another answer",
                "completion_type": "clarification_needed",
            }
        )

        answered_by = "human" if answered_by_human else None
        result = await run_mode.resume_with_clarification(
            task_id="task-clarify",
            answer="Use rotating refresh tokens",
            answered_by=answered_by,
        )

        assert result["completion_type"] == "clarification_needed"

        reloaded = manager.get_task("task-clarify")
        assert reloaded is not None
        assert reloaded.id == "task-clarify"
        assert reloaded.status == TaskStatus.RUNNING
        assert reloaded.phase == TaskPhase.IMPLEMENT

        clarification = reloaded.metadata["clarification_requests"][0]
        assert clarification["status"] == "answered"
        assert clarification["answer"] == "Use rotating refresh tokens"
        assert clarification["task_id"] == "task-clarify"
        assert clarification["task_phase"] == TaskPhase.IMPLEMENT.value

        _, _, resumed_context = run_mode._execute_task.await_args.args
        assert resumed_context["task_id"] == "task-clarify"
        assert resumed_context["clarification_answer"] == "Use rotating refresh tokens"
        assert resumed_context["clarification_prompt"] == "Choose auth mode"
        if seed_extra_metadata:
            assert resumed_context["metadata"]["note"] == "keep-me"


@given(
    st.sampled_from(list(TaskStatus)),
    st.sampled_from(list(TaskPhase)),
    st.booleans(),
)
def test_artifact_ready_only_unlocks_on_matching_valid_artifact(status, phase, matching_key):
    with TemporaryDirectory() as tmpdir:
        manager = ProjectManager(tmpdir)
        artifact_key = "client_bundle"
        dependency = TaskDependency(
            task_id="dep-1",
            policy="artifact_ready",
            artifact_key=artifact_key,
        )

        task = make_task(task_id="dep-1", status=status, phase=phase)
        if matching_key:
            task.artifact_evidence = [
                {
                    "key": artifact_key,
                    "kind": "file",
                    "producer_task_id": "dep-1",
                    "valid": True,
                }
            ]
        else:
            task.artifact_evidence = [
                {
                    "key": "other_bundle",
                    "kind": "file",
                    "producer_task_id": "dep-1",
                    "valid": True,
                }
            ]

        satisfied = manager._is_dependency_satisfied(dependency, task)
        assert satisfied is matching_key
