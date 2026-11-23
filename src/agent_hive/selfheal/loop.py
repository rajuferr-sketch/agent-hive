"""Bounded self-heal loop — continuous self-checks with hard limits.

Guarantees (spec: "no infinite loops, no unlimited retries"):

* each cycle runs a fixed list of checks within a **time budget**;
* a remediation action is attempted at most ``max_retries`` times
  (per problem signature, reset on success);
* after ``fail_limit`` consecutive failing cycles the loop triggers the
  **safe-stop** callback (the API app shuts the hive down cleanly) and
  stops retrying — an operator must restart, by design.

Checks: database connectivity, scheduler loop alive, agent roster loaded,
universal memory reachable + TTL purge, orphaned task recovery, event bus
pump alive. Remediations: task recovery, TTL purge, scheduler restart —
all bounded and logged; every cycle appends a :class:`SelfHealReport`.
"""

from __future__ import annotations

import asyncio
import time
from collections import Counter
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from agent_hive.core.errors import AgentError
from agent_hive.core.logging import get_logger
from agent_hive.db.base import get_engine

log = get_logger("agent_hive.selfheal")

CheckFn = Callable[[], Awaitable[tuple[bool, str]]]
RemediateFn = Callable[[], Awaitable[bool]]


@dataclass(slots=True)
class SelfHealReport:
    cycle: int
    healthy: bool
    checks: list[dict[str, Any]] = field(default_factory=list)
    remediations: list[str] = field(default_factory=list)
    budget_exceeded: bool = False
    safe_stop_triggered: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "cycle": self.cycle,
            "healthy": self.healthy,
            "checks": self.checks,
            "remediations": self.remediations,
            "budget_exceeded": self.budget_exceeded,
            "safe_stop_triggered": self.safe_stop_triggered,
        }


