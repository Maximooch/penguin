"""Cancellation evidence belongs to the owned execution, not an observer."""

import asyncio

import pytest

from penguin.system.task_cancellation import (
    AbortReason,
    CancellationTrackingTask,
    abort_task,
    cancellation_owner,
    task_abort_reason,
)


@pytest.mark.asyncio
async def test_completed_task_does_not_acquire_cancellation_or_abort_intent():
    async def execute():
        return "done"

    task = CancellationTrackingTask(execute(), name="completed")
    assert await task == "done"
    assert task.cancel() is False
    abort_task(task, AbortReason.USER_INTERRUPTED)
    assert not task.cancellation_requested
    assert task_abort_reason(task) is None


@pytest.mark.asyncio
async def test_cancellation_before_start_does_not_execute_work():
    executed = False

    async def execute():
        nonlocal executed
        executed = True

    task = CancellationTrackingTask(execute(), name="not-started")
    assert task.cancel("shutdown") is True
    with pytest.raises(asyncio.CancelledError):
        await task
    assert task.cancellation_requested
    assert not executed


@pytest.mark.asyncio
async def test_uncancel_does_not_erase_durable_cancellation_evidence():
    started = asyncio.Event()

    async def execute():
        started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            task = asyncio.current_task()
            if hasattr(task, "uncancel"):
                task.uncancel()
            return "swallowed"

    task = CancellationTrackingTask(execute(), name="swallowed")
    await started.wait()
    task.cancel()
    assert await task == "swallowed"
    assert task.cancellation_requested
    assert task_abort_reason(task) is None


@pytest.mark.asyncio
async def test_cancellation_is_isolated_and_does_not_replace_task_factory():
    started = asyncio.Event()
    loop = asyncio.get_running_loop()
    factory = loop.get_task_factory()

    async def execute():
        started.set()
        await asyncio.Event().wait()

    first = CancellationTrackingTask(execute(), name="first")
    second = CancellationTrackingTask(execute(), name="second")
    await started.wait()
    abort_task(first, AbortReason.USER_INTERRUPTED)
    first.cancel("second cancellation request")
    assert not second.cancellation_requested
    assert task_abort_reason(second) is None
    assert task_abort_reason(first) is AbortReason.USER_INTERRUPTED
    second.cancel()
    await asyncio.gather(first, second, return_exceptions=True)
    assert loop.get_task_factory() is factory


@pytest.mark.asyncio
@pytest.mark.parametrize("explicit", [True, False])
async def test_child_cleanup_cannot_hide_boundary_stop(explicit):
    import anyio

    started = asyncio.Event()
    children = []

    async def execute():
        children.append(asyncio.current_task())
        with anyio.CancelScope() as scope:
            scope.cancel()
            await anyio.sleep(0)
        started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            # A swallowed/uncancelled shutdown is still owned by the outer task.
            if hasattr(asyncio.current_task(), "uncancel"):
                asyncio.current_task().uncancel()
            return "swallowed"

    async def run():
        return await asyncio.current_task().run_child(execute())

    owner = CancellationTrackingTask(run(), name="boundary")
    await started.wait()
    assert cancellation_owner(children[0]) is owner
    assert not owner.cancellation_requested
    if explicit:
        abort_task(children[0], AbortReason.USER_INTERRUPTED)
    else:
        owner.cancel()
    assert await owner == "swallowed"
    assert owner.cancellation_requested
    assert task_abort_reason(owner) == (
        AbortReason.USER_INTERRUPTED if explicit else None
    )
    assert cancellation_owner(children[0]) is children[0]
