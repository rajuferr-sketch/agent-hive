"""Scheduler — dispatches ready tasks to capable agents concurrently.

Guarantees
----------
* Respects ``MAX_CONCURRENCY`` via an asyncio semaphore.
* Per-task timeouts enforced with ``asyncio.wait_for``.
* Failures flow through ``TaskManager.record_failure`` (auto-retry).
* The mission monitor uses ``wait_for_mission`` to poll completion.
"""

from __future__ import annotations

import asyncio
from typing import Any

from agent_hive.core.errors import TaskError, TaskTimeout
from agent_hive.core.events import EventBus
from agent_hive.core.logging import get_logger
from agent_hive.db.models import Task
from agent_hive.tasks.manager import TaskManager

log = get_logger("agent_hive.scheduler")


class Scheduler:
    def __init__(
        self,
        task_manager: TaskManager,
        runtime: Any,  # AgentRuntime — injected to avoid circular imports
        event_bus: EventBus,
        max_concurrency: int = 8,
        poll_interval: float = 1.0,
    ) -> None:
        self.tasks = task_manager
        self.runtime = runtime
        self.events = event_bus
        self.semaphore = asyncio.Semaphore(max_concurrency)
        self.poll_interval = poll_interval
        self._running: dict[str, asyncio.Task[None]] = {}
        self._loop_task: asyncio.Task[None] | None = None
        self._stopping = asyncio.Event()

    # ------------------------------------------------------------- dispatch
    async def dispatch(self, task: Task) -> None:
        """Assign and execute a single task with timeout + error handling."""
        agent_name = task.agent_name or self.runtime.best_agent_for(
            capabilities_hint=task.payload.get("capabilities_hint", []),
            exclude_busy=False,
        )
        if agent_name is None:
            await self.tasks.record_failure(task.id, "no capable agent available")
            return
        await self.tasks.mark_assigned(task.id, agent_name)
        await self.tasks.mark_running(task.id)

        async def _runner() -> None:
            async with self.semaphore:
                try:
                    result = await asyncio.wait_for(
                        self.runtime.execute(agent_name, task),
                        timeout=task.timeout_s,
                    )
                    await self.tasks.record_result(task.id, result)
                except TimeoutError:
                    await self.tasks.record_failure(
                        task.id, f"timeout after {task.timeout_s}s"
                    )
                except TaskTimeout:
                    await self.tasks.record_failure(task.id, "internal timeout")
                except Exception as exc:  # noqa: BLE001 — isolate task failures
                    log.exception("Task %s failed", task.id)
                    await self.tasks.record_failure(task.id, f"{type(exc).__name__}: {exc}")

        runner = asyncio.get_running_loop().create_task(_runner())
        self._running[task.id] = runner
        runner.add_done_callback(lambda _: self._running.pop(task.id, None))

    async def run_cycle(self) -> int:
        """Pick up ready tasks and dispatch them. Returns dispatch count."""
        ready = await self.tasks.ready_tasks()
        for task in ready:
            await self.dispatch(task)
        return len(ready)

    # ------------------------------------------------------------------ loop
    async def run_forever(self) -> None:
        log.info("Scheduler started (interval=%.1fs)", self.poll_interval)
        while not self._stopping.is_set():
            try:
                await self.run_cycle()
            except Exception:  # noqa: BLE001 — keep the loop alive
                log.exception("Scheduler cycle error")
            try:
                await asyncio.wait_for(
                    self._stopping.wait(), timeout=self.poll_interval
                )
            except TimeoutError:
                pass
        log.info("Scheduler stopped")

    def start(self) -> None:
        self._stopping.clear()
        self._loop_task = asyncio.get_running_loop().create_task(self.run_forever())

    async def stop(self) -> None:
        self._stopping.set()
        if self._loop_task:
            try:
                await asyncio.wait_for(self._loop_task, timeout=5)
            except (TimeoutError, asyncio.CancelledError):
                self._loop_task.cancel()
        runners = list(self._running.values())
        for fut in runners:
            fut.cancel()
        # Await cancelled runners so no task is destroyed while pending.
        for fut in runners:
            try:
                await fut
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass

    # --------------------------------------------------------------- monitor
    async def wait_for_mission(
        self,
        mission_id: str,
        poll_interval: float = 2.0,
        max_wait_s: float = 900.0,
    ) -> dict[str, Any]:
        """Block until every task of a mission reaches a terminal status."""
        waited = 0.0
        while waited < max_wait_s:
            tasks = await self.tasks.list(mission_id=mission_id, limit=200)
            if tasks and all(t.status in Task.TERMINAL_STATUSES for t in tasks):
                return {
                    "completed": sum(t.status == "completed" for t in tasks),
                    "failed": sum(t.status == "failed" for t in tasks),
                    "cancelled": sum(t.status == "cancelled" for t in tasks),
                    "total": len(tasks),
                }
            await asyncio.sleep(poll_interval)
            waited += poll_interval
        raise TaskError(f"Mission {mission_id} did not finish within {max_wait_s}s")