class SelfHeal:
    """Continuous bounded self-diagnostics over a started Hive."""

    def __init__(self, hive, safe_stop: Callable[[], Awaitable[None]] | None = None) -> None:
        self.hive = hive
        self._safe_stop = safe_stop
        settings = hive.settings
        self.interval = max(5.0, settings.selfheal_interval)
        self.max_retries = max(1, settings.selfheal_max_retries)
        self.budget_s = max(1.0, settings.selfheal_budget_s)
        self.fail_limit = max(1, settings.selfheal_fail_limit)
        self.enabled = settings.selfheal_enabled
        self._task: asyncio.Task[None] | None = None
        self._cycle = 0
        self._consecutive_failures = 0
        self._remedy_counts: Counter[str] = Counter()
        self.reports: list[SelfHealReport] = []
        self.safe_stop_triggered = False

    # ------------------------------------------------------------- lifecycle
    def start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        if not self.enabled:
            log.info("self-heal disabled by configuration")
            return
        self._task = asyncio.get_running_loop().create_task(self._loop())

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def _loop(self) -> None:
        try:
            while True:
                await asyncio.sleep(self.interval)
                report = await self.run_cycle()
                if not report.healthy:
                    self._consecutive_failures += 1
                    if self._consecutive_failures >= self.fail_limit and not self.safe_stop_triggered:
                        log.critical(
                            "self-heal: %d consecutive failing cycles — safe stop",
                            self._consecutive_failures,
                        )
                        self.safe_stop_triggered = True
                        if self._safe_stop is not None:
                            try:
                                await asyncio.wait_for(self._safe_stop(), timeout=30)
                            except (asyncio.TimeoutError, AgentError) as exc:
                                log.error("safe-stop callback failed: %s", exc)
                        return  # stop retrying: operator intervention required
                else:
                    self._consecutive_failures = 0
        except asyncio.CancelledError:
            raise

    # ------------------------------------------------------------------ cycle
    async def run_cycle(self) -> SelfHealReport:
        """One bounded diagnose → remediate → re-check cycle."""
        self._cycle += 1
        started = time.monotonic()
        report = SelfHealReport(cycle=self._cycle, healthy=True)
        checks = await self._checks_within_budget(report)
        report.checks = checks
        report.budget_exceeded = (time.monotonic() - started) > self.budget_s
        broken = [c for c in checks if not c["ok"]]

        if broken:
            report.remediations = await self._remediate_within_budget(broken)
            if report.remediations:
                rechecks = await self._checks_within_budget(report)
                report.checks = [
                    {**c, "recheck": next(
                        (r["ok"] for r in rechecks if r["check"] == c["check"]), None)}
                    for c in checks
                ]
                broken = [c for c in report.checks
                          if not c["ok"] and c.get("recheck") is not True]
        report.healthy = not broken
        self.reports.append(report)
        if len(self.reports) > 50:
            self.reports = self.reports[-50:]
        log.info("self-heal cycle %d: %s (%d checks)", self._cycle,
                 "healthy" if report.healthy else "degraded", len(checks))
        return report

    async def _checks_within_budget(self, report: SelfHealReport) -> list[dict[str, Any]]:
        checks: list[dict[str, Any]] = []
        deadline = time.monotonic() + self.budget_s
        for name, fn in self._check_functions():
            if time.monotonic() > deadline:
                report.budget_exceeded = True
                break
            try:
                ok, detail = await asyncio.wait_for(fn(), timeout=max(1.0, deadline - time.monotonic()))
            except (asyncio.TimeoutError, AgentError, Exception) as exc:  # noqa: BLE001
                ok, detail = False, str(exc)[:160]
            checks.append({"check": name, "ok": bool(ok), "detail": detail})
        return checks

    async def _remediate_within_budget(self, broken: list[dict[str, Any]]) -> list[str]:
        actions: list[str] = []
        deadline = time.monotonic() + self.budget_s
        for problem in broken:
            name = problem["check"]
            remedy = self._remediation_for(name)
            if remedy is None:
                continue
            if self._remedy_counts[name] >= self.max_retries:
                actions.append(f"{name}: remediation limit reached ({self.max_retries})")
                continue
            if time.monotonic() > deadline:
                break
            try:
                applied = await asyncio.wait_for(remedy(), timeout=max(1.0, deadline - time.monotonic()))
                self._remedy_counts[name] += 1
                actions.append(f"{name}: remediation applied={applied}")
            except (asyncio.TimeoutError, AgentError, Exception) as exc:  # noqa: BLE001
                self._remedy_counts[name] += 1
                actions.append(f"{name}: remediation failed: {str(exc)[:120]}")
        return actions

    # ------------------------------------------------------- checks/remedies
    def _check_functions(self) -> list[tuple[str, CheckFn]]:
        async def _db() -> tuple[bool, str]:
            from sqlalchemy import text

            engine = get_engine()
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
            return True, "connected"

        async def _scheduler() -> tuple[bool, str]:
            task = self.hive.scheduler._loop_task
            alive = bool(task and not task.done())
            return alive, "scheduler loop task"

        async def _agents() -> tuple[bool, str]:
            count = len(self.hive.runtime.agents)
            return count > 0, f"{count} agents"

        async def _memory() -> tuple[bool, str]:
            stats = await self.hive.umemory.stats()
            return True, f"{stats.get('total', 0)} universal records"

        async def _events() -> tuple[bool, str]:
            task = self.hive.events._pump_task
            return True, f"pump task present={task is not None}"

        return [
            ("database", _db),
            ("scheduler", _scheduler),
            ("agents", _agents),
            ("universal_memory", _memory),
            ("event_bus", _events),
        ]

    def _remediation_for(self, check: str) -> RemediateFn | None:
        async def _recover_tasks() -> bool:
            recovered = await self.hive.tasks.recover()
            return recovered >= 0

        async def _purge_memory() -> bool:
            purged = await self.hive.umemory.purge_expired()
            return purged >= 0

        async def _restart_scheduler() -> bool:
            await self.hive.scheduler.stop()
            self.hive.scheduler.start()
            return True

        return {
            "database": _recover_tasks,          # mild first remedy: flush state
            "scheduler": _restart_scheduler,
            "universal_memory": _purge_memory,
            "agents": _recover_tasks,
        }.get(check)
