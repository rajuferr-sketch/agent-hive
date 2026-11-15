"""Tests for the task state machine: creation, DAG dependencies,
retries, cancellation and recovery."""

from __future__ import annotations

import uuid

import pytest

from agent_hive.core.errors import DependencyError
from agent_hive.core.events import EventBus
from agent_hive.db.models import Task
from agent_hive.tasks.manager import TaskManager


def _manager() -> TaskManager:
    return TaskManager(EventBus())


async def test_create_task_starts_queued() -> None:
    """New tasks are created directly in the queued state."""
    tasks = _manager()
    task = await tasks.create("Queued probe", agent_name="analyst")
    assert task.status == Task.STATUS_QUEUED
    assert task.attempts == 0
    stored = await tasks.get(task.id)
    assert stored is not None and stored.title == "Queued probe"


async def test_create_rejects_unknown_dependency() -> None:
    """Dangling depends_on references are rejected at creation."""
    tasks = _manager()
    with pytest.raises(DependencyError, match="Unknown dependencies"):
        await tasks.create("Orphan", depends_on=["nonexistent-id"])


async def test_dependency_dag_gates_readiness() -> None:
    """A task depending on A is not ready until A is completed."""
    tasks = _manager()
    tag = uuid.uuid4().hex[:8]
    first = await tasks.create(f"Stage A {tag}", payload={"tag": tag})
    second = await tasks.create(
        f"Stage B {tag}", depends_on=[first.id], payload={"tag": tag}
    )

    ready = await tasks.ready_tasks()
    assert first.id in {t.id for t in ready}
    assert second.id not in {t.id for t in ready}  # blocked by dependency

    await tasks.record_result(first.id, {"answer": "done"})
    ready_after = await tasks.ready_tasks()
    assert second.id in {t.id for t in ready_after}

    completed = await tasks.get(first.id)
    assert completed.status == Task.STATUS_COMPLETED
    assert completed.result == {"answer": "done"}
    assert completed.completed_at is not None


async def test_record_failure_retries_then_fails() -> None:
    """Failures requeue the task while attempts remain, then mark FAILED."""
    tasks = _manager()
    task = await tasks.create("Retry budget", max_retries=1)
    assert task.max_retries == 1

    after_first = await tasks.record_failure(task.id, "boom #1")
    assert after_first.status == Task.STATUS_QUEUED, "still has retries left"
    assert after_first.attempts == 1
    assert after_first.error == "boom #1"
    assert after_first.agent_name is None, "failed task is re-assignable"

    after_second = await tasks.record_failure(task.id, "boom #2")
    assert after_second.status == Task.STATUS_FAILED
    assert after_second.attempts == 2
    assert after_second.completed_at is not None


async def test_cancel_terminal_task_is_noop() -> None:
    """Cancelling twice yields None the second time (already terminal)."""
    tasks = _manager()
    task = await tasks.create("Cancellable")
    cancelled = await tasks.cancel(task.id)
    assert cancelled is not None
    assert cancelled.status == Task.STATUS_CANCELLED
    assert cancelled.completed_at is not None
    assert await tasks.cancel(task.id) is None


async def test_recover_resets_running_tasks() -> None:
    """Orphaned running/assigned tasks are reset to queued after restart."""
    tasks = _manager()
    running = await tasks.create("Interrupted job")
    assigned = await tasks.create("Interrupted assignment")
    await tasks.mark_running(running.id)
    await tasks.mark_assigned(assigned.id, "analyst")

    recovered = await tasks.recover()
    assert recovered >= 2

    for task_id in (running.id, assigned.id):
        task = await tasks.get(task_id)
        assert task.status == Task.STATUS_QUEUED
        assert task.agent_name is None
        assert task.error == "recovered after restart"


async def test_stats_reports_status_counts() -> None:
    """stats() aggregates per-status task counts."""
    tasks = _manager()
    task = await tasks.create("Stats sample")
    stats = await tasks.stats()
    assert stats.get(Task.STATUS_QUEUED, 0) >= 1
    assert sum(stats.values()) >= 1

    await tasks.cancel(task.id)
    stats_after = await tasks.stats()
    assert stats_after.get(Task.STATUS_CANCELLED, 0) >= 1


async def test_priority_is_clamped() -> None:
    """Priorities outside 1..9 are clamped into range."""
    tasks = _manager()
    high = await tasks.create("Too urgent", priority=0)
    low = await tasks.create("Whatever", priority=99)
    assert high.priority == 1
    assert low.priority == 9
