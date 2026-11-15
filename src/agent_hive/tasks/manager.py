"""Task Manager — creation, state machine, dependencies, retries, recovery.

Task lifecycle::

    pending ──▶ queued ──▶ assigned ──▶ running ──▶ completed
                 ▲            │            │
                 │            └── cancel   └──▶ failed ──retry──▶ queued
                 └── blocked (deps unmet)

Every transition is recorded in the audit log; every task carries its
own attempts/max_retries/timeout budget and can be recovered after a
system restart (``recover()`` resets orphaned ``running`` tasks).
"""

from __future__ import annotations

from datetime import UTC
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from agent_hive.config.settings import get_settings
from agent_hive.core.errors import DependencyError
from agent_hive.core.events import EventBus
from agent_hive.db.base import get_session_factory
from agent_hive.db.models import Task


class TaskManager:
    """Async service over the ``tasks`` table."""

    def __init__(self, event_bus: EventBus) -> None:
        self.events = event_bus

    # ---------------------------------------------------------------- create
    async def create(
        self,
        title: str,
        description: str = "",
        payload: dict[str, Any] | None = None,
        *,
        parent_id: str | None = None,
        mission_id: str | None = None,
        agent_name: str | None = None,
        priority: int = 5,
        mode: str = "A",
        depends_on: list[str] | None = None,
        timeout_s: int | None = None,
        max_retries: int | None = None,
        created_by: str = "master",
        status: str = Task.STATUS_QUEUED,
    ) -> Task:
        settings = get_settings()
        task = Task(
            title=title,
            description=description,
            payload=payload or {},
            parent_id=parent_id,
            mission_id=mission_id,
            agent_name=agent_name,
            priority=max(1, min(9, priority)),
            mode=mode,
            depends_on=depends_on or [],
            timeout_s=timeout_s or settings.default_task_timeout,
            max_retries=settings.default_max_retries if max_retries is None else max_retries,
            created_by=created_by,
            status=status,
        )

        async def _write(sess: AsyncSession) -> Task:
            # Validate dependencies exist (prevents dangling references)
            if task.depends_on:
                rows = await sess.execute(
                    select(Task.id).where(Task.id.in_(task.depends_on))
                )
                found = {r[0] for r in rows}
                missing = set(task.depends_on) - found
                if missing:
                    raise DependencyError(f"Unknown dependencies: {sorted(missing)}")
            sess.add(task)
            await sess.commit()
            await sess.refresh(task)
            return task

        factory = get_session_factory()
        async with factory() as sess:
            task = await _write(sess)
        await self.events.publish(
            "task.created", created_by,
            task_id=task.id, title=task.title, agent=agent_name, mode=mode,
        )
        return task

    # ------------------------------------------------------------------ read
    async def get(self, task_id: str) -> Task | None:
        factory = get_session_factory()
        async with factory() as sess:
            return (await sess.execute(
                select(Task).where(Task.id == task_id)
            )).scalar_one_or_none()

    async def list(
        self,
        status: str | None = None,
        mission_id: str | None = None,
        agent_name: str | None = None,
        limit: int = 100,
    ) -> list[Task]:
        factory = get_session_factory()
        async with factory() as sess:
            stmt = select(Task)
            if status:
                stmt = stmt.where(Task.status == status)
            if mission_id:
                stmt = stmt.where(Task.mission_id == mission_id)
            if agent_name:
                stmt = stmt.where(Task.agent_name == agent_name)
            stmt = stmt.order_by(Task.priority, Task.created_at).limit(limit)
            return list((await sess.execute(stmt)).scalars())

    async def stats(self) -> dict[str, int]:
        factory = get_session_factory()
        async with factory() as sess:
            rows = await sess.execute(
                select(Task.status, func.count()).group_by(Task.status)
            )
            return {status: count for status, count in rows}

    # ----------------------------------------------------------- transitions
    async def set_status(
        self, task_id: str, status: str, session: AsyncSession | None = None, **fields: Any
    ) -> None:
        async def _write(sess: AsyncSession) -> None:
            values: dict[str, Any] = {"status": status, **fields}
            await sess.execute(update(Task).where(Task.id == task_id).values(**values))

        if session is not None:
            await _write(session)
        else:
            factory = get_session_factory()
            async with factory() as sess:
                await _write(sess)
                await sess.commit()
        await self.events.publish("task.status", "task_manager",
                                  task_id=task_id, status=status, **fields)

    async def mark_assigned(self, task_id: str, agent_name: str) -> None:
        await self.set_status(task_id, Task.STATUS_ASSIGNED, agent_name=agent_name)

    async def mark_running(self, task_id: str) -> None:
        from datetime import datetime

        factory = get_session_factory()
        async with factory() as sess:
            await sess.execute(
                update(Task)
                .where(Task.id == task_id)
                .values(
                    status=Task.STATUS_RUNNING,
                    started_at=datetime.now(UTC),
                )
            )
            task = (await sess.execute(
                select(Task).where(Task.id == task_id)
            )).scalar_one()
            task.attempts += 1
            await sess.commit()
        await self.events.publish("task.running", "task_manager", task_id=task_id)

    async def record_result(self, task_id: str, result: dict[str, Any]) -> Task:
        factory = get_session_factory()
        async with factory() as sess:
            task = (await sess.execute(
                select(Task).where(Task.id == task_id)
            )).scalar_one()
            task.result = result
            task.status = Task.STATUS_COMPLETED
            task.completed_at = func_now()
            task.error = None
            await sess.commit()
            await sess.refresh(task)
        await self.events.publish("task.completed", task.agent_name or "unknown",
                                  task_id=task_id)
        return task

    async def record_failure(self, task_id: str, error: str) -> Task:
        """Record a failure; retry automatically while attempts remain."""
        factory = get_session_factory()
        async with factory() as sess:
            task = (await sess.execute(
                select(Task).where(Task.id == task_id)
            )).scalar_one()
            task.error = error
            task.attempts += 1
            if task.attempts <= task.max_retries:
                task.status = Task.STATUS_QUEUED  # schedule retry
                task.agent_name = None            # allow re-assignment
                retried = True
            else:
                task.status = Task.STATUS_FAILED
                task.completed_at = func_now()
                retried = False
            await sess.commit()
            await sess.refresh(task)
        await self.events.publish("task.failed", "task_manager",
                                  task_id=task_id, error=error[:200], retried=retried)
        return task

    async def cancel(self, task_id: str) -> Task | None:
        factory = get_session_factory()
        async with factory() as sess:
            task = (await sess.execute(
                select(Task).where(Task.id == task_id)
            )).scalar_one_or_none()
            if task and task.status not in Task.TERMINAL_STATUSES:
                task.status = Task.STATUS_CANCELLED
                task.completed_at = func_now()
                await sess.commit()
                await sess.refresh(task)
                return task
        return None

    # ----------------------------------------------------------- scheduling
    async def ready_tasks(self, limit: int = 50) -> list[Task]:
        """Queued tasks whose dependencies are all completed."""
        factory = get_session_factory()
        async with factory() as sess:
            tasks = (await sess.execute(
                select(Task)
                .where(Task.status.in_([Task.STATUS_QUEUED, Task.STATUS_BLOCKED]))
                .order_by(Task.priority, Task.created_at)
                .limit(limit)
            )).scalars().all()
            ready: list[Task] = []
            for task in tasks:
                if not task.depends_on:
                    ready.append(task)
                    continue
                rows = await sess.execute(
                    select(Task.id, Task.status).where(Task.id.in_(task.depends_on))
                )
                dep_status = {tid: st for tid, st in rows}
                if all(st == Task.STATUS_COMPLETED for st in dep_status.values()):
                    ready.append(task)
                elif any(
                    st in Task.TERMINAL_STATUSES and st != Task.STATUS_COMPLETED
                    for st in dep_status.values()
                ):
                    # A dependency failed terminally — mark blocked for triage
                    await self.set_status(task.id, Task.STATUS_BLOCKED, session=sess)
        return ready

    async def recover(self) -> int:
        """After restart: reset orphaned running/assigned tasks to queued."""
        factory = get_session_factory()
        async with factory() as sess:
            res = await sess.execute(
                update(Task)
                .where(Task.status.in_([Task.STATUS_RUNNING, Task.STATUS_ASSIGNED]))
                .values(status=Task.STATUS_QUEUED, agent_name=None, error="recovered after restart")
            )
            count = res.rowcount or 0
            await sess.commit()
        if count:
            await self.events.publish("tasks.recovered", "task_manager", count=count)
        return count


def func_now():
    from datetime import datetime
    return datetime.now(UTC)


__all__ = ["TaskManager", "func_now"]
